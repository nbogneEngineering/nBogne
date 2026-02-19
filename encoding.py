"""
nBogne Transport — Encoding
Pack health record dicts into USSD-safe chunked strings.
Each chunk ≤178 chars, GSM 7-bit only, pipe-delimited key=value.
"""

import hashlib
from datetime import datetime
import config

# Abbreviate common fields to save bytes
ABBR = {
    'patient_id': 'P', 'temperature': 'T', 'heart_rate': 'HR',
    'blood_pressure': 'BP', 'spo2': 'O2', 'weight': 'W', 'height': 'HT',
    'fasting_blood_sugar': 'FBS', 'hemoglobin': 'HB', 'platelets': 'PLT',
    'wbc': 'WBC', 'rbc': 'RBC', 'creatinine': 'CRT', 'diagnosis': 'DX',
    'prescription': 'RX', 'notes': 'NT', 'visit_type': 'VT',
    'facility_id': 'FID', 'timestamp': 'TS', 'record_id': 'RID',
}
ABBR_REV = {v: k for k, v in ABBR.items()}

# These cost 2 septets in GSM 7-bit — avoid
_EXPENSIVE = set('{}[]\\~^€')


def encode(data: dict, record_id: str = '') -> list[str]:
    """
    Encode a health record into USSD chunks.
    Returns list of strings like: '1/2:a3f1:RID=abc:P=GH42:T=36.5:HR=72'
    """
    data.setdefault('facility_id', config.FACILITY_ID)
    data.setdefault('timestamp', datetime.utcnow().strftime('%y%m%d%H%M%S'))

    pairs = []
    if record_id:
        pairs.append(f'RID={record_id}')
    for key, val in data.items():
        short = ABBR.get(key, key[:4].upper())
        pairs.append(f'{short}={_sanitize(str(val))}')

    tag = hashlib.md5(':'.join(pairs).encode()).hexdigest()[:4]
    max_body = config.USSD_CHAR_LIMIT - 10  # reserve for "1/3:xxxx:"
    chunks, cur = [], ''
    for p in pairs:
        test = (cur + ':' + p) if cur else p
        if len(test) <= max_body:
            cur = test
        else:
            chunks.append(cur)
            cur = p
    if cur:
        chunks.append(cur)

    n = len(chunks)
    return [f'{i+1}/{n}:{tag}:{c}' for i, c in enumerate(chunks)]


def decode(chunks: list[str]) -> dict:
    """Reassemble chunks into a dict."""
    ordered = sorted(chunks, key=lambda c: int(c.split('/')[0]))
    parts = []
    for c in ordered:
        sp = c.split(':', 2)
        if len(sp) >= 3:
            parts.append(sp[2])
    full = ':'.join(parts)
    result = {}
    for pair in full.split(':'):
        if '=' in pair:
            k, v = pair.split('=', 1)
            result[ABBR_REV.get(k, k.lower())] = _coerce(v)
    return result


def _sanitize(s: str) -> str:
    return ''.join('_' if c in _EXPENSIVE or ord(c) > 127 else c for c in s)[:50]


def _coerce(v: str):
    try:
        return float(v) if '.' in v else int(v)
    except ValueError:
        return v
