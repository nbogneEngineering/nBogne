"""
Binary Value Encoder

Packs extracted FHIR values into compact binary.
Each field type has a specific encoding:
  - string: length-prefixed UTF-8 (1 byte len + data)
  - date: 2 bytes (days since 2020-01-01)
  - code: 2 bytes (index into shared codebook)
  - uint8/uint16: fixed width
  - float16: value * 10 as uint16 (1 decimal precision)
  - float32: IEEE 754
  - text: length-prefixed UTF-8 (2 bytes len + data)
"""
import struct
from datetime import date, datetime
from typing import Any

from compression.codebook import encode_code, decode_code, NOT_IN_CODEBOOK


DATE_EPOCH = date(2020, 1, 1)


def encode_values(values: dict, template: dict) -> bytes:
    """Encode extracted values to compact binary using template field definitions."""
    parts = []
    for field_def in template["fields"]:
        path = field_def["path"]
        ftype = field_def["type"]
        val = values.get(path, _default_for_type(ftype))
        parts.append(_encode_field(val, ftype, field_def))
    return b''.join(parts)


def decode_values(data: bytes, template: dict) -> dict:
    """Decode compact binary back to values dict using template field definitions."""
    offset = 0
    values = {}
    for field_def in template["fields"]:
        path = field_def["path"]
        ftype = field_def["type"]
        val, consumed = _decode_field(data, offset, ftype, field_def)
        values[path] = val
        offset += consumed
    return values


def _encode_field(val: Any, ftype: str, field_def: dict) -> bytes:
    if ftype == "string":
        s = str(val)[:field_def.get("max_len", 255)].encode('utf-8')
        return struct.pack('!B', len(s)) + s

    elif ftype == "text":
        s = str(val)[:field_def.get("max_len", 500)].encode('utf-8')
        return struct.pack('!H', len(s)) + s

    elif ftype == "date":
        if isinstance(val, str) and val:
            try:
                d = datetime.strptime(val[:10], "%Y-%m-%d").date()
                days = (d - DATE_EPOCH).days
            except ValueError:
                days = 0
        else:
            days = 0
        return struct.pack('!H', max(0, min(65535, days)))

    elif ftype == "code":
        codebook_name = field_def.get("codebook", "")
        if codebook_name:
            idx, found = encode_code(str(val), codebook_name)
            if found:
                return struct.pack('!H', idx)  # 2 bytes
            else:
                # Not in codebook: sentinel + inline string
                s = str(val)[:20].encode('utf-8')
                return struct.pack('!HB', NOT_IN_CODEBOOK, len(s)) + s
        # No codebook specified, fall back to string
        s = str(val)[:20].encode('utf-8')
        return struct.pack('!B', len(s)) + s

    elif ftype == "uint8":
        return struct.pack('!B', int(val) & 0xFF)

    elif ftype == "uint16":
        return struct.pack('!H', int(val) & 0xFFFF)

    elif ftype == "float16":
        # Store as uint16 with 1 decimal: 36.5 -> 365
        return struct.pack('!H', int(float(val) * 10) & 0xFFFF)

    elif ftype == "float32":
        return struct.pack('!f', float(val))

    elif ftype == "offset_uint8":
        offset = field_def.get("offset", 0)
        scale = field_def.get("scale", 1)
        val_f = float(val)
        if val_f == 0:  # missing
            return struct.pack('!B', 0)
        raw = int((val_f - offset) * scale)
        raw = max(1, min(255, raw))  # 0 reserved for missing
        return struct.pack('!B', raw)

    else:
        raise ValueError(f"Unknown field type: {ftype}")


def _decode_field(data: bytes, offset: int, ftype: str, field_def: dict):
    if ftype == "string":
        slen = data[offset]
        s = data[offset + 1:offset + 1 + slen].decode('utf-8')
        return s, 1 + slen

    elif ftype == "text":
        slen = struct.unpack('!H', data[offset:offset + 2])[0]
        s = data[offset + 2:offset + 2 + slen].decode('utf-8')
        return s, 2 + slen

    elif ftype == "date":
        days = struct.unpack('!H', data[offset:offset + 2])[0]
        if days == 0:
            return "", 2
        d = DATE_EPOCH
        from datetime import timedelta
        d = d + timedelta(days=days)
        return d.strftime("%Y-%m-%d"), 2

    elif ftype == "code":
        codebook_name = field_def.get("codebook", "")
        if codebook_name:
            idx = struct.unpack('!H', data[offset:offset + 2])[0]
            if idx != NOT_IN_CODEBOOK:
                return decode_code(idx, codebook_name), 2
            else:
                slen = data[offset + 2]
                s = data[offset + 3:offset + 3 + slen].decode('utf-8')
                return s, 3 + slen
        # No codebook
        slen = data[offset]
        s = data[offset + 1:offset + 1 + slen].decode('utf-8')
        return s, 1 + slen

    elif ftype == "uint8":
        return data[offset], 1

    elif ftype == "uint16":
        return struct.unpack('!H', data[offset:offset + 2])[0], 2

    elif ftype == "float16":
        raw = struct.unpack('!H', data[offset:offset + 2])[0]
        return raw / 10.0, 2

    elif ftype == "float32":
        return struct.unpack('!f', data[offset:offset + 4])[0], 4

    elif ftype == "offset_uint8":
        field_offset = field_def.get("offset", 0)
        scale = field_def.get("scale", 1)
        raw = data[offset]
        if raw == 0:
            return 0.0, 1
        return round(raw / scale + field_offset, 1), 1

    else:
        raise ValueError(f"Unknown field type: {ftype}")


def _default_for_type(ftype: str):
    return {"string": "", "text": "", "date": "", "code": "",
            "uint8": 0, "uint16": 0, "float16": 0.0, "float32": 0.0,
            "offset_uint8": 0.0}.get(ftype, "")
