"""
Tests for encoding module. Run anywhere — no hardware needed.

  python -m pytest tests/test_encoding.py -v
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from encoding import encode, decode


def test_single_chunk():
    """Small record fits in one USSD exchange."""
    data = {'patient_id': 'GH42', 'temperature': 36.5, 'heart_rate': 72}
    chunks = encode(data, record_id='abc1')
    assert len(chunks) == 1
    assert chunks[0].startswith('1/1:')
    assert 'RID=abc1' in chunks[0]
    assert 'T=36.5' in chunks[0]
    assert len(chunks[0]) <= 178


def test_multi_chunk():
    """Large record splits across multiple exchanges."""
    data = {
        'patient_id': 'GH-LONG-ID-12345',
        'temperature': 36.5, 'heart_rate': 72, 'blood_pressure': '120/80',
        'spo2': 98, 'weight': 72.5, 'height': 168,
        'fasting_blood_sugar': 5.4, 'hemoglobin': 12.1,
        'platelets': 245, 'wbc': 7.2, 'rbc': 4.8, 'creatinine': 0.9,
        'diagnosis': 'malaria_negative_routine_antenatal_visit_week_28',
        'prescription': 'iron_folate_sp_ipt_llin',
        'notes': 'patient_stable_vitals_normal_fetal_heartbeat_present',
        'visit_type': 'ANC',
    }
    chunks = encode(data, record_id='big1')
    assert len(chunks) >= 2
    for c in chunks:
        assert len(c) <= 178, f"Chunk too long: {len(c)} chars"


def test_roundtrip():
    """Encode then decode should preserve data."""
    data = {
        'patient_id': 'GH42',
        'temperature': 36.5,
        'heart_rate': 72,
        'blood_pressure': '120/80',
        'spo2': 98,
    }
    chunks = encode(data, record_id='rt01')
    result = decode(chunks)
    assert result['patient_id'] == 'GH42'
    assert result['temperature'] == 36.5
    assert result['heart_rate'] == 72
    assert result['blood_pressure'] == '120/80'
    assert result['spo2'] == 98
    assert result['record_id'] == 'rt01'


def test_gsm_safe_chars():
    """Expensive GSM 7-bit chars get sanitized."""
    data = {'notes': 'test{with}brackets[and]backslash\\tilde~'}
    chunks = encode(data)
    for c in chunks:
        for ch in '{}[]\\~^€':
            assert ch not in c, f"Dangerous char '{ch}' found in: {c}"


def test_empty_record():
    """Empty dict gets facility_id and timestamp added."""
    chunks = encode({})
    assert len(chunks) >= 1
    text = chunks[0]
    assert 'FID=' in text
    assert 'TS=' in text


if __name__ == '__main__':
    test_single_chunk()
    test_multi_chunk()
    test_roundtrip()
    test_gsm_safe_chars()
    test_empty_record()
    print("All encoding tests passed!")
