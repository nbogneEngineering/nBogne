"""
nBogne Adapter - Main orchestration module.

This module provides the main NBogneAdapter class that:
    - Orchestrates all components (queue, transmitter, receiver)
    - Runs the queue drainer loop
    - Manages component lifecycle
    - Handles graceful shutdown

The adapter is the main entry point for running the nBogne transport layer
at a health facility.

Example:
    >>> from nbogne import NBogneAdapter, Config
    >>> 
    >>> config = Config.from_file("config/default.yaml")
    >>> adapter = NBogneAdapter(config)
    >>> 
    >>> # Start the adapter (blocking)
    >>> adapter.run()
    >>> 
    >>> # Or run in background
    >>> adapter.start()
    >>> # ... do other things ...
    >>> adapter.stop()
"""

import signal
import time
import logging
import threading
from typing import Optional, Dict, Any
from datetime import datetime

from nbogne.config import Config
from nbogne.wire_format import WireFormat
from nbogne.queue import PersistentQueue, QueueItemStatus
from nbogne.transmitter import Transmitter, TransmissionResult, TransmissionStatus
from nbogne.receiver import EMRReceiver

logger = logging.getLogger(__name__)


class NBogneAdapter:
    """Main nBogne Adapter orchestrator.
    
    This class manages the complete lifecycle of the nBogne adapter:
        - Initializes all components
        - Runs the queue drainer loop
        - Handles incoming FHIR from EMR
        - Transmits queued messages via GPRS
        - Manages graceful shutdown
    
    Architecture:
        ┌──────────────────────────────────────────────────────────┐
        │                    NBogneAdapter                         │
        │  ┌─────────────┐  ┌─────────────┐  ┌────────────────┐   │
        │  │ EMRReceiver │→ │   Queue     │→ │  Transmitter   │   │
        │  │  (HTTP)     │  │  (SQLite)   │  │   (GPRS)       │   │
        │  └─────────────┘  └─────────────┘  └────────────────┘   │
        │        ↑                                    ↓           │
        │      EMR                              nBogne Mediator   │
        └──────────────────────────────────────────────────────────┘
    
    Thread Model:
        - Main thread: Queue drainer loop
        - HTTP thread: EMRReceiver server
        - Both threads share the thread-safe PersistentQueue
    
    Example:
        >>> adapter = NBogneAdapter(config)
        >>> 
        >>> # Run with signal handling (recommended for production)
        >>> adapter.run()
        >>> 
        >>> # Or manage lifecycle manually
        >>> adapter.start()
        >>> while adapter.is_running:
        ...     time.sleep(1)
        >>> adapter.stop()
    """
    
    def __init__(self, config: Config):
        """Initialize the nBogne adapter.
        
        Args:
            config: Application configuration
        """
        self.config = config
        self._running = False
        self._stopping = False
        self._drainer_thread: Optional[threading.Thread] = None
        
        # Initialize components
        logger.info("Initializing nBogne Adapter...")
        
        self.wire_format = WireFormat()
        logger.debug("Wire format initialized")
        
        self.queue = PersistentQueue(
            db_path=config.queue.db_path,
            max_size=config.queue.max_size,
            max_retries=config.transmission.max_retries,
        )
        logger.debug(f"Queue initialized: {config.queue.db_path}")
        
        self.transmitter = Transmitter(
            config=config,
            on_success=self._on_transmission_success,
            on_failure=self._on_transmission_failure,
        )
        logger.debug(f"Transmitter initialized: {config.mediator.endpoint}")
        
        self.receiver = EMRReceiver(
            config=config,
            queue=self.queue,
            wire_format=self.wire_format,
        )
        logger.debug(
            f"Receiver initialized: "
            f"{config.server.host}:{config.server.port}{config.server.path}"
        )
        
        # Statistics
        self._stats_lock = threading.Lock()
        self._stats = {
            "started_at": None,
            "drain_cycles": 0,
            "messages_processed": 0,
        }
        
        logger.info(
            f"nBogne Adapter initialized: "
            f"facility={config.facility.id}, "
            f"mediator={config.mediator.endpoint}"
        )
    
    def start(self) -> None:
        """Start the adapter in background threads.
        
        This method starts:
            - EMR receiver HTTP server
            - Queue drainer thread
        
        The method returns immediately. Use is_running to check status
        and stop() to shutdown.
        """
        if self._running:
            logger.warning("Adapter already running")
            return
        
        self._running = True
        self._stopping = False
        
        with self._stats_lock:
            self._stats["started_at"] = datetime.utcnow().isoformat()
        
        # Start receiver
        self.receiver.start()
        
        # Start drainer thread
        self._drainer_thread = threading.Thread(
            target=self._drainer_loop,
            name="QueueDrainer",
            daemon=True,
        )
        self._drainer_thread.start()
        
        logger.info("nBogne Adapter started")
    
    def run(self, handle_signals: bool = True) -> None:
        """Run the adapter (blocking).
        
        This method starts the adapter and blocks until interrupted
        (Ctrl+C) or stop() is called from another thread.
        
        Args:
            handle_signals: Whether to install signal handlers for
                           graceful shutdown (SIGINT, SIGTERM)
        """
        if handle_signals:
            self._install_signal_handlers()
        
        self.start()
        
        try:
            while self._running and not self._stopping:
                time.sleep(0.5)
        except KeyboardInterrupt:
            logger.info("Received interrupt signal")
        finally:
            self.stop()
    
    def stop(self, timeout: float = 10.0) -> None:
        """Stop the adapter gracefully.
        
        Args:
            timeout: Seconds to wait for graceful shutdown
        """
        if not self._running:
            return
        
        logger.info("Stopping nBogne Adapter...")
        self._stopping = True
        
        # Stop receiver
        self.receiver.stop(timeout=timeout / 2)
        
        # Stop drainer
        self._running = False
        if self._drainer_thread:
            self._drainer_thread.join(timeout=timeout / 2)
        
        # Close components
        self.transmitter.close()
        self.queue.close()
        
        logger.info("nBogne Adapter stopped")
    
    def _drainer_loop(self) -> None:
        """Queue drainer main loop.
        
        This loop continuously:
            1. Fetches a batch of messages from the queue
            2. Transmits each message via GPRS
            3. Acknowledges or nacks based on result
            4. Sleeps between cycles
        """
        logger.info("Queue drainer started")
        
        batch_size = self.config.queue.batch_size
        drain_interval = self.config.queue.drain_interval
        
        while self._running:
            try:
                # Get batch of messages
                items = self.queue.get_batch(batch_size=batch_size)
                
                if not items:
                    # No messages, sleep and retry
                    time.sleep(drain_interval)
                    continue
                
                logger.debug(f"Processing batch of {len(items)} messages")
                
                for item in items:
                    if not self._running:
                        # Put item back if shutting down
                        self.queue.nack(item.id, "Shutdown requested")
                        break
                    
                    # Transmit
                    result = self.transmitter.send(
                        payload=item.payload,
                        message_id=item.message_id,
                        idempotency_key=item.message_id,
                    )
                    
                    # Handle result
                    if result.success:
                        self.queue.ack(item.id)
                        with self._stats_lock:
                            self._stats["messages_processed"] += 1
                    else:
                        self.queue.nack(item.id, result.error)
                
                with self._stats_lock:
                    self._stats["drain_cycles"] += 1
                
            except Exception as e:
                logger.error(f"Drainer loop error: {e}")
                time.sleep(drain_interval)
        
        logger.info("Queue drainer stopped")
    
    def _on_transmission_success(self, result: TransmissionResult) -> None:
        """Callback when transmission succeeds."""
        logger.debug(
            f"Transmission success: message_id={result.message_id}, "
            f"duration={result.duration_ms:.0f}ms"
        )
    
    def _on_transmission_failure(self, result: TransmissionResult) -> None:
        """Callback when transmission fails after all retries."""
        logger.warning(
            f"Transmission failed: message_id={result.message_id}, "
            f"attempts={result.attempts}, error={result.error}"
        )
    
    def _install_signal_handlers(self) -> None:
        """Install signal handlers for graceful shutdown."""
        def signal_handler(signum, frame):
            signame = signal.Signals(signum).name
            logger.info(f"Received {signame}, initiating shutdown...")
            self._stopping = True
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive adapter statistics.
        
        Returns:
            Dictionary with statistics from all components
        """
        with self._stats_lock:
            adapter_stats = dict(self._stats)
        
        return {
            "adapter": {
                **adapter_stats,
                "running": self._running,
                "facility_id": self.config.facility.id,
            },
            "queue": self.queue.get_stats(),
            "transmitter": self.transmitter.get_stats(),
            "receiver": self.receiver.get_stats(),
        }
    
    def health_check(self) -> Dict[str, Any]:
        """Perform a health check on all components.
        
        Returns:
            Dictionary with health status of each component
        """
        queue_stats = self.queue.get_stats()
        pending_count = queue_stats["by_status"].get("pending", 0)
        dead_count = queue_stats["by_status"].get("dead", 0)
        
        # Determine overall health
        issues = []
        
        if pending_count > 1000:
            issues.append(f"High queue backlog: {pending_count} pending")
        
        if dead_count > 100:
            issues.append(f"Many dead letters: {dead_count}")
        
        if not self.receiver.is_running:
            issues.append("EMR receiver not running")
        
        # Try mediator health check
        mediator_reachable = self.transmitter.health_check()
        if not mediator_reachable:
            issues.append("Mediator endpoint unreachable")
        
        return {
            "status": "unhealthy" if issues else "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "issues": issues,
            "components": {
                "queue": {
                    "healthy": pending_count < 1000 and dead_count < 100,
                    "pending": pending_count,
                    "dead": dead_count,
                },
                "receiver": {
                    "healthy": self.receiver.is_running,
                    "running": self.receiver.is_running,
                },
                "transmitter": {
                    "healthy": mediator_reachable,
                    "mediator_reachable": mediator_reachable,
                },
            },
        }
    
    @property
    def is_running(self) -> bool:
        """Check if the adapter is running."""
        return self._running and not self._stopping
    
    def __enter__(self):
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        return False
