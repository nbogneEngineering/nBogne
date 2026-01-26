"""
Tests for the wire format module.

These tests verify:
    - Header encoding/decoding
    - Payload compression
    - Round-trip integrity
    - Edge cases and error handling
"""

import pytest
import uuid
import time
import json

from nbogne.wire_format import WireFormat, MessageType, MessageHeader
from nbogne.exceptions import WireFormatError, HeaderParseError, PayloadError


class TestWireFormat:
    """Test suite for WireFormat class."""
    
    @pytest.fixture
    def wire_format(self):
        """Create a WireFormat instance for testing."""
        return WireFormat()
    
    @pytest.fixture
    def sample_fhir_bundle(self):
        """Create a sample FHIR bundle for testing."""
        return json.dumps({
            "resourceType": "Bundle",
            "type": "message",
            "entry": [
                {
                    "resource": {
                        "resourceType": "Patient",
                        "id": "patient-123",
                        "name": [{"family": "Doe", "given": ["John"]}],
                        "birthDate": "1990-01-15",
                    }
                }
            ]
        }).encode("utf-8")
    
    def test_encode_decode_roundtrip(self, wire_format, sample_fhir_bundle):
        """Test that encoding then decoding returns original payload."""
        # Encode
        encoded = wire_format.encode(
            payload=sample_fhir_bundle,
            source="FAC-001",
            destination="FAC-002",
            message_type=MessageType.BUNDLE,
        )
        
        # Decode
        header, payload = wire_format.decode(encoded)
        
        # Verify payload integrity
        assert payload == sample_fhir_bundle
        
        # Verify header fields
        assert header.source_facility == "FAC-001"
        assert header.destination_facility == "FAC-002"
        assert header.message_type == MessageType.BUNDLE
        assert header.payload_length == len(sample_fhir_bundle)
        assert header.version == 1
    
    def test_encode_with_custom_message_id(self, wire_format, sample_fhir_bundle):
        """Test encoding with a custom message ID."""
        custom_id = str(uuid.uuid4())
        
        encoded = wire_format.encode(
            payload=sample_fhir_bundle,
            source="FAC-001",
            destination="FAC-002",
            message_type=MessageType.PATIENT,
            message_id=custom_id,
        )
        
        header, _ = wire_format.decode(encoded)
        
        assert header.message_id == custom_id
    
    def test_encode_with_custom_timestamp(self, wire_format, sample_fhir_bundle):
        """Test encoding with a custom timestamp."""
        custom_timestamp = 1704067200  # 2024-01-01 00:00:00 UTC
        
        encoded = wire_format.encode(
            payload=sample_fhir_bundle,
            source="FAC-001",
            destination="FAC-002",
            message_type=MessageType.OBSERVATION,
            timestamp=custom_timestamp,
        )
        
        header, _ = wire_format.decode(encoded)
        
        assert header.timestamp == custom_timestamp
    
    def test_compression_reduces_size(self, wire_format):
        """Test that compression significantly reduces payload size."""
        # Create a large, repetitive payload (compresses well)
        large_payload = json.dumps({
            "data": "x" * 10000,
            "more_data": ["item"] * 1000,
        }).encode("utf-8")
        
        encoded = wire_format.encode(
            payload=large_payload,
            source="SRC",
            destination="DST",
            message_type=MessageType.BUNDLE,
        )
        
        # Encoded should be smaller than original + header
        # (base64 adds ~33%, but gzip compression is much more)
        assert len(encoded) < len(large_payload)
    
    def test_header_size_is_48_bytes(self, wire_format, sample_fhir_bundle):
        """Test that header is exactly 48 bytes."""
        encoded = wire_format.encode(
            payload=sample_fhir_bundle,
            source="FAC-001",
            destination="FAC-002",
            message_type=MessageType.BUNDLE,
        )
        
        # Header should be first 48 bytes
        assert len(encoded) >= 48
        
        # Verify by checking struct size
        assert wire_format.HEADER_SIZE == 48
    
    def test_facility_id_padding(self, wire_format, sample_fhir_bundle):
        """Test that short facility IDs are properly padded."""
        # Test with short IDs
        encoded = wire_format.encode(
            payload=sample_fhir_bundle,
            source="A",
            destination="B",
            message_type=MessageType.BUNDLE,
        )
        
        header, _ = wire_format.decode(encoded)
        
        assert header.source_facility == "A"
        assert header.destination_facility == "B"
    
    def test_facility_id_max_length(self, wire_format, sample_fhir_bundle):
        """Test that 8-character facility IDs work."""
        encoded = wire_format.encode(
            payload=sample_fhir_bundle,
            source="12345678",
            destination="ABCDEFGH",
            message_type=MessageType.BUNDLE,
        )
        
        header, _ = wire_format.decode(encoded)
        
        assert header.source_facility == "12345678"
        assert header.destination_facility == "ABCDEFGH"
    
    def test_facility_id_too_long_raises_error(self, wire_format, sample_fhir_bundle):
        """Test that facility IDs over 8 characters raise error."""
        with pytest.raises(WireFormatError):
            wire_format.encode(
                payload=sample_fhir_bundle,
                source="123456789",  # 9 characters
                destination="FAC-002",
                message_type=MessageType.BUNDLE,
            )
    
    def test_all_message_types(self, wire_format, sample_fhir_bundle):
        """Test encoding/decoding with all message types."""
        for message_type in MessageType:
            encoded = wire_format.encode(
                payload=sample_fhir_bundle,
                source="SRC",
                destination="DST",
                message_type=message_type,
            )
            
            header, _ = wire_format.decode(encoded)
            
            assert header.message_type == message_type
    
    def test_empty_payload(self, wire_format):
        """Test encoding an empty payload."""
        encoded = wire_format.encode(
            payload=b"",
            source="SRC",
            destination="DST",
            message_type=MessageType.HEARTBEAT,
        )
        
        header, payload = wire_format.decode(encoded)
        
        # Empty payload should round-trip correctly
        assert payload == b""
        assert header.payload_length == 0
    
    def test_binary_payload(self, wire_format):
        """Test encoding binary (non-UTF8) payload."""
        binary_payload = bytes(range(256))
        
        encoded = wire_format.encode(
            payload=binary_payload,
            source="SRC",
            destination="DST",
            message_type=MessageType.BUNDLE,
        )
        
        header, payload = wire_format.decode(encoded)
        
        assert payload == binary_payload
    
    def test_decode_truncated_message_raises_error(self, wire_format):
        """Test that decoding truncated data raises error."""
        with pytest.raises(HeaderParseError):
            wire_format.decode(b"too short")
    
    def test_is_fragmented_property(self, wire_format, sample_fhir_bundle):
        """Test the is_fragmented header property."""
        # Non-fragmented message
        encoded = wire_format.encode(
            payload=sample_fhir_bundle,
            source="SRC",
            destination="DST",
            message_type=MessageType.BUNDLE,
            segment_number=0,
            total_segments=1,
        )
        
        header, _ = wire_format.decode(encoded)
        
        assert not header.is_fragmented
        assert header.is_complete
        
        # Fragmented message
        encoded = wire_format.encode(
            payload=sample_fhir_bundle,
            source="SRC",
            destination="DST",
            message_type=MessageType.BUNDLE,
            segment_number=1,
            total_segments=3,
            reference_number=12345,
        )
        
        header, _ = wire_format.decode(encoded)
        
        assert header.is_fragmented
        assert not header.is_complete
        assert header.segment_number == 1
        assert header.total_segments == 3
        assert header.reference_number == 12345
    
    def test_create_ack(self, wire_format, sample_fhir_bundle):
        """Test ACK message creation."""
        # First create original message
        original_encoded = wire_format.encode(
            payload=sample_fhir_bundle,
            source="FAC-001",
            destination="FAC-002",
            message_type=MessageType.REFERRAL,
        )
        
        original_header, _ = wire_format.decode(original_encoded)
        
        # Create ACK
        ack_encoded = wire_format.create_ack(
            original_header=original_header,
            source="FAC-002",
        )
        
        ack_header, ack_payload = wire_format.decode(ack_encoded)
        
        assert ack_header.message_type == MessageType.ACK
        assert ack_header.source_facility == "FAC-002"
        assert ack_header.destination_facility == "FAC-001"
        
        # Verify ACK payload references original
        ack_data = json.loads(ack_payload.decode("utf-8"))
        assert ack_data["ack_for"] == original_header.message_id
        assert ack_data["status"] == "received"
    
    def test_checksum_calculation(self, wire_format, sample_fhir_bundle):
        """Test checksum calculation."""
        checksum = wire_format.calculate_checksum(sample_fhir_bundle)
        
        # Should be 64 character hex string (SHA-256)
        assert len(checksum) == 64
        assert all(c in "0123456789abcdef" for c in checksum)
        
        # Same input should give same checksum
        checksum2 = wire_format.calculate_checksum(sample_fhir_bundle)
        assert checksum == checksum2
        
        # Different input should give different checksum
        checksum3 = wire_format.calculate_checksum(b"different")
        assert checksum != checksum3
    
    def test_estimate_size(self, wire_format):
        """Test size estimation."""
        # With 30% compression ratio
        estimated = wire_format.estimate_size(1000, compression_ratio=0.3)
        
        # Should be: 48 (header) + (1000 * 0.3 * 1.34) = 48 + 402 = 450
        assert 400 < estimated < 500
    
    def test_header_to_dict(self, wire_format, sample_fhir_bundle):
        """Test header serialization to dictionary."""
        encoded = wire_format.encode(
            payload=sample_fhir_bundle,
            source="FAC-001",
            destination="FAC-002",
            message_type=MessageType.PATIENT,
        )
        
        header, _ = wire_format.decode(encoded)
        header_dict = header.to_dict()
        
        assert header_dict["source_facility"] == "FAC-001"
        assert header_dict["destination_facility"] == "FAC-002"
        assert header_dict["message_type"] == "PATIENT"
        assert "message_id" in header_dict
        assert "timestamp" in header_dict


class TestMessageType:
    """Test suite for MessageType enum."""
    
    def test_all_types_have_unique_values(self):
        """Test that all message types have unique values."""
        values = [mt.value for mt in MessageType]
        assert len(values) == len(set(values))
    
    def test_specific_type_values(self):
        """Test specific message type values match specification."""
        assert MessageType.REFERRAL.value == 0x0001
        assert MessageType.OBSERVATION.value == 0x0002
        assert MessageType.PATIENT.value == 0x0003
        assert MessageType.ACK.value == 0x0007
        assert MessageType.ERROR.value == 0x00FF
