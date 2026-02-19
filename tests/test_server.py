"""
Test the server USSD callback handler locally.
Simulates what Africa's Talking sends when a device dials your shortcode.

  python3 tests/test_server.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'server'))

from app import app


def test_full_ussd_session():
    """Simulate a complete 2-chunk USSD data upload."""
    client = app.test_client()

    session_id = 'test-session-001'
    phone = '+233549000000'
    service = '*384*72#'

    # Step 1: Device dials shortcode (empty text)
    r = client.post('/ussd', data={
        'sessionId': session_id, 'phoneNumber': phone,
        'serviceCode': service, 'text': ''
    })
    body = r.data.decode()
    assert body.startswith('CON READY'), f"Expected CON READY, got: {body}"
    print(f"Step 1 ✓  Server: {body}")

    # Step 2: Device sends chunk 1/2
    chunk1 = '1/2:a3f1:RID=test1:P=GH42:T=36.5:HR=72:BP=120/80:O2=98:FID=GH-CHPS-001'
    r = client.post('/ussd', data={
        'sessionId': session_id, 'phoneNumber': phone,
        'serviceCode': service, 'text': chunk1
    })
    body = r.data.decode()
    assert 'ACK' in body, f"Expected ACK, got: {body}"
    print(f"Step 2 ✓  Server: {body}")

    # Step 3: Device sends chunk 2/2
    chunk2 = '2/2:a3f1:DX=malaria_neg:RX=artemether:VT=OPD:TS=250219143022'
    # Africa's Talking concatenates all inputs with *
    full_text = f"{chunk1}*{chunk2}"
    r = client.post('/ussd', data={
        'sessionId': session_id, 'phoneNumber': phone,
        'serviceCode': service, 'text': full_text
    })
    body = r.data.decode()
    assert 'CONFIRMED' in body, f"Expected CONFIRMED, got: {body}"
    assert 'TXN:' in body
    print(f"Step 3 ✓  Server: {body}")

    print("\nFull USSD session test passed!")


def test_gprs_endpoint():
    """Test the HTTP POST endpoint (GPRS channel)."""
    client = app.test_client()

    r = client.post('/api/v1/data',
        json={
            'facility_id': 'GH-CHPS-001',
            'record_id': 'gprs-test-1',
            'data': {'temperature': 37.2, 'heart_rate': 80},
            'channel': 'GPRS',
            'rssi': 15
        }
    )
    assert r.status_code == 201
    data = r.get_json()
    assert data['status'] == 'ok'
    assert 'txn_id' in data
    print(f"GPRS test ✓  txn_id={data['txn_id']}")


def test_health():
    client = app.test_client()
    r = client.get('/health')
    assert r.status_code == 200
    print(f"Health  ✓  {r.get_json()}")


if __name__ == '__main__':
    test_health()
    test_gprs_endpoint()
    test_full_ussd_session()
    print("\n=== All server tests passed ===")
