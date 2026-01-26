"""
Configuration management for nBogne Adapter.

This module provides a type-safe, validated configuration system supporting:
- YAML configuration files
- Environment variable overrides
- Default values with sensible GPRS-optimized settings
- Validation of all configuration parameters

Configuration Hierarchy (highest to lowest priority):
    1. Environment variables (NBOGNE_*)
    2. Configuration file (config.yaml)
    3. Default values

Example:
    >>> config = Config.from_file("config/default.yaml")
    >>> config.mediator.endpoint
    'https://mediator.example.com/gsm/inbound'
    >>> config.transmission.timeout_connect
    30.0
"""

import os
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Any
import yaml

from nbogne.exceptions import ConfigurationError

logger = logging.getLogger(__name__)


@dataclass
class FacilityConfig:
    """Configuration for the local facility.
    
    Attributes:
        id: Unique facility identifier (max 8 characters for wire format)
        name: Human-readable facility name
        phone_number: SIM card phone number for SMS fallback
    """
    id: str
    name: str
    phone_number: str
    
    def __post_init__(self):
        if len(self.id) > 8:
            raise ConfigurationError(
                f"Facility ID must be 8 characters or less, got {len(self.id)}",
                field="facility.id"
            )
        if not self.id:
            raise ConfigurationError("Facility ID cannot be empty", field="facility.id")


@dataclass
class MediatorConfig:
    """Configuration for the central nBogne Mediator.
    
    Attributes:
        endpoint: HTTP endpoint URL for GPRS transmission
        sms_number: Phone number for SMS fallback
        api_key: Optional API key for authentication
    """
    endpoint: str
    sms_number: str
    api_key: Optional[str] = None
    
    def __post_init__(self):
        if not self.endpoint.startswith(("http://", "https://")):
            raise ConfigurationError(
                "Mediator endpoint must be a valid HTTP(S) URL",
                field="mediator.endpoint"
            )


@dataclass
class EMRConfig:
    """Configuration for the local EMR system.
    
    Attributes:
        type: EMR type (openmrs, openemr, dhis2, custom)
        base_url: Base URL for EMR API
        fhir_endpoint: FHIR API endpoint path
        auth_token: Authentication token for EMR API
        polling_interval: Seconds between polling for new data (0 = push mode)
    """
    type: str
    base_url: str
    fhir_endpoint: str = "/fhir"
    auth_token: Optional[str] = None
    polling_interval: int = 0
    
    SUPPORTED_TYPES = ("openmrs", "openemr", "dhis2", "custom")
    
    def __post_init__(self):
        if self.type not in self.SUPPORTED_TYPES:
            raise ConfigurationError(
                f"Unsupported EMR type: {self.type}. Supported: {self.SUPPORTED_TYPES}",
                field="emr.type"
            )


@dataclass
class TransmissionConfig:
    """Configuration for GPRS transmission parameters.
    
    All timeouts and delays are optimized for GPRS networks based on RFC 3481
    and documented field measurements.
    
    Attributes:
        timeout_connect: TCP connection timeout in seconds (GPRS: 30s recommended)
        timeout_read: HTTP read timeout in seconds (GPRS: 120s recommended)
        max_retries: Maximum number of retry attempts before fallback
        base_delay: Base delay for exponential backoff in seconds
        max_delay: Maximum delay cap for backoff in seconds
        jitter: Enable full jitter on retry delays (recommended: True)
        keepalive_interval: HTTP keep-alive interval in seconds (GPRS: 60s max)
    """
    timeout_connect: float = 30.0
    timeout_read: float = 120.0
    max_retries: int = 5
    base_delay: float = 3.0
    max_delay: float = 300.0
    jitter: bool = True
    keepalive_interval: float = 55.0
    
    def __post_init__(self):
        if self.timeout_connect < 10:
            logger.warning(
                f"Connect timeout {self.timeout_connect}s may be too low for GPRS. "
                "Recommended: 30s minimum"
            )
        if self.base_delay < 1:
            raise ConfigurationError(
                "Base delay must be at least 1 second for GPRS",
                field="transmission.base_delay"
            )


@dataclass
class QueueConfig:
    """Configuration for the persistent message queue.
    
    Attributes:
        db_path: Path to SQLite database file
        max_size: Maximum number of messages in queue (0 = unlimited)
        batch_size: Number of messages to process per drain cycle
        drain_interval: Seconds between queue drain attempts
        retention_days: Days to keep acknowledged messages (for audit)
    """
    db_path: str = "data/outbox.db"
    max_size: int = 10000
    batch_size: int = 10
    drain_interval: float = 5.0
    retention_days: int = 30
    
    def __post_init__(self):
        # Ensure parent directory exists
        db_path = Path(self.db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)


@dataclass
class ModemConfig:
    """Configuration for the GSM modem.
    
    Attributes:
        port: Serial port for modem (e.g., /dev/ttyUSB0)
        baudrate: Serial baudrate (typically 115200 for modern modems)
        apn: Access Point Name for GPRS connection
        apn_user: APN username (often empty)
        apn_password: APN password (often empty)
        pin: SIM PIN code (if required)
        model: Modem model hint (quectel, simcom, huawei, auto)
    """
    port: str = "/dev/ttyUSB0"
    baudrate: int = 115200
    apn: str = "internet"
    apn_user: str = ""
    apn_password: str = ""
    pin: Optional[str] = None
    model: str = "auto"
    
    SUPPORTED_MODELS = ("quectel", "simcom", "huawei", "auto")
    
    def __post_init__(self):
        if self.model not in self.SUPPORTED_MODELS:
            raise ConfigurationError(
                f"Unsupported modem model: {self.model}. Supported: {self.SUPPORTED_MODELS}",
                field="modem.model"
            )


@dataclass
class ServerConfig:
    """Configuration for the local HTTP server (receives from EMR).
    
    Attributes:
        host: Bind address for HTTP server
        port: Port number for HTTP server
        path: URL path for FHIR endpoint
    """
    host: str = "0.0.0.0"
    port: int = 8080
    path: str = "/fhir"


@dataclass
class LoggingConfig:
    """Configuration for logging.
    
    Attributes:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        file: Log file path (None = stdout only)
        max_bytes: Maximum log file size before rotation
        backup_count: Number of backup files to keep
        format: Log message format string
    """
    level: str = "INFO"
    file: Optional[str] = "logs/nbogne.log"
    max_bytes: int = 10_485_760  # 10 MB
    backup_count: int = 5
    format: str = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    
    VALID_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
    
    def __post_init__(self):
        if self.level.upper() not in self.VALID_LEVELS:
            raise ConfigurationError(
                f"Invalid log level: {self.level}. Valid: {self.VALID_LEVELS}",
                field="logging.level"
            )
        self.level = self.level.upper()
        
        if self.file:
            log_path = Path(self.file)
            log_path.parent.mkdir(parents=True, exist_ok=True)


@dataclass
class Config:
    """Main configuration container for nBogne Adapter.
    
    This class aggregates all configuration sections and provides
    factory methods for loading from files and environment variables.
    
    Example:
        >>> # Load from file
        >>> config = Config.from_file("config/default.yaml")
        
        >>> # Load with environment overrides
        >>> config = Config.from_file("config/default.yaml", use_env=True)
        
        >>> # Access configuration
        >>> config.facility.id
        'FAC-001'
        >>> config.transmission.timeout_connect
        30.0
    """
    facility: FacilityConfig
    mediator: MediatorConfig
    emr: EMRConfig
    transmission: TransmissionConfig = field(default_factory=TransmissionConfig)
    queue: QueueConfig = field(default_factory=QueueConfig)
    modem: ModemConfig = field(default_factory=ModemConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        """Create Config from a dictionary.
        
        Args:
            data: Dictionary with configuration values
            
        Returns:
            Validated Config instance
            
        Raises:
            ConfigurationError: If required fields are missing or invalid
        """
        try:
            return cls(
                facility=FacilityConfig(**data.get("facility", {})),
                mediator=MediatorConfig(**data.get("mediator", {})),
                emr=EMRConfig(**data.get("emr", {})),
                transmission=TransmissionConfig(**data.get("transmission", {})),
                queue=QueueConfig(**data.get("queue", {})),
                modem=ModemConfig(**data.get("modem", {})),
                server=ServerConfig(**data.get("server", {})),
                logging=LoggingConfig(**data.get("logging", {})),
            )
        except TypeError as e:
            raise ConfigurationError(f"Missing required configuration: {e}")
    
    @classmethod
    def from_file(cls, path: str, use_env: bool = True) -> "Config":
        """Load configuration from a YAML file.
        
        Args:
            path: Path to YAML configuration file
            use_env: Whether to apply environment variable overrides
            
        Returns:
            Validated Config instance
            
        Raises:
            ConfigurationError: If file not found or invalid
        """
        config_path = Path(path)
        if not config_path.exists():
            raise ConfigurationError(f"Configuration file not found: {path}")
        
        try:
            with open(config_path) as f:
                data = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            raise ConfigurationError(f"Invalid YAML in configuration file: {e}")
        
        if use_env:
            data = cls._apply_env_overrides(data)
        
        return cls.from_dict(data)
    
    @staticmethod
    def _apply_env_overrides(data: dict[str, Any]) -> dict[str, Any]:
        """Apply environment variable overrides to configuration.
        
        Environment variables follow the pattern: NBOGNE_SECTION_KEY
        For example: NBOGNE_FACILITY_ID, NBOGNE_MEDIATOR_ENDPOINT
        
        Args:
            data: Configuration dictionary to override
            
        Returns:
            Configuration dictionary with environment overrides applied
        """
        env_mappings = {
            "NBOGNE_FACILITY_ID": ("facility", "id"),
            "NBOGNE_FACILITY_NAME": ("facility", "name"),
            "NBOGNE_FACILITY_PHONE": ("facility", "phone_number"),
            "NBOGNE_MEDIATOR_ENDPOINT": ("mediator", "endpoint"),
            "NBOGNE_MEDIATOR_SMS": ("mediator", "sms_number"),
            "NBOGNE_MEDIATOR_API_KEY": ("mediator", "api_key"),
            "NBOGNE_EMR_TYPE": ("emr", "type"),
            "NBOGNE_EMR_URL": ("emr", "base_url"),
            "NBOGNE_EMR_TOKEN": ("emr", "auth_token"),
            "NBOGNE_MODEM_PORT": ("modem", "port"),
            "NBOGNE_MODEM_APN": ("modem", "apn"),
            "NBOGNE_QUEUE_PATH": ("queue", "db_path"),
            "NBOGNE_LOG_LEVEL": ("logging", "level"),
        }
        
        for env_var, (section, key) in env_mappings.items():
            value = os.environ.get(env_var)
            if value is not None:
                if section not in data:
                    data[section] = {}
                data[section][key] = value
                logger.debug(f"Applied environment override: {env_var}")
        
        return data
    
    def to_dict(self) -> dict[str, Any]:
        """Export configuration to dictionary (excludes sensitive fields)."""
        return {
            "facility": {
                "id": self.facility.id,
                "name": self.facility.name,
                "phone_number": "***REDACTED***",
            },
            "mediator": {
                "endpoint": self.mediator.endpoint,
                "sms_number": "***REDACTED***",
            },
            "emr": {
                "type": self.emr.type,
                "base_url": self.emr.base_url,
                "fhir_endpoint": self.emr.fhir_endpoint,
            },
            "transmission": {
                "timeout_connect": self.transmission.timeout_connect,
                "timeout_read": self.transmission.timeout_read,
                "max_retries": self.transmission.max_retries,
                "base_delay": self.transmission.base_delay,
                "max_delay": self.transmission.max_delay,
            },
            "queue": {
                "db_path": self.queue.db_path,
                "max_size": self.queue.max_size,
                "batch_size": self.queue.batch_size,
            },
            "modem": {
                "port": self.modem.port,
                "model": self.modem.model,
            },
        }
