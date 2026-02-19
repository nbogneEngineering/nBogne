"""
nBogne Server — USSD Callback Handler
This runs on your cloud VPS (not on the Raspberry Pi).
Africa's Talking POSTs here when a device dials your shortcode.

Handles the multi-step USSD session protocol:
  Step 1: Device dials shortcode → server responds "CON READY|session"
  Step 2: Device sends chunk 1/N → server responds "CON ACK|NEXT"
  ...
  Step N: Device sends last chunk → server responds "END CONFIRMED|TXN:xxxx"

Setup:
  1. pip install flask
  2. Set your Africa's Talking callback URL to: https://yourserver.com/ussd
  3. python3 server/app.py
"""

import uuid
import json
import logging
from datetime import datetime
from flask import Flask, request, jsonify

# In production, replace with your real database/DHIS2 integration
RECEIVED_DATA = {}    # session_id → {chunks: [], facility_id: str, ...}

app = Flask(__name__)
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('nbogne.server')


@app.route('/ussd', methods=['POST'])
def ussd_callback():
    """
    Africa's Talking sends POST with:
      sessionId, phoneNumber, networkCode, serviceCode, text

    'text' contains user's latest input (or all inputs joined by * for full history).
    We respond with a string:
      "CON ..." = keep session open (status 1)
      "END ..." = close session (status 0)
    """
    session_id = request.form.get('sessionId', '')
    phone      = request.form.get('phoneNumber', '')
    text       = request.form.get('text', '')

    log.info(f"USSD [{session_id[:8]}] phone={phone} text={text[:60]}")

    # ── Step 1: First request (text is empty) → send READY ───
    if text == '':
        RECEIVED_DATA[session_id] = {
            'chunks': [],
            'phone': phone,
            'started': datetime.utcnow().isoformat(),
        }
        return f"CON READY|{session_id[:8]}"

    # ── Step 2+: Device is sending data chunks ───────────────
    # Africa's Talking concatenates all exchanges with *
    # The LATEST input is the last segment after splitting by *
    parts = text.split('*')
    latest = parts[-1] if parts else text

    session = RECEIVED_DATA.get(session_id)
    if not session:
        return "END ERROR|NO_SESSION"

    session['chunks'].append(latest)
    log.info(f"  Chunk {len(session['chunks'])}: {latest[:60]}")

    # Parse chunk header to check if this is the last one: "2/2:hash:data"
    is_last = False
    if '/' in latest:
        try:
            idx_total = latest.split(':')[0]  # "2/2"
            idx, total = idx_total.split('/')
            is_last = (idx == total)
        except (ValueError, IndexError):
            pass

    if is_last:
        # All chunks received → process
        txn_id = uuid.uuid4().hex[:8]
        record = _reassemble(session)
        record['txn_id'] = txn_id
        record['received_at'] = datetime.utcnow().isoformat()

        log.info(f"  COMPLETE txn={txn_id} fields={list(record.get('data', {}).keys())}")

        # TODO: Forward to DHIS2 / OpenHIM / your database
        _store_record(record)

        del RECEIVED_DATA[session_id]
        return f"END CONFIRMED|TXN:{txn_id}"

    # More chunks expected
    return "CON ACK|NEXT"


@app.route('/api/v1/data', methods=['POST'])
def gprs_data():
    """
    GPRS HTTP POST endpoint.
    Device sends JSON directly when internet is available.
    """
    data = request.get_json(force=True)
    txn_id = uuid.uuid4().hex[:8]

    log.info(f"GPRS data from {data.get('facility_id')} record={data.get('record_id')} txn={txn_id}")

    _store_record({
        'facility_id': data.get('facility_id'),
        'record_id': data.get('record_id'),
        'data': data.get('data', {}),
        'channel': 'GPRS',
        'rssi': data.get('rssi'),
        'txn_id': txn_id,
        'received_at': datetime.utcnow().isoformat(),
    })

    return jsonify({'status': 'ok', 'txn_id': txn_id}), 201


@app.route('/api/v1/sms', methods=['POST'])
def sms_data():
    """
    SMS webhook endpoint.
    Africa's Talking or Twilio POSTs here when an SMS arrives from a device.
    """
    sender = request.form.get('from', '')
    text   = request.form.get('text', '')

    log.info(f"SMS from {sender}: {text[:60]}")

    if text.startswith('D:'):
        # Parse compact SMS format: D:record_id:facility_id:P=val:T=val:...
        parts = text.split(':')
        record = {
            'record_id': parts[1] if len(parts) > 1 else '',
            'facility_id': parts[2] if len(parts) > 2 else '',
            'channel': 'SMS',
            'data': {},
            'received_at': datetime.utcnow().isoformat(),
        }
        for p in parts[3:]:
            if '=' in p:
                k, v = p.split('=', 1)
                record['data'][k] = v
        _store_record(record)

    return jsonify({'status': 'ok'}), 200


@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'sessions': len(RECEIVED_DATA)})


# ── Internal ─────────────────────────────────────────────────

def _reassemble(session: dict) -> dict:
    """Reassemble USSD chunks into a data dict."""
    from encoding import decode
    try:
        # Filter out non-chunk data (like the initial READY response exchange)
        chunks = [c for c in session['chunks'] if '/' in c.split(':')[0]]
        data = decode(chunks)
    except Exception as e:
        log.error(f"Reassembly error: {e}")
        data = {'_raw_chunks': session['chunks']}

    return {
        'facility_id': data.pop('facility_id', ''),
        'record_id': data.pop('record_id', ''),
        'data': data,
        'channel': 'USSD',
        'phone': session.get('phone', ''),
    }


def _store_record(record: dict):
    """
    Store received record.
    Replace this with your actual database / DHIS2 integration.
    For MVP, we just append to a JSON file.
    """
    import os
    path = os.environ.get('DATA_DIR', '/var/lib/nbogne-server')
    os.makedirs(path, exist_ok=True)
    filepath = os.path.join(path, 'received.jsonl')
    with open(filepath, 'a') as f:
        f.write(json.dumps(record) + '\n')
    log.info(f"Stored → {filepath}")


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
