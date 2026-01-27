"""
Tests for the configuration module.

These tests verify:
    - Configuration loading from YAML
    - Environment variable overrides
    - Validation of required fields
    - Default values
"""

import pytest
import tempfile
import os
from pathlib import Path

from nbogne.config import (
    Config,
    FacilityConfig,
    MediatorConfig,
    EMRConfig,
    TransmissionConfig,
    QueueConfig,
    ModemConfig,
    ServerConfig,
    LoggingConfig,
)
from nbogne.exceptions import ConfigurationError


class TestFacilityConfig:
    """Test suite for FacilityConfig."""
    
    def test_valid_facility_config(self):
        """Test valid facility configuration."""
        config = FacilityConfig(
            id="FAC-001",
            name="Test Facility",
            phone_number="+1234567890",
        )
        
        assert config.id == "FAC-001"
        assert config.name == "Test Facility"
        assert config.phone_number == "+1234567890"
    
    def test_facility_id_max_length(self):
        """Test that facility ID must be 8 characters or less."""
        # Valid 8-character ID
        config = FacilityConfig(
            id="12345678",
            name="Test",
            phone_number="+1234567890",
        )
        assert len(config.id) == 8
        
        # Invalid 9-character ID
        with pytest.raises(ConfigurationError) as exc_info:
            FacilityConfig(
                id="123456789",
                name="Test",
                phone_number="+1234567890",
            )
        assert "8 characters" in str(exc_info.value)
    
    def test_facility_id_cannot_be_empty(self):
        """Test that facility ID cannot be empty."""
        with pytest.raises(ConfigurationError) as exc_info:
            FacilityConfig(
                id="",
                name="Test",
                phone_number="+1234567890",
            )
        assert "cannot be empty" in str(exc_info.value)


class TestMediatorConfig:
    """Test suite for MediatorConfig."""
    
    def test_valid_mediator_config(self):
        """Test valid mediator configuration."""
        config = MediatorConfig(
            endpoint="https://mediator.example.com/gsm/inbound",
            sms_number="+1234567890",
            api_key="secret-key",
        )
        
        assert config.endpoint == "https://mediator.example.com/gsm/inbound"
        assert config.sms_number == "+1234567890"
        assert config.api_key == "secret-key"
    
    def test_endpoint_must_be_http_url(self):
        """Test that endpoint must be an HTTP(S) URL."""
        # Valid HTTPS
        config = MediatorConfig(
            endpoint="https://example.com",
            sms_number="+1234567890",
        )
        assert config.endpoint.startswith("https://")
        
        # Valid HTTP
        config = MediatorConfig(
            endpoint="http://localhost:8080",
            sms_number="+1234567890",
        )
        assert config.endpoint.startswith("http://")
        
        # Invalid - not a URL
        with pytest.raises(ConfigurationError) as exc_info:
            MediatorConfig(
                endpoint="example.com/path",
                sms_number="+1234567890",
            )
        assert "HTTP(S) URL" in str(exc_info.value)


class TestEMRConfig:
    """Test suite for EMRConfig."""
    
    def test_valid_emr_config(self):
        """Test valid EMR configuration."""
        config = EMRConfig(
            type="openmrs",
            base_url="http://localhost:8080",
            fhir_endpoint="/fhir",
        )
        
        assert config.type == "openmrs"
        assert config.base_url == "http://localhost:8080"
        assert config.fhir_endpoint == "/fhir"
    
    def test_supported_emr_types(self):
        """Test that only supported EMR types are allowed."""
        for emr_type in ["openmrs", "openemr", "dhis2", "custom"]:
            config = EMRConfig(type=emr_type, base_url="http://localhost")
            assert config.type == emr_type
        
        with pytest.raises(ConfigurationError) as exc_info:
            EMRConfig(type="unsupported", base_url="http://localhost")
        assert "Unsupported EMR type" in str(exc_info.value)


class TestTransmissionConfig:
    """Test suite for TransmissionConfig."""
    
    def test_default_values(self):
        """Test default transmission configuration values."""
        config = TransmissionConfig()
        
        assert config.timeout_connect == 30.0
        assert config.timeout_read == 120.0
        assert config.max_retries == 5
        assert config.base_delay == 3.0
        assert config.max_delay == 300.0
        assert config.jitter is True
        assert config.keepalive_interval == 55.0
    
    def test_base_delay_minimum(self):
        """Test that base delay must be at least 1 second."""
        with pytest.raises(ConfigurationError) as exc_info:
            TransmissionConfig(base_delay=0.5)
        assert "at least 1 second" in str(exc_info.value)


class TestLoggingConfig:
    """Test suite for LoggingConfig."""
    
    def test_default_values(self):
        """Test default logging configuration values."""
        config = LoggingConfig()
        
        assert config.level == "INFO"
        assert config.file == "logs/nbogne.log"
        assert config.max_bytes == 10_485_760
        assert config.backup_count == 5
    
    def test_valid_log_levels(self):
        """Test that only valid log levels are accepted."""
        for level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            config = LoggingConfig(level=level)
            assert config.level == level
        
        # Lowercase should be normalized to uppercase
        config = LoggingConfig(level="debug")
        assert config.level == "DEBUG"
        
        with pytest.raises(ConfigurationError) as exc_info:
            LoggingConfig(level="INVALID")
        assert "Invalid log level" in str(exc_info.value)


class TestConfig:
    """Test suite for main Config class."""
    
    @pytest.fixture
    def valid_config_dict(self):
        """Return a valid configuration dictionary."""
        return {
            "facility": {
                "id": "FAC-001",
                "name": "Test Facility",
                "phone_number": "+1234567890",
            },
            "mediator": {
                "endpoint": "https://mediator.example.com/gsm/inbound",
                "sms_number": "+0987654321",
            },
            "emr": {
                "type": "openmrs",
                "base_url": "http://localhost:8080",
            },
        }
    
    @pytest.fixture
    def valid_config_file(self, valid_config_dict):
        """Create a temporary configuration file."""
        import yaml
        
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".yaml",
            delete=False
        ) as f:
            yaml.dump(valid_config_dict, f)
            yield f.name
        
        os.unlink(f.name)
    
    def test_from_dict(self, valid_config_dict):
        """Test creating Config from dictionary."""
        config = Config.from_dict(valid_config_dict)
        
        assert config.facility.id == "FAC-001"
        assert config.mediator.endpoint == "https://mediator.example.com/gsm/inbound"
        assert config.emr.type == "openmrs"
        
        # Check defaults are applied
        assert config.transmission.timeout_connect == 30.0
        assert config.queue.max_size == 10000
    
    def test_from_file(self, valid_config_file):
        """Test loading Config from YAML file."""
        config = Config.from_file(valid_config_file, use_env=False)
        
        assert config.facility.id == "FAC-001"
        assert config.mediator.endpoint == "https://mediator.example.com/gsm/inbound"
    
    def test_file_not_found(self):
        """Test error when config file doesn't exist."""
        with pytest.raises(ConfigurationError) as exc_info:
            Config.from_file("/nonexistent/path.yaml")
        assert "not found" in str(exc_info.value)
    
    def test_missing_required_fields(self):
        """Test error when required fields are missing."""
        with pytest.raises(ConfigurationError):
            Config.from_dict({})  # Missing all required sections
    
    def test_environment_overrides(self, valid_config_file, monkeypatch):
        """Test that environment variables override config file."""
        monkeypatch.setenv("NBOGNE_FACILITY_ID", "ENV-FAC")
        monkeypatch.setenv("NBOGNE_LOG_LEVEL", "DEBUG")
        
        config = Config.from_file(valid_config_file, use_env=True)
        
        assert config.facility.id == "ENV-FAC"
        assert config.logging.level == "DEBUG"
    
    def test_to_dict_redacts_sensitive(self, valid_config_dict):
        """Test that to_dict() redacts sensitive fields."""
        config = Config.from_dict(valid_config_dict)
        config_dict = config.to_dict()
        
        assert "REDACTED" in config_dict["facility"]["phone_number"]
        assert "REDACTED" in config_dict["mediator"]["sms_number"]
    
    def test_custom_transmission_values(self, valid_config_dict):
        """Test custom transmission configuration values."""
        valid_config_dict["transmission"] = {
            "timeout_connect": 60.0,
            "timeout_read": 180.0,
            "max_retries": 10,
            "base_delay": 5.0,
            "max_delay": 600.0,
            "jitter": False,
        }
        
        config = Config.from_dict(valid_config_dict)
        
        assert config.transmission.timeout_connect == 60.0
        assert config.transmission.timeout_read == 180.0
        assert config.transmission.max_retries == 10
        assert config.transmission.jitter is False
    
    def test_custom_queue_values(self, valid_config_dict):
        """Test custom queue configuration values."""
        valid_config_dict["queue"] = {
            "db_path": "/custom/path/queue.db",
            "max_size": 50000,
            "batch_size": 20,
            "drain_interval": 10.0,
        }
        
        config = Config.from_dict(valid_config_dict)
        
        assert config.queue.db_path == "/custom/path/queue.db"
        assert config.queue.max_size == 50000
        assert config.queue.batch_size == 20
    
    def test_custom_modem_values(self, valid_config_dict):
        """Test custom modem configuration values."""
        valid_config_dict["modem"] = {
            "port": "/dev/ttyACM0",
            "baudrate": 9600,
            "apn": "mtn",
            "model": "quectel",
        }
        
        config = Config.from_dict(valid_config_dict)
        
        assert config.modem.port == "/dev/ttyACM0"
        assert config.modem.baudrate == 9600
        assert config.modem.apn == "mtn"
        assert config.modem.model == "quectel"
