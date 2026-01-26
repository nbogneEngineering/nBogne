"""
Wire Format implementation for nBogne transport protocol.

This module implements the binary wire format used for GPRS and SMS transmission
of health data. The format consists of a fixed 48-byte header followed by a
compressed and encoded payload.

Header Structure (48 bytes, big-endian):
    ┌────────────────────────────────────────────────────────────────┐
    │ Offset │ Size │ Field              │ Description               │
    ├────────┼──────┼────────────────────┼───────────────────────────┤
    │ 0      │ 2    │ Version            │ Protocol version (0x0001) │
    │ 2      │ 16   │ Message ID         │ UUID v4 as raw bytes      │
    │ 18     │ 8    │ Source Facility    │ Left-padded with 0x00     │
    │ 26     │ 8    │ Dest Facility      │ Left-padded with 0x00     │
    │ 34     │ 2    │ Message Type       │ See MessageType enum      │
    │ 36     │ 4    │ Timestamp          │ Unix timestamp (seconds)  │
    │ 40     │ 4    │ Payload Length     │ Uncompressed length       │
    │ 44     │ 1    │ Segment Number     │ 0 if not fragmented       │
    │ 45     │ 1    │ Total Segments     │ 1 if not fragmented       │
    │ 46     │ 2    │ Reference Number   │ For segment reassembly    │
    └────────────────────────────────────────────────────────────────┘

Payload Processing:
    1. Original FHIR JSON
    2. Compress with gzip (60-80% reduction)
    3. Encode with base64 (for SMS compatibility)
    4. Prepend 48-byte header

Example:
    >>> from nbogne.wire_format import WireFormat, MessageType
    >>> wf = WireFormat()
    >>> 
    >>> # Encode a FHIR bundle
    >>> fhir_json = '{"resourceType": "Bundle", ...}'
    >>> message = wf.encode(
    ...     payload=fhir_json.encode(),
    ...     source="FAC-001",
    ...     destination="FAC-002", 
    ...     message_type=MessageType.REFERRAL
    ... )
    >>> 
    >>> # Decode received message
    >>> header, payload = wf.decode(message)
    >>> print(header.source_facility)
    'FAC-001'
"""

import gzip
import base64
import struct
import hashlib
import uuid
import time
import logging
from dataclasses import dataclass
from enum import IntEnum
from typing import Optional, Tuple

from nbogne.exceptions import (
    WireFormatError,
    HeaderParseError,
    PayloadError,
)

logger = logging.getLogger(__name__)


class MessageType(IntEnum):
    """Message type codes for the wire format header.
    
    These codes identify the type of health data being transmitted,
    allowing receivers to route and process messages appropriately.
    """
    REFERRAL = 0x0001       # Patient referral between facilities
    OBSERVATION = 0x0002    # Lab results, vital signs, etc.
    PATIENT = 0x0003        # Patient demographic data
    ENCOUNTER = 0x0004      # Clinical encounter record
    BUNDLE = 0x0005         # Generic FHIR bundle
    RESPONSE = 0x0006       # Response to a previous message
    ACK = 0x0007            # Acknowledgment (delivery receipt)
    NACK = 0x0008           # Negative acknowledgment (error)
    HEARTBEAT = 0x00FE      # Keep-alive / status check
    ERROR = 0x00FF          # Error message


@dataclass(frozen=True)
class MessageHeader:
    """Parsed message header from wire format.
    
    This immutable dataclass represents the decoded 48-byte header,
    providing typed access to all header fields.
    
    Attributes:
        version: Protocol version (currently 1)
        message_id: UUID v4 identifying this message
        source_facility: Originating facility ID
        destination_facility: Target facility ID
        message_type: Type of message (see MessageType enum)
        timestamp: Unix timestamp when message was created
        payload_length: Length of uncompressed payload in bytes
        segment_number: Segment index (0 = complete message)
        total_segments: Total number of segments (1 = complete message)
        reference_number: Shared ID for segment reassembly
    """
    version: int
    message_id: str
    source_facility: str
    destination_facility: str
    message_type: MessageType
    timestamp: int
    payload_length: int
    segment_number: int
    total_segments: int
    reference_number: int
    
    @property
    def is_fragmented(self) -> bool:
        """Check if this message is part of a fragmented transmission."""
        return self.total_segments > 1
    
    @property
    def is_complete(self) -> bool:
        """Check if this is a complete (non-fragmented) message."""
        return self.segment_number == 0 and self.total_segments == 1
    
    def to_dict(self) -> dict:
        """Convert header to dictionary for logging/serialization."""
        return {
            "version": self.version,
            "message_id": self.message_id,
            "source_facility": self.source_facility,
            "destination_facility": self.destination_facility,
            "message_type": self.message_type.name,
            "timestamp": self.timestamp,
            "payload_length": self.payload_length,
            "segment_number": self.segment_number,
            "total_segments": self.total_segments,
            "reference_number": self.reference_number,
        }


class WireFormat:
    """Encoder/decoder for the nBogne wire format protocol.
    
    This class handles the complete encoding and decoding of messages
    for transmission over GPRS or SMS, including compression, encoding,
    and header generation/parsing.
    
    The wire format is designed for:
        - Minimal bandwidth usage (gzip compression)
        - Binary-safe transmission (base64 encoding)
        - Message integrity (built-in length fields)
        - Fragmentation support (for SMS fallback)
    
    Thread Safety:
        This class is thread-safe. All methods are stateless and can be
        called concurrently from multiple threads.
    
    Example:
        >>> wf = WireFormat()
        >>> encoded = wf.encode(
        ...     payload=b'{"resourceType": "Patient"}',
        ...     source="FAC-01",
        ...     destination="CENTRAL",
        ...     message_type=MessageType.PATIENT
        ... )
        >>> print(f"Encoded size: {len(encoded)} bytes")
        
        >>> header, payload = wf.decode(encoded)
        >>> print(f"From: {header.source_facility}")
    """
    
    # Protocol constants
    HEADER_SIZE = 48
    PROTOCOL_VERSION = 0x0001
    FACILITY_ID_SIZE = 8
    
    # Struct format for header (big-endian)
    # H = unsigned short (2 bytes)
    # 16s = 16 bytes (UUID)
    # 8s = 8 bytes (facility IDs)
    # I = unsigned int (4 bytes)
    # B = unsigned char (1 byte)
    HEADER_FORMAT = ">H16s8s8sHIIBBH"
    
    def __init__(self, compression_level: int = 6):
        """Initialize the wire format encoder/decoder.
        
        Args:
            compression_level: gzip compression level (1-9, default 6)
                              Higher = better compression, more CPU
                              For GPRS, 6-9 recommended (bandwidth > CPU)
        """
        self.compression_level = compression_level
        
        # Verify struct format matches expected header size
        calculated_size = struct.calcsize(self.HEADER_FORMAT)
        if calculated_size != self.HEADER_SIZE:
            raise WireFormatError(
                f"Header format mismatch: expected {self.HEADER_SIZE}, "
                f"calculated {calculated_size}"
            )
    
    def encode(
        self,
        payload: bytes,
        source: str,
        destination: str,
        message_type: MessageType,
        message_id: Optional[str] = None,
        timestamp: Optional[int] = None,
        segment_number: int = 0,
        total_segments: int = 1,
        reference_number: int = 0,
    ) -> bytes:
        """Encode a payload with the wire format header.
        
        This method:
            1. Compresses the payload with gzip
            2. Encodes the compressed data with base64
            3. Generates the 48-byte header
            4. Returns header + encoded payload
        
        Args:
            payload: Raw payload bytes (typically FHIR JSON)
            source: Source facility ID (max 8 characters)
            destination: Destination facility ID (max 8 characters)
            message_type: Type of message being sent
            message_id: Optional UUID (generated if not provided)
            timestamp: Optional Unix timestamp (current time if not provided)
            segment_number: Segment index for fragmented messages (0 = complete)
            total_segments: Total segments for fragmented messages (1 = complete)
            reference_number: Shared ID for segment reassembly
        
        Returns:
            Complete message bytes (header + encoded payload)
        
        Raises:
            PayloadError: If compression or encoding fails
            WireFormatError: If facility IDs are too long
        """
        # Validate facility IDs
        if len(source) > self.FACILITY_ID_SIZE:
            raise WireFormatError(
                f"Source facility ID too long: {len(source)} > {self.FACILITY_ID_SIZE}"
            )
        if len(destination) > self.FACILITY_ID_SIZE:
            raise WireFormatError(
                f"Destination facility ID too long: {len(destination)} > {self.FACILITY_ID_SIZE}"
            )
        
        # Generate message ID if not provided
        if message_id is None:
            message_id = str(uuid.uuid4())
        
        # Use current timestamp if not provided
        if timestamp is None:
            timestamp = int(time.time())
        
        # Store original length before compression
        original_length = len(payload)
        
        # Compress payload
        try:
            compressed = gzip.compress(payload, compresslevel=self.compression_level)
            if original_length > 0:
                compression_ratio = (1 - len(compressed) / original_length) * 100
                logger.debug(
                    f"Compressed payload: {original_length} -> {len(compressed)} bytes "
                    f"({compression_ratio:.1f}% reduction)"
                )
            else:
                logger.debug("Empty payload, compression skipped")
        except Exception as e:
            raise PayloadError(f"Compression failed: {e}", operation="gzip.compress")
        
        # Base64 encode for binary-safe transmission
        try:
            encoded_payload = base64.b64encode(compressed)
        except Exception as e:
            raise PayloadError(f"Base64 encoding failed: {e}", operation="base64.encode")
        
        # Build header
        header = self._build_header(
            message_id=message_id,
            source=source,
            destination=destination,
            message_type=message_type,
            timestamp=timestamp,
            payload_length=original_length,
            segment_number=segment_number,
            total_segments=total_segments,
            reference_number=reference_number,
        )
        
        logger.debug(
            f"Encoded message: id={message_id[:8]}..., type={message_type.name}, "
            f"total_size={len(header) + len(encoded_payload)} bytes"
        )
        
        return header + encoded_payload
    
    def decode(self, data: bytes) -> Tuple[MessageHeader, bytes]:
        """Decode a wire format message.
        
        This method:
            1. Parses the 48-byte header
            2. Decodes the base64 payload
            3. Decompresses the gzip payload
            4. Returns the header and original payload
        
        Args:
            data: Complete message bytes (header + encoded payload)
        
        Returns:
            Tuple of (MessageHeader, decoded_payload_bytes)
        
        Raises:
            HeaderParseError: If header parsing fails
            PayloadError: If decoding or decompression fails
        """
        if len(data) < self.HEADER_SIZE:
            raise HeaderParseError(
                f"Message too short: {len(data)} bytes (minimum {self.HEADER_SIZE})",
                raw_bytes=data
            )
        
        # Parse header
        header = self._parse_header(data[:self.HEADER_SIZE])
        
        # Extract and decode payload
        encoded_payload = data[self.HEADER_SIZE:]
        
        if not encoded_payload:
            logger.debug(f"Message {header.message_id[:8]}... has empty payload")
            return header, b""
        
        # Base64 decode
        try:
            compressed = base64.b64decode(encoded_payload)
        except Exception as e:
            raise PayloadError(f"Base64 decoding failed: {e}", operation="base64.decode")
        
        # Decompress
        try:
            payload = gzip.decompress(compressed)
        except Exception as e:
            raise PayloadError(f"Decompression failed: {e}", operation="gzip.decompress")
        
        # Verify payload length matches header
        if len(payload) != header.payload_length:
            logger.warning(
                f"Payload length mismatch: header says {header.payload_length}, "
                f"got {len(payload)} bytes"
            )
        
        logger.debug(
            f"Decoded message: id={header.message_id[:8]}..., "
            f"type={header.message_type.name}, payload_size={len(payload)} bytes"
        )
        
        return header, payload
    
    def _build_header(
        self,
        message_id: str,
        source: str,
        destination: str,
        message_type: MessageType,
        timestamp: int,
        payload_length: int,
        segment_number: int,
        total_segments: int,
        reference_number: int,
    ) -> bytes:
        """Build the 48-byte binary header.
        
        Args:
            message_id: UUID string
            source: Source facility ID
            destination: Destination facility ID
            message_type: Message type enum value
            timestamp: Unix timestamp
            payload_length: Original (uncompressed) payload length
            segment_number: Segment index (0 for complete messages)
            total_segments: Total segment count (1 for complete messages)
            reference_number: Shared ID for fragmentation
        
        Returns:
            48-byte header as bytes
        """
        # Convert UUID string to bytes
        try:
            uuid_bytes = uuid.UUID(message_id).bytes
        except ValueError as e:
            raise WireFormatError(f"Invalid message ID format: {e}")
        
        # Pad facility IDs to 8 bytes (left-pad with null bytes)
        source_bytes = source.encode("ascii").rjust(self.FACILITY_ID_SIZE, b"\x00")
        dest_bytes = destination.encode("ascii").rjust(self.FACILITY_ID_SIZE, b"\x00")
        
        # Pack header
        header = struct.pack(
            self.HEADER_FORMAT,
            self.PROTOCOL_VERSION,
            uuid_bytes,
            source_bytes,
            dest_bytes,
            int(message_type),
            timestamp,
            payload_length,
            segment_number,
            total_segments,
            reference_number,
        )
        
        return header
    
    def _parse_header(self, header_bytes: bytes) -> MessageHeader:
        """Parse the 48-byte binary header.
        
        Args:
            header_bytes: Exactly 48 bytes of header data
        
        Returns:
            Parsed MessageHeader dataclass
        
        Raises:
            HeaderParseError: If parsing fails
        """
        try:
            (
                version,
                uuid_bytes,
                source_bytes,
                dest_bytes,
                message_type_raw,
                timestamp,
                payload_length,
                segment_number,
                total_segments,
                reference_number,
            ) = struct.unpack(self.HEADER_FORMAT, header_bytes)
        except struct.error as e:
            raise HeaderParseError(f"Failed to unpack header: {e}", raw_bytes=header_bytes)
        
        # Convert UUID bytes to string
        try:
            message_id = str(uuid.UUID(bytes=uuid_bytes))
        except ValueError as e:
            raise HeaderParseError(f"Invalid UUID in header: {e}", raw_bytes=header_bytes)
        
        # Decode facility IDs (strip null padding)
        source = source_bytes.lstrip(b"\x00").decode("ascii", errors="replace")
        destination = dest_bytes.lstrip(b"\x00").decode("ascii", errors="replace")
        
        # Convert message type
        try:
            message_type = MessageType(message_type_raw)
        except ValueError:
            logger.warning(f"Unknown message type: 0x{message_type_raw:04X}, using BUNDLE")
            message_type = MessageType.BUNDLE
        
        return MessageHeader(
            version=version,
            message_id=message_id,
            source_facility=source,
            destination_facility=destination,
            message_type=message_type,
            timestamp=timestamp,
            payload_length=payload_length,
            segment_number=segment_number,
            total_segments=total_segments,
            reference_number=reference_number,
        )
    
    def create_ack(
        self,
        original_header: MessageHeader,
        source: str,
    ) -> bytes:
        """Create an acknowledgment message for a received message.
        
        Args:
            original_header: Header of the message being acknowledged
            source: Facility ID sending the acknowledgment
        
        Returns:
            Encoded ACK message
        """
        ack_payload = {
            "ack_for": original_header.message_id,
            "received_at": int(time.time()),
            "status": "received",
        }
        
        import json
        return self.encode(
            payload=json.dumps(ack_payload).encode("utf-8"),
            source=source,
            destination=original_header.source_facility,
            message_type=MessageType.ACK,
        )
    
    def calculate_checksum(self, data: bytes) -> str:
        """Calculate SHA-256 checksum of data.
        
        This is used for integrity verification, not included in the header
        but can be transmitted separately or logged for auditing.
        
        Args:
            data: Bytes to checksum
        
        Returns:
            Hex-encoded SHA-256 hash
        """
        return hashlib.sha256(data).hexdigest()
    
    @staticmethod
    def estimate_size(payload_size: int, compression_ratio: float = 0.3) -> int:
        """Estimate the encoded message size.
        
        Useful for determining if SMS fragmentation will be needed.
        
        Args:
            payload_size: Original payload size in bytes
            compression_ratio: Expected compression ratio (0.3 = 70% reduction)
        
        Returns:
            Estimated total message size in bytes
        """
        compressed_size = int(payload_size * compression_ratio)
        # Base64 encoding increases size by ~33%
        encoded_size = int(compressed_size * 1.34)
        return WireFormat.HEADER_SIZE + encoded_size
