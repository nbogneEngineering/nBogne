"""
Logging configuration for nBogne Adapter.

This module provides a centralized logging setup with:
    - Console and file output
    - Log rotation
    - Structured formatting
    - Level configuration

Example:
    >>> from nbogne.logging_config import setup_logging
    >>> from nbogne.config import Config
    >>> 
    >>> config = Config.from_file("config/default.yaml")
    >>> setup_logging(config.logging)
    >>> 
    >>> # Now all modules use configured logging
    >>> import logging
    >>> logger = logging.getLogger("nbogne")
    >>> logger.info("Adapter starting...")
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from nbogne.config import LoggingConfig


def setup_logging(config: LoggingConfig) -> logging.Logger:
    """Configure logging for the application.
    
    This function sets up logging with:
        - Console handler (always enabled)
        - File handler with rotation (if configured)
        - Consistent formatting across all loggers
    
    Args:
        config: Logging configuration
    
    Returns:
        Root logger for the nbogne package
    """
    # Get the root logger for nbogne package
    logger = logging.getLogger("nbogne")
    logger.setLevel(getattr(logging, config.level))
    
    # Clear existing handlers
    logger.handlers.clear()
    
    # Create formatter
    formatter = logging.Formatter(config.format)
    
    # Console handler (always enabled)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, config.level))
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # File handler (if configured)
    if config.file:
        # Ensure directory exists
        log_path = Path(config.file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        file_handler = RotatingFileHandler(
            config.file,
            maxBytes=config.max_bytes,
            backupCount=config.backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(getattr(logging, config.level))
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    # Don't propagate to root logger
    logger.propagate = False
    
    # Also configure related libraries
    for lib_name in ["urllib3", "requests"]:
        lib_logger = logging.getLogger(lib_name)
        lib_logger.setLevel(logging.WARNING)
    
    logger.debug(f"Logging configured: level={config.level}, file={config.file}")
    
    return logger


def get_logger(name: str) -> logging.Logger:
    """Get a logger for a specific module.
    
    Args:
        name: Module name (will be prefixed with 'nbogne.')
    
    Returns:
        Logger instance
    """
    if not name.startswith("nbogne"):
        name = f"nbogne.{name}"
    return logging.getLogger(name)


class LogContext:
    """Context manager for adding context to log messages.
    
    Example:
        >>> with LogContext(message_id="abc123", facility="FAC-01"):
        ...     logger.info("Processing message")
        ...     # Logs: "Processing message | context: message_id=abc123, facility=FAC-01"
    """
    
    _current: Optional["LogContext"] = None
    
    def __init__(self, **kwargs):
        """Initialize log context with key-value pairs."""
        self.context = kwargs
        self._previous: Optional["LogContext"] = None
    
    def __enter__(self):
        self._previous = LogContext._current
        LogContext._current = self
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        LogContext._current = self._previous
        return False
    
    @classmethod
    def get_context(cls) -> dict:
        """Get the current context dictionary."""
        if cls._current is None:
            return {}
        return cls._current.context
    
    @classmethod
    def format_context(cls) -> str:
        """Format context for log messages."""
        ctx = cls.get_context()
        if not ctx:
            return ""
        pairs = [f"{k}={v}" for k, v in ctx.items()]
        return f" | context: {', '.join(pairs)}"


class ContextualFormatter(logging.Formatter):
    """Log formatter that includes context from LogContext.
    
    Example:
        >>> formatter = ContextualFormatter("%(asctime)s | %(message)s%(context)s")
    """
    
    def format(self, record: logging.LogRecord) -> str:
        # Add context to record
        record.context = LogContext.format_context()
        return super().format(record)
