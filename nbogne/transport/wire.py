"""
Wire Protocol

Handles:
1. Building wire packets (header + payload + CRC)
2. SMS segmentation (binary segments, 134 bytes per GSM data SMS)
3. Reassembly from SMS segments

Binary SMS mode: each segment carries raw bytes (no Base64 overhead).
Segment format: [1B index][1B total][up to 132B data] = max 134 bytes per segment.
"""
import struct
import math
from typing import Optional
from config import SMS_BINARY_BYTES_PER_SEGMENT, SMS_MAX_SEGMENTS

# Usable data bytes per segment after 2-byte framing header
_DATA_PER_SEGMENT = SMS_BINARY_BYTES_PER_SEGMENT - 2  # 132


def packet_to_sms_segments(wire_bytes: bytes) -> list[bytes]:
    """Convert wire packet bytes to binary SMS segments.

    Each segment is raw bytes: [1B index][1B total][data].
    Max 134 bytes per segment (134 = GSM binary SMS capacity with UDH).
    """
    total_segments = math.ceil(len(wire_bytes) / _DATA_PER_SEGMENT)

    if total_segments > SMS_MAX_SEGMENTS:
        raise ValueError(
            f"Payload too large: {len(wire_bytes)} bytes = {total_segments} segments "
            f"(max {SMS_MAX_SEGMENTS})"
        )

    segments = []
    for i in range(total_segments):
        chunk = wire_bytes[i * _DATA_PER_SEGMENT:(i + 1) * _DATA_PER_SEGMENT]
        header = struct.pack('!BB', i + 1, total_segments)
        segments.append(header + chunk)

    return segments


def sms_segments_to_packet(segments: list[bytes]) -> bytes:
    """Reassemble binary SMS segments back to wire packet bytes.

    Handles out-of-order arrival by sorting on index byte.
    """
    parsed = []
    for seg in segments:
        idx = seg[0]
        total = seg[1]
        data = seg[2:]
        parsed.append((idx, total, data))

    parsed.sort(key=lambda x: x[0])

    # Verify completeness
    if parsed:
        expected_total = parsed[0][1]
        received = {p[0] for p in parsed}
        expected = set(range(1, expected_total + 1))
        if received != expected:
            missing = expected - received
            raise ValueError(f"Missing SMS segments: {missing}")

    return b''.join(p[2] for p in parsed)


def estimate_sms_count(payload_bytes: int) -> int:
    """Estimate how many SMS segments a payload will need."""
    # Payload → L1 encrypt (+16 tag) → wire header (~15) → L2 encrypt (+28) = ~59 bytes overhead
    total_bytes = payload_bytes + 16 + 15 + 28
    return math.ceil(total_bytes / _DATA_PER_SEGMENT)
