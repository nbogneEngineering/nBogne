"""
Wire Protocol

Handles:
1. Building wire packets (header + payload + CRC)
2. SMS segmentation (splitting into 134-byte chunks)
3. Base64 encoding for SMS text mode
4. Reassembly from SMS segments
"""
import base64
import struct
import math
from typing import Optional
from config import SMS_BINARY_BYTES_PER_SEGMENT, SMS_MAX_SEGMENTS


def packet_to_sms_segments(wire_bytes: bytes) -> list[str]:
    """Convert wire packet bytes to Base64-encoded SMS segments.

    Each segment is a string that fits in one SMS (153 chars for concat, 160 for single).
    Segments are prefixed with index: "01/03:..." for reassembly.
    """
    b64 = base64.b64encode(wire_bytes).decode('ascii')
    # Each SMS text segment: 153 chars max (concatenated), minus 6 chars for "NN/NN:" prefix
    chars_per_segment = 147
    total_segments = math.ceil(len(b64) / chars_per_segment)

    if total_segments > SMS_MAX_SEGMENTS:
        raise ValueError(
            f"Payload too large: {len(wire_bytes)} bytes = {total_segments} segments "
            f"(max {SMS_MAX_SEGMENTS})"
        )

    segments = []
    for i in range(total_segments):
        chunk = b64[i * chars_per_segment:(i + 1) * chars_per_segment]
        prefix = f"{i+1:02d}/{total_segments:02d}:"
        segments.append(prefix + chunk)

    return segments


def sms_segments_to_packet(segments: list[str]) -> bytes:
    """Reassemble SMS segments back to wire packet bytes.

    Handles out-of-order arrival by sorting on prefix.
    """
    # Parse and sort segments
    parsed = []
    for seg in segments:
        if '/' in seg[:5] and ':' in seg[:6]:
            idx = int(seg[:2])
            total = int(seg[3:5])
            data = seg[6:]
            parsed.append((idx, total, data))
        else:
            # No prefix — single segment
            parsed.append((1, 1, seg))

    parsed.sort(key=lambda x: x[0])

    # Verify completeness
    if parsed:
        expected_total = parsed[0][1]
        received = {p[0] for p in parsed}
        expected = set(range(1, expected_total + 1))
        if received != expected:
            missing = expected - received
            raise ValueError(f"Missing SMS segments: {missing}")

    b64 = ''.join(p[2] for p in parsed)
    return base64.b64decode(b64)


def estimate_sms_count(payload_bytes: int) -> int:
    """Estimate how many SMS segments a payload will need."""
    # Payload → L1 encrypt (+28) → wire header (~15) → L2 encrypt (+28) → Base64 (×4/3)
    total_bytes = payload_bytes + 28 + 15 + 28  # ~71 bytes overhead
    b64_chars = math.ceil(total_bytes * 4 / 3)
    chars_per_segment = 147
    return math.ceil(b64_chars / chars_per_segment)
