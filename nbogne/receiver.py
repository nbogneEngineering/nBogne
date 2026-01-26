"""
EMR Receiver - HTTP endpoint for receiving FHIR data from local EMR.

This module provides an HTTP server that:
    - Receives FHIR bundles from the local EMR (OpenMRS, OpenEMR, etc.)
    - Validates incoming data
    - Encodes data using the wire format
    - Queues data for transmission

The receiver acts as the bridge between the EMR and the nBogne transport layer.

Example:
    >>> from nbogne.receiver import EMRReceiver
    >>> from nbogne.config import Config
    >>> 
    >>> config = Config.from_file("config/default.yaml")
    >>> receiver = EMRReceiver(config, queue, wire_format)
    >>> receiver.start()  # Starts HTTP server in background thread
    >>> # ...
    >>> receiver.stop()
"""

import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional, Dict, Any, Callable
from urllib.parse import urlparse, parse_qs
import uuid

from nbogne.config import Config
from nbogne.wire_format import WireFormat, MessageType
from nbogne.queue import PersistentQueue

logger = logging.getLogger(__name__)


@dataclass
class ReceivedMessage:
    """Represents a message received from the EMR.
    
    Attributes:
        message_id: Generated UUID for this message
        resource_type: FHIR resource type (Bundle, Patient, etc.)
        destination: Target facility ID
        payload: Raw FHIR JSON bytes
        received_at: Timestamp when message was received
        metadata: Additional metadata from headers
    """
    message_id: str
    resource_type: str
    destination: str
    payload: bytes
    received_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)


class EMRRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for EMR FHIR submissions.
    
    This handler processes POST requests containing FHIR bundles,
    validates them, and queues them for transmission.
    
    Supported Endpoints:
        POST /fhir           - Submit FHIR bundle for transmission
        POST /fhir/Bundle    - Submit FHIR bundle (explicit)
        POST /fhir/Patient   - Submit patient resource
        GET  /health         - Health check endpoint
        GET  /stats          - Queue and transmission statistics
    """
    
    # Reference to parent receiver (set by EMRReceiver)
    receiver: Optional["EMRReceiver"] = None
    
    def log_message(self, format: str, *args) -> None:
        """Override to use our logger instead of stderr."""
        logger.debug(f"HTTP: {format % args}")
    
    def do_GET(self) -> None:
        """Handle GET requests."""
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        
        if path == "/health":
            self._handle_health()
        elif path == "/stats":
            self._handle_stats()
        else:
            self._send_error(404, "Not Found")
    
    def do_POST(self) -> None:
        """Handle POST requests."""
        if not self.receiver:
            self._send_error(500, "Receiver not initialized")
            return
        
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        base_path = self.receiver.config.server.path.rstrip("/")
        
        # Check if path matches our FHIR endpoint
        if path == base_path or path.startswith(f"{base_path}/"):
            self._handle_fhir_submission()
        else:
            self._send_error(404, "Not Found")
    
    def _handle_health(self) -> None:
        """Handle health check request."""
        response = {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "queue_size": self.receiver.queue.size() if self.receiver else 0,
        }
        self._send_json(200, response)
    
    def _handle_stats(self) -> None:
        """Handle statistics request."""
        if not self.receiver:
            self._send_error(500, "Receiver not initialized")
            return
        
        stats = {
            "queue": self.receiver.queue.get_stats(),
            "received": self.receiver.get_stats(),
            "timestamp": datetime.utcnow().isoformat(),
        }
        self._send_json(200, stats)
    
    def _handle_fhir_submission(self) -> None:
        """Handle FHIR bundle submission."""
        # Get content length
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            self._send_error(400, "Empty request body")
            return
        
        if content_length > 10 * 1024 * 1024:  # 10 MB limit
            self._send_error(413, "Request too large (max 10MB)")
            return
        
        # Read body
        try:
            body = self.rfile.read(content_length)
        except Exception as e:
            logger.error(f"Failed to read request body: {e}")
            self._send_error(400, f"Failed to read body: {e}")
            return
        
        # Extract destination from headers or query params
        destination = (
            self.headers.get("X-Destination") or
            self.headers.get("X-Target-Facility") or
            parse_qs(urlparse(self.path).query).get("destination", [None])[0]
        )
        
        if not destination:
            self._send_error(400, "Missing destination (X-Destination header or ?destination= param)")
            return
        
        # Extract optional metadata from headers
        metadata = {
            "source_ip": self.client_address[0],
            "content_type": self.headers.get("Content-Type", "application/json"),
            "user_agent": self.headers.get("User-Agent", "unknown"),
        }
        
        # Optional priority header
        priority_str = self.headers.get("X-Priority", "0")
        try:
            priority = int(priority_str)
        except ValueError:
            priority = 0
        
        # Process the submission
        try:
            result = self.receiver.process_submission(
                payload=body,
                destination=destination,
                priority=priority,
                metadata=metadata,
            )
            
            response = {
                "status": "queued",
                "message_id": result["message_id"],
                "queue_id": result["queue_id"],
                "timestamp": datetime.utcnow().isoformat(),
            }
            
            self._send_json(202, response)  # 202 Accepted
            
        except ValueError as e:
            self._send_error(400, str(e))
        except Exception as e:
            logger.error(f"Failed to process submission: {e}")
            self._send_error(500, f"Processing error: {e}")
    
    def _send_json(self, status: int, data: Dict[str, Any]) -> None:
        """Send JSON response."""
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    
    def _send_error(self, status: int, message: str) -> None:
        """Send error response."""
        self._send_json(status, {"error": message, "status": status})


class EMRReceiver:
    """HTTP server for receiving FHIR data from local EMR.
    
    This class manages the HTTP server lifecycle and processes
    incoming FHIR submissions.
    
    Thread Safety:
        The HTTP server runs in a separate daemon thread. The queue
        and wire format operations are thread-safe.
    
    Example:
        >>> receiver = EMRReceiver(config, queue, wire_format)
        >>> receiver.start()
        >>> 
        >>> # Server is running, accepting requests...
        >>> 
        >>> receiver.stop()
    """
    
    # Map FHIR resource types to message types
    RESOURCE_TYPE_MAP = {
        "Bundle": MessageType.BUNDLE,
        "Patient": MessageType.PATIENT,
        "Observation": MessageType.OBSERVATION,
        "Encounter": MessageType.ENCOUNTER,
        "ServiceRequest": MessageType.REFERRAL,
        "ReferralRequest": MessageType.REFERRAL,
    }
    
    def __init__(
        self,
        config: Config,
        queue: PersistentQueue,
        wire_format: WireFormat,
        on_receive: Optional[Callable[[ReceivedMessage], None]] = None,
    ):
        """Initialize the EMR receiver.
        
        Args:
            config: Application configuration
            queue: Persistent queue for outgoing messages
            wire_format: Wire format encoder
            on_receive: Optional callback when message is received
        """
        self.config = config
        self.queue = queue
        self.wire_format = wire_format
        self.on_receive = on_receive
        
        self.host = config.server.host
        self.port = config.server.port
        
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        
        # Statistics
        self._stats_lock = threading.Lock()
        self._stats = {
            "received": 0,
            "queued": 0,
            "errors": 0,
            "total_bytes": 0,
        }
        
        logger.info(
            f"Initialized EMR receiver: {self.host}:{self.port}{config.server.path}"
        )
    
    def start(self) -> None:
        """Start the HTTP server in a background thread."""
        if self._running:
            logger.warning("Receiver already running")
            return
        
        # Configure request handler with reference to self
        EMRRequestHandler.receiver = self
        
        # Create server
        self._server = HTTPServer(
            (self.host, self.port),
            EMRRequestHandler
        )
        
        # Start server thread
        self._thread = threading.Thread(
            target=self._run_server,
            name="EMRReceiver",
            daemon=True,
        )
        self._running = True
        self._thread.start()
        
        logger.info(f"EMR receiver started on {self.host}:{self.port}")
    
    def _run_server(self) -> None:
        """Server thread main loop."""
        try:
            while self._running:
                self._server.handle_request()
        except Exception as e:
            logger.error(f"Server error: {e}")
        finally:
            logger.debug("Server thread exiting")
    
    def stop(self, timeout: float = 5.0) -> None:
        """Stop the HTTP server.
        
        Args:
            timeout: Seconds to wait for graceful shutdown
        """
        if not self._running:
            return
        
        logger.info("Stopping EMR receiver...")
        self._running = False
        
        if self._server:
            self._server.shutdown()
        
        if self._thread:
            self._thread.join(timeout=timeout)
        
        logger.info("EMR receiver stopped")
    
    def process_submission(
        self,
        payload: bytes,
        destination: str,
        priority: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Process an incoming FHIR submission.
        
        Args:
            payload: Raw FHIR JSON bytes
            destination: Target facility ID
            priority: Message priority
            metadata: Optional metadata
        
        Returns:
            Dictionary with message_id and queue_id
        
        Raises:
            ValueError: If payload is invalid
        """
        # Parse and validate FHIR JSON
        try:
            fhir_data = json.loads(payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            with self._stats_lock:
                self._stats["errors"] += 1
            raise ValueError(f"Invalid JSON: {e}")
        
        # Get resource type
        resource_type = fhir_data.get("resourceType", "Bundle")
        
        # Determine message type
        message_type = self.RESOURCE_TYPE_MAP.get(
            resource_type,
            MessageType.BUNDLE
        )
        
        # Generate message ID
        message_id = str(uuid.uuid4())
        
        # Update statistics
        with self._stats_lock:
            self._stats["received"] += 1
            self._stats["total_bytes"] += len(payload)
        
        # Create received message object
        received = ReceivedMessage(
            message_id=message_id,
            resource_type=resource_type,
            destination=destination,
            payload=payload,
            metadata=metadata or {},
        )
        
        # Call callback if set
        if self.on_receive:
            try:
                self.on_receive(received)
            except Exception as e:
                logger.error(f"on_receive callback failed: {e}")
        
        # Encode with wire format
        encoded = self.wire_format.encode(
            payload=payload,
            source=self.config.facility.id,
            destination=destination,
            message_type=message_type,
            message_id=message_id,
        )
        
        # Queue for transmission
        queue_id = self.queue.put(
            message_id=message_id,
            destination=destination,
            payload=encoded,
            priority=priority,
            metadata={
                "resource_type": resource_type,
                "original_size": len(payload),
                "encoded_size": len(encoded),
                **(metadata or {}),
            },
        )
        
        with self._stats_lock:
            self._stats["queued"] += 1
        
        logger.info(
            f"Queued message: id={message_id[:8]}..., "
            f"type={resource_type}, dest={destination}, "
            f"size={len(payload)}->{len(encoded)} bytes"
        )
        
        return {
            "message_id": message_id,
            "queue_id": queue_id,
        }
    
    def get_stats(self) -> Dict[str, Any]:
        """Get receiver statistics.
        
        Returns:
            Dictionary with receiver statistics
        """
        with self._stats_lock:
            stats = dict(self._stats)
        
        stats["running"] = self._running
        stats["endpoint"] = f"http://{self.host}:{self.port}{self.config.server.path}"
        
        return stats
    
    def reset_stats(self) -> None:
        """Reset receiver statistics."""
        with self._stats_lock:
            self._stats = {
                "received": 0,
                "queued": 0,
                "errors": 0,
                "total_bytes": 0,
            }
    
    @property
    def is_running(self) -> bool:
        """Check if the receiver is running."""
        return self._running
    
    def __enter__(self):
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        return False
