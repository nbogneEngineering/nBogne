"""
Custom exceptions for the nBogne Adapter.

This module defines a hierarchy of exceptions for handling various error conditions
that may occur during health data transmission over GPRS networks.

Exception Hierarchy:
    NBogneError (base)
    ├── ConfigurationError
    ├── WireFormatError
    │   ├── HeaderParseError
    │   ├── PayloadError
    │   └── ChecksumError
    ├── QueueError
    │   ├── QueueFullError
    │   └── QueueCorruptedError
    ├── TransmissionError
    │   ├── ConnectionError
    │   ├── TimeoutError
    │   └── RetryExhaustedError
    └── ModemError
        ├── ModemNotReadyError
        ├── NetworkRegistrationError
        └── ATCommandError
"""

from typing import Optional, Any


class NBogneError(Exception):
    """Base exception for all nBogne-related errors.
    
    Attributes:
        message: Human-readable error description
        details: Optional dictionary with additional context
        recoverable: Whether the operation can be retried
    """
    
    def __init__(
        self, 
        message: str, 
        details: Optional[dict[str, Any]] = None,
        recoverable: bool = False
    ):
        self.message = message
        self.details = details or {}
        self.recoverable = recoverable
        super().__init__(self.message)
    
    def __str__(self) -> str:
        if self.details:
            return f"{self.message} | Details: {self.details}"
        return self.message
    
    def to_dict(self) -> dict[str, Any]:
        """Convert exception to dictionary for logging/serialization."""
        return {
            "error_type": self.__class__.__name__,
            "message": self.message,
            "details": self.details,
            "recoverable": self.recoverable,
        }


# =============================================================================
# Configuration Errors
# =============================================================================

class ConfigurationError(NBogneError):
    """Raised when configuration is invalid or missing required fields."""
    
    def __init__(self, message: str, field: Optional[str] = None):
        details = {"field": field} if field else {}
        super().__init__(message, details, recoverable=False)


# =============================================================================
# Wire Format Errors
# =============================================================================

class WireFormatError(NBogneError):
    """Base class for wire format related errors."""
    pass


class HeaderParseError(WireFormatError):
    """Raised when message header cannot be parsed."""
    
    def __init__(self, message: str, raw_bytes: Optional[bytes] = None):
        details = {}
        if raw_bytes:
            details["raw_bytes_hex"] = raw_bytes[:48].hex() if len(raw_bytes) >= 48 else raw_bytes.hex()
            details["raw_length"] = len(raw_bytes)
        super().__init__(message, details, recoverable=False)


class PayloadError(WireFormatError):
    """Raised when payload encoding/decoding fails."""
    
    def __init__(self, message: str, operation: str = "unknown"):
        super().__init__(message, {"operation": operation}, recoverable=False)


class ChecksumError(WireFormatError):
    """Raised when message checksum validation fails."""
    
    def __init__(self, expected: str, actual: str):
        message = f"Checksum mismatch: expected {expected}, got {actual}"
        super().__init__(message, {"expected": expected, "actual": actual}, recoverable=False)


# =============================================================================
# Queue Errors
# =============================================================================

class QueueError(NBogneError):
    """Base class for queue-related errors."""
    pass


class QueueFullError(QueueError):
    """Raised when the queue has reached its maximum capacity."""
    
    def __init__(self, max_size: int, current_size: int):
        message = f"Queue is full: {current_size}/{max_size} items"
        super().__init__(
            message, 
            {"max_size": max_size, "current_size": current_size},
            recoverable=True  # Can retry after items are processed
        )


class QueueCorruptedError(QueueError):
    """Raised when the queue database is corrupted."""
    
    def __init__(self, message: str, db_path: Optional[str] = None):
        details = {"db_path": db_path} if db_path else {}
        super().__init__(message, details, recoverable=False)


# =============================================================================
# Transmission Errors
# =============================================================================

class TransmissionError(NBogneError):
    """Base class for transmission-related errors."""
    pass


class ConnectionError(TransmissionError):
    """Raised when connection to the remote server fails."""
    
    def __init__(self, message: str, endpoint: Optional[str] = None):
        details = {"endpoint": endpoint} if endpoint else {}
        super().__init__(message, details, recoverable=True)


class TimeoutError(TransmissionError):
    """Raised when a transmission times out."""
    
    def __init__(
        self, 
        message: str, 
        timeout_seconds: float,
        operation: str = "unknown"
    ):
        super().__init__(
            message,
            {"timeout_seconds": timeout_seconds, "operation": operation},
            recoverable=True
        )


class RetryExhaustedError(TransmissionError):
    """Raised when all retry attempts have been exhausted."""
    
    def __init__(
        self, 
        message: str, 
        attempts: int,
        last_error: Optional[str] = None
    ):
        super().__init__(
            message,
            {"attempts": attempts, "last_error": last_error},
            recoverable=False  # No more automatic retries
        )


# =============================================================================
# Modem Errors
# =============================================================================

class ModemError(NBogneError):
    """Base class for modem-related errors."""
    pass


class ModemNotReadyError(ModemError):
    """Raised when the modem is not ready for communication."""
    
    def __init__(self, message: str = "Modem not ready"):
        super().__init__(message, recoverable=True)


class NetworkRegistrationError(ModemError):
    """Raised when the modem fails to register on the network."""
    
    def __init__(self, message: str, registration_status: Optional[int] = None):
        details = {}
        if registration_status is not None:
            details["registration_status"] = registration_status
            details["status_meaning"] = {
                0: "Not registered, not searching",
                1: "Registered, home network",
                2: "Not registered, searching",
                3: "Registration denied",
                4: "Unknown",
                5: "Registered, roaming",
            }.get(registration_status, "Unknown status code")
        super().__init__(message, details, recoverable=True)


class ATCommandError(ModemError):
    """Raised when an AT command fails."""
    
    def __init__(
        self, 
        command: str, 
        response: str,
        expected: Optional[str] = None
    ):
        message = f"AT command failed: {command}"
        super().__init__(
            message,
            {"command": command, "response": response, "expected": expected},
            recoverable=True
        )
