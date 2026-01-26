"""
GPRS Transmitter with exponential backoff and retry logic.

This module handles reliable transmission of messages over GPRS networks,
implementing the patterns documented by AWS Architecture Blog and proven
in production systems like M-Pesa.

Key Features:
    - Exponential backoff with full jitter (AWS recommended)
    - Configurable timeouts optimized for GPRS (RFC 3481)
    - Idempotency support for safe retries
    - Connection pooling and keep-alive
    - Comprehensive error handling and logging

Example:
    >>> from nbogne.transmitter import Transmitter
    >>> from nbogne.config import Config
    >>> 
    >>> config = Config.from_file("config/default.yaml")
    >>> transmitter = Transmitter(config)
    >>> 
    >>> result = transmitter.send(encoded_message)
    >>> if result.success:
    ...     print(f"Transmitted in {result.duration_ms}ms")
    ... else:
    ...     print(f"Failed: {result.error}")
"""

import time
import random
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any, Callable
from enum import Enum

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from nbogne.config import Config, TransmissionConfig
from nbogne.exceptions import (
    TransmissionError,
    ConnectionError,
    TimeoutError,
    RetryExhaustedError,
)

logger = logging.getLogger(__name__)


class TransmissionStatus(Enum):
    """Status of a transmission attempt."""
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CONNECTION_ERROR = "connection_error"
    SERVER_ERROR = "server_error"
    RETRY_EXHAUSTED = "retry_exhausted"


@dataclass
class TransmissionResult:
    """Result of a transmission attempt.
    
    Attributes:
        success: Whether transmission succeeded
        status: Detailed status code
        status_code: HTTP status code (if applicable)
        response_body: Response body from server
        duration_ms: Total transmission time in milliseconds
        attempts: Number of attempts made
        error: Error message (if failed)
        message_id: Message ID that was transmitted
        timestamp: When transmission completed
    """
    success: bool
    status: TransmissionStatus
    status_code: Optional[int] = None
    response_body: Optional[bytes] = None
    duration_ms: float = 0.0
    attempts: int = 1
    error: Optional[str] = None
    message_id: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary for logging/serialization."""
        return {
            "success": self.success,
            "status": self.status.value,
            "status_code": self.status_code,
            "duration_ms": self.duration_ms,
            "attempts": self.attempts,
            "error": self.error,
            "message_id": self.message_id,
            "timestamp": self.timestamp.isoformat(),
        }


class Transmitter:
    """GPRS message transmitter with retry logic.
    
    This class handles HTTP POST transmission over GPRS with:
        - Exponential backoff with full jitter
        - Configurable timeouts for slow networks
        - Connection pooling for efficiency
        - Idempotency key support
    
    Thread Safety:
        This class is thread-safe. Multiple threads can call send()
        concurrently. The underlying requests Session handles connection
        pooling automatically.
    
    Example:
        >>> transmitter = Transmitter(config)
        >>> 
        >>> # Simple send
        >>> result = transmitter.send(payload)
        >>> 
        >>> # Send with idempotency key
        >>> result = transmitter.send(payload, idempotency_key="msg-123")
        >>> 
        >>> # Send with custom headers
        >>> result = transmitter.send(payload, headers={"X-Facility": "FAC-01"})
    """
    
    # HTTP headers for GPRS optimization
    DEFAULT_HEADERS = {
        "Content-Type": "application/octet-stream",
        "Accept": "application/json",
        "Connection": "keep-alive",
    }
    
    def __init__(
        self,
        config: Config,
        on_success: Optional[Callable[[TransmissionResult], None]] = None,
        on_failure: Optional[Callable[[TransmissionResult], None]] = None,
    ):
        """Initialize the transmitter.
        
        Args:
            config: Application configuration
            on_success: Optional callback on successful transmission
            on_failure: Optional callback on failed transmission
        """
        self.config = config
        self.transmission_config = config.transmission
        self.endpoint = config.mediator.endpoint
        self.api_key = config.mediator.api_key
        
        self.on_success = on_success
        self.on_failure = on_failure
        
        # Thread-local storage for sessions
        self._local = threading.local()
        
        # Statistics
        self._stats_lock = threading.Lock()
        self._stats = {
            "total_attempts": 0,
            "successful": 0,
            "failed": 0,
            "total_bytes_sent": 0,
            "total_duration_ms": 0,
        }
        
        logger.info(f"Initialized transmitter: endpoint={self.endpoint}")
    
    def _get_session(self) -> requests.Session:
        """Get a thread-local requests Session with retry configuration."""
        if not hasattr(self._local, "session") or self._local.session is None:
            session = requests.Session()
            
            # Configure retry strategy for connection-level retries
            # (separate from our application-level retry logic)
            retry_strategy = Retry(
                total=2,  # Only retry connection errors
                backoff_factor=0.5,
                status_forcelist=[502, 503, 504],  # Retry these status codes
                allowed_methods=["POST"],
                raise_on_status=False,
            )
            
            adapter = HTTPAdapter(
                max_retries=retry_strategy,
                pool_connections=1,  # Single connection for GPRS
                pool_maxsize=1,
            )
            
            session.mount("http://", adapter)
            session.mount("https://", adapter)
            
            # Set default headers
            session.headers.update(self.DEFAULT_HEADERS)
            
            # Add API key if configured
            if self.api_key:
                session.headers["Authorization"] = f"Bearer {self.api_key}"
            
            self._local.session = session
            
        return self._local.session
    
    def send(
        self,
        payload: bytes,
        message_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout_override: Optional[tuple] = None,
    ) -> TransmissionResult:
        """Send a message to the mediator endpoint.
        
        This method attempts to send the payload with automatic retries
        on failure, using exponential backoff with full jitter.
        
        Args:
            payload: Encoded message bytes to send
            message_id: Optional message ID for logging
            idempotency_key: Optional key for safe retries
            headers: Optional additional headers
            timeout_override: Optional (connect, read) timeout tuple
        
        Returns:
            TransmissionResult with outcome details
        """
        start_time = time.time()
        attempts = 0
        last_error = None
        
        # Prepare headers
        request_headers = dict(headers) if headers else {}
        if idempotency_key:
            request_headers["Idempotency-Key"] = idempotency_key
        if message_id:
            request_headers["X-Message-ID"] = message_id
        
        # Get timeouts
        timeout = timeout_override or (
            self.transmission_config.timeout_connect,
            self.transmission_config.timeout_read,
        )
        
        while attempts < self.transmission_config.max_retries:
            attempts += 1
            
            try:
                result = self._attempt_send(
                    payload=payload,
                    headers=request_headers,
                    timeout=timeout,
                    attempt=attempts,
                )
                
                if result.success:
                    # Update statistics
                    with self._stats_lock:
                        self._stats["total_attempts"] += attempts
                        self._stats["successful"] += 1
                        self._stats["total_bytes_sent"] += len(payload)
                        self._stats["total_duration_ms"] += result.duration_ms
                    
                    result.attempts = attempts
                    result.message_id = message_id
                    
                    if self.on_success:
                        try:
                            self.on_success(result)
                        except Exception as e:
                            logger.error(f"on_success callback failed: {e}")
                    
                    return result
                
                last_error = result.error
                
            except Exception as e:
                last_error = str(e)
                logger.warning(f"Attempt {attempts} failed: {e}")
            
            # Calculate backoff delay
            if attempts < self.transmission_config.max_retries:
                delay = self._calculate_backoff(attempts)
                logger.debug(f"Waiting {delay:.2f}s before retry")
                time.sleep(delay)
        
        # All retries exhausted
        duration_ms = (time.time() - start_time) * 1000
        
        result = TransmissionResult(
            success=False,
            status=TransmissionStatus.RETRY_EXHAUSTED,
            duration_ms=duration_ms,
            attempts=attempts,
            error=f"All {attempts} attempts failed. Last error: {last_error}",
            message_id=message_id,
        )
        
        # Update statistics
        with self._stats_lock:
            self._stats["total_attempts"] += attempts
            self._stats["failed"] += 1
            self._stats["total_duration_ms"] += duration_ms
        
        if self.on_failure:
            try:
                self.on_failure(result)
            except Exception as e:
                logger.error(f"on_failure callback failed: {e}")
        
        logger.error(
            f"Transmission failed after {attempts} attempts: {last_error}"
        )
        
        return result
    
    def _attempt_send(
        self,
        payload: bytes,
        headers: Dict[str, str],
        timeout: tuple,
        attempt: int,
    ) -> TransmissionResult:
        """Make a single transmission attempt.
        
        Args:
            payload: Message bytes to send
            headers: Request headers
            timeout: (connect_timeout, read_timeout) tuple
            attempt: Current attempt number
        
        Returns:
            TransmissionResult with outcome
        """
        start_time = time.time()
        
        logger.debug(
            f"Attempt {attempt}: sending {len(payload)} bytes to {self.endpoint}"
        )
        
        try:
            session = self._get_session()
            
            response = session.post(
                self.endpoint,
                data=payload,
                headers=headers,
                timeout=timeout,
            )
            
            duration_ms = (time.time() - start_time) * 1000
            
            # Check response status
            if response.status_code == 200:
                logger.info(
                    f"Transmission successful: {len(payload)} bytes in {duration_ms:.0f}ms"
                )
                return TransmissionResult(
                    success=True,
                    status=TransmissionStatus.SUCCESS,
                    status_code=response.status_code,
                    response_body=response.content,
                    duration_ms=duration_ms,
                )
            
            elif response.status_code in (408, 429, 500, 502, 503, 504):
                # Retryable errors
                logger.warning(
                    f"Server returned {response.status_code}, will retry"
                )
                return TransmissionResult(
                    success=False,
                    status=TransmissionStatus.SERVER_ERROR,
                    status_code=response.status_code,
                    response_body=response.content,
                    duration_ms=duration_ms,
                    error=f"HTTP {response.status_code}",
                )
            
            else:
                # Non-retryable errors (4xx except 408, 429)
                logger.error(
                    f"Server returned {response.status_code}: {response.text[:200]}"
                )
                return TransmissionResult(
                    success=False,
                    status=TransmissionStatus.FAILED,
                    status_code=response.status_code,
                    response_body=response.content,
                    duration_ms=duration_ms,
                    error=f"HTTP {response.status_code}: {response.text[:100]}",
                )
        
        except requests.exceptions.ConnectTimeout:
            duration_ms = (time.time() - start_time) * 1000
            logger.warning(f"Connection timeout after {duration_ms:.0f}ms")
            return TransmissionResult(
                success=False,
                status=TransmissionStatus.TIMEOUT,
                duration_ms=duration_ms,
                error="Connection timeout",
            )
        
        except requests.exceptions.ReadTimeout:
            duration_ms = (time.time() - start_time) * 1000
            logger.warning(f"Read timeout after {duration_ms:.0f}ms")
            return TransmissionResult(
                success=False,
                status=TransmissionStatus.TIMEOUT,
                duration_ms=duration_ms,
                error="Read timeout",
            )
        
        except requests.exceptions.ConnectionError as e:
            duration_ms = (time.time() - start_time) * 1000
            logger.warning(f"Connection error: {e}")
            return TransmissionResult(
                success=False,
                status=TransmissionStatus.CONNECTION_ERROR,
                duration_ms=duration_ms,
                error=f"Connection error: {e}",
            )
        
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            logger.error(f"Unexpected error: {e}")
            return TransmissionResult(
                success=False,
                status=TransmissionStatus.FAILED,
                duration_ms=duration_ms,
                error=f"Unexpected error: {e}",
            )
    
    def _calculate_backoff(self, attempt: int) -> float:
        """Calculate backoff delay with full jitter.
        
        Uses the "Full Jitter" algorithm recommended by AWS:
        sleep = random_between(0, min(cap, base * 2^attempt))
        
        Args:
            attempt: Current attempt number (1-based)
        
        Returns:
            Delay in seconds
        """
        base = self.transmission_config.base_delay
        cap = self.transmission_config.max_delay
        
        if self.transmission_config.jitter:
            # Full jitter (AWS recommended)
            exp_backoff = min(cap, base * (2 ** (attempt - 1)))
            return random.uniform(0, exp_backoff)
        else:
            # Pure exponential backoff
            return min(cap, base * (2 ** (attempt - 1)))
    
    def health_check(self) -> bool:
        """Perform a health check on the mediator endpoint.
        
        Sends a lightweight request to verify connectivity.
        
        Returns:
            True if endpoint is reachable, False otherwise
        """
        try:
            session = self._get_session()
            response = session.get(
                self.endpoint.rstrip("/") + "/health",
                timeout=(10, 10),
            )
            return response.status_code in (200, 204, 404)  # 404 is OK if no health endpoint
        except Exception as e:
            logger.warning(f"Health check failed: {e}")
            return False
    
    def get_stats(self) -> Dict[str, Any]:
        """Get transmission statistics.
        
        Returns:
            Dictionary with transmission statistics
        """
        with self._stats_lock:
            stats = dict(self._stats)
        
        # Calculate derived statistics
        if stats["successful"] + stats["failed"] > 0:
            stats["success_rate"] = (
                stats["successful"] / (stats["successful"] + stats["failed"])
            ) * 100
        else:
            stats["success_rate"] = 0
        
        if stats["total_attempts"] > 0:
            stats["avg_duration_ms"] = (
                stats["total_duration_ms"] / stats["total_attempts"]
            )
        else:
            stats["avg_duration_ms"] = 0
        
        stats["endpoint"] = self.endpoint
        
        return stats
    
    def reset_stats(self) -> None:
        """Reset transmission statistics."""
        with self._stats_lock:
            self._stats = {
                "total_attempts": 0,
                "successful": 0,
                "failed": 0,
                "total_bytes_sent": 0,
                "total_duration_ms": 0,
            }
    
    def close(self) -> None:
        """Close the transmitter and release resources."""
        if hasattr(self._local, "session") and self._local.session:
            self._local.session.close()
            self._local.session = None
            logger.debug("Closed transmitter session")
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
