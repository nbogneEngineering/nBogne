"""
nBogne Data Models and Wire Protocol

Wire format:
  [MAGIC 2B][VER 1B][FLAGS 1B][MSG_ID 4B][TEMPLATE_ID 1B][DEST_LEN 1B][DEST varB][PAYLOAD_LEN 2B][PAYLOAD varB][CRC16 2B]

FLAGS byte:
  bit 0: 0=templated, 1=fallback (full compressed)
  bit 1: 0=data, 1=handshake/ACK
  bit 2: 0=single, 1=multi-part (reserved)
  bits 3-7: reserved
"""
import struct
import hashlib
import uuid
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional


class PacketType(IntEnum):
    TEMPLATED = 0       # Template-based encoded data
    FALLBACK = 1        # Full compressed (FhirProto-style + zstd)
    HANDSHAKE = 2       # ACK message


@dataclass
class WirePacket:
    msg_id: bytes           # 4 bytes, unique per transmission
    template_id: int        # 0-255 (0 = fallback/no template)
    destination: str        # Phone number of destination modem
    payload: bytes          # Compressed + encrypted payload
    packet_type: PacketType = PacketType.TEMPLATED
    version: int = 1

    def encode(self) -> bytes:
        """Encode packet to wire format bytes."""
        from config import WIRE_MAGIC, WIRE_VERSION

        flags = 0
        if self.packet_type == PacketType.FALLBACK:
            flags |= 0x01
        elif self.packet_type == PacketType.HANDSHAKE:
            flags |= 0x02

        dest_bytes = self.destination.encode('ascii')
        dest_len = len(dest_bytes)

        # Pack header + payload
        header = struct.pack(
            '!2sBBB',
            WIRE_MAGIC,
            self.version & 0xFF,
            flags,
            self.template_id & 0xFF,
        )
        msg_id_bytes = self.msg_id[:4].ljust(4, b'\x00')
        dest_part = struct.pack('!B', dest_len) + dest_bytes
        payload_part = struct.pack('!H', len(self.payload)) + self.payload

        packet_no_crc = header + msg_id_bytes + dest_part + payload_part

        # CRC16 (CCITT)
        crc = _crc16(packet_no_crc)
        return packet_no_crc + struct.pack('!H', crc)

    @classmethod
    def decode(cls, data: bytes) -> 'WirePacket':
        """Decode wire format bytes to WirePacket."""
        from config import WIRE_MAGIC

        if len(data) < 12:
            raise ValueError(f"Packet too short: {len(data)} bytes")

        # Verify magic
        if data[0:2] != WIRE_MAGIC:
            raise ValueError(f"Invalid magic: {data[0:2].hex()}")

        # Verify CRC
        crc_received = struct.unpack('!H', data[-2:])[0]
        crc_computed = _crc16(data[:-2])
        if crc_received != crc_computed:
            raise ValueError(f"CRC mismatch: received={crc_received}, computed={crc_computed}")

        version = data[2]
        flags = data[3]
        template_id = data[4]
        msg_id = data[5:9]

        dest_len = data[9]
        dest = data[10:10 + dest_len].decode('ascii')

        payload_offset = 10 + dest_len
        payload_len = struct.unpack('!H', data[payload_offset:payload_offset + 2])[0]
        payload = data[payload_offset + 2:payload_offset + 2 + payload_len]

        if flags & 0x02:
            ptype = PacketType.HANDSHAKE
        elif flags & 0x01:
            ptype = PacketType.FALLBACK
        else:
            ptype = PacketType.TEMPLATED

        return cls(
            msg_id=msg_id,
            template_id=template_id,
            destination=dest,
            payload=payload,
            packet_type=ptype,
            version=version,
        )


@dataclass
class TransmissionRecord:
    """Tracks a single transmission attempt in the queue."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    msg_id: bytes = b''
    patient_record_id: str = ''
    fhir_resource_type: str = ''
    raw_size: int = 0
    compressed_size: int = 0
    wire_size: int = 0
    sms_segments: int = 0
    status: str = 'PENDING'  # PENDING, SENDING, COMPLETE, FAILED
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    retry_count: int = 0
    carrier: str = ''
    error: str = ''


@dataclass
class Handshake:
    """ACK message sent back from receiver to sender."""
    msg_id: bytes
    status: str  # 'RECEIVED', 'ERROR'
    timestamp: float = field(default_factory=time.time)

    def to_bytes(self) -> bytes:
        return struct.pack('!4sB d', self.msg_id[:4], 1 if self.status == 'RECEIVED' else 0, self.timestamp)

    @classmethod
    def from_bytes(cls, data: bytes) -> 'Handshake':
        msg_id, status_byte, ts = struct.unpack('!4sB d', data[:13])
        return cls(msg_id=msg_id, status='RECEIVED' if status_byte else 'ERROR', timestamp=ts)


def generate_msg_id() -> bytes:
    """Generate a 4-byte message ID."""
    return uuid.uuid4().bytes[:4]


def _crc16(data: bytes) -> int:
    """CRC-16/CCITT-FALSE."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc <<= 1
            crc &= 0xFFFF
    return crc
