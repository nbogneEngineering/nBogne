"""
nBogne Transport — Multi-Channel Sender
Tries GPRS → USSD → SMS in order. Handles chunked USSD sessions.
"""

import json
import time
import logging
import config
import db
from modem import Modem
from encoding import encode

log = logging.getLogger('nbogne.transport')


class Transport:

    def __init__(self, modem: Modem):
        self.modem = modem

    def send_record(self, record_id: str, payload: dict) -> bool:
        """Try all channels. Returns True on first success."""
        db.mark_sending(record_id)
        rssi = self.modem.get_rssi()

        for method in (self._gprs, self._ussd, self._sms):
            if method(record_id, payload, rssi):
                return True

        db.mark_failed(record_id, 'all_channels')
        state = db.get_state()
        db.update_state(consec_fails=state.get('consec_fails', 0) + 1)
        return False

    # ── GPRS ─────────────────────────────────────────────────

    def _gprs(self, rid, payload, rssi):
        if not self.modem.gprs_attached():
            db.update_state(gprs_ok=0)
            return False

        log.info(f"[{rid}] GPRS...")
        t0 = time.time()
        body = json.dumps({
            'facility_id': config.FACILITY_ID,
            'record_id': rid,
            'data': payload, 'channel': 'GPRS', 'rssi': rssi
        })
        url = config.SERVER_URL + config.GPRS_POST_ENDPOINT
        status, resp = self.modem.http_post(url, body)
        ms = int((time.time() - t0) * 1000)

        if status in (200, 201):
            log.info(f"[{rid}] GPRS OK ({ms}ms)")
            db.mark_sent(rid, 'GPRS', resp[:60])
            db.log_tx(rid, 'GPRS', True, rssi=rssi, duration_ms=ms)
            db.update_state(gprs_ok=1, last_success=_now(), last_channel='GPRS', consec_fails=0)
            return True

        log.warning(f"[{rid}] GPRS fail: {status}")
        db.log_tx(rid, 'GPRS', False, error=str(status), rssi=rssi, duration_ms=ms)
        db.update_state(gprs_ok=0)
        return False

    # ── USSD ─────────────────────────────────────────────────

    def _ussd(self, rid, payload, rssi):
        if rssi < config.MIN_RSSI or rssi == 99:
            return False

        log.info(f"[{rid}] USSD...")
        t0 = time.time()
        chunks = encode(payload, record_id=rid)

        self.modem.ussd_cancel()
        time.sleep(0.3)

        # 1) Dial shortcode → expect server READY
        resp = self.modem.ussd_send(config.USSD_SHORTCODE)
        if not resp or resp['status'] == 2:
            self._ussd_fail(rid, 'init_fail', rssi, t0)
            return False

        # 2) Send each chunk → expect ACK / CONFIRMED
        for i, chunk in enumerate(chunks):
            if len(chunk) > config.USSD_CHAR_LIMIT:
                log.error(f"Chunk {i} too long ({len(chunk)})")
                self.modem.ussd_cancel()
                return False

            resp = self.modem.ussd_reply(chunk)
            if not resp:
                self._ussd_fail(rid, f'timeout_chunk{i}', rssi, t0)
                return False
            if resp['status'] == 2:
                self._ussd_fail(rid, f'net_term_chunk{i}', rssi, t0)
                return False

            text = resp.get('text', '')
            if 'NACK' in text or 'ERR' in text:
                self.modem.ussd_cancel()
                self._ussd_fail(rid, f'nack:{text[:20]}', rssi, t0)
                return False

            # Last chunk → expect CONFIRMED
            if i == len(chunks) - 1 and ('CONFIRMED' in text or 'ACK' in text):
                ms = int((time.time() - t0) * 1000)
                ack = text.split('TXN:')[1][:8] if 'TXN:' in text else text[:20]
                log.info(f"[{rid}] USSD OK ({len(chunks)} chunks, {ms}ms)")
                db.mark_sent(rid, 'USSD', ack)
                db.log_tx(rid, 'USSD', True, rssi=rssi, duration_ms=ms)
                db.update_state(last_success=_now(), last_channel='USSD', consec_fails=0)
                return True

        self._ussd_fail(rid, 'no_confirm', rssi, t0)
        return False

    def _ussd_fail(self, rid, error, rssi, t0):
        ms = int((time.time() - t0) * 1000)
        log.warning(f"[{rid}] USSD fail: {error}")
        db.log_tx(rid, 'USSD', False, error=error, rssi=rssi, duration_ms=ms)

    # ── SMS ──────────────────────────────────────────────────

    def _sms(self, rid, payload, rssi):
        log.info(f"[{rid}] SMS fallback...")
        t0 = time.time()
        # Compact SMS: essential fields only
        parts = [f"D:{rid}:{config.FACILITY_ID}"]
        for k in ('patient_id', 'temperature', 'heart_rate', 'blood_pressure', 'spo2', 'diagnosis'):
            if k in payload:
                short = {'patient_id':'P','temperature':'T','heart_rate':'HR',
                         'blood_pressure':'BP','spo2':'O2','diagnosis':'DX'}.get(k, k[:2])
                parts.append(f"{short}={payload[k]}")
        body = ':'.join(parts)[:160]

        ok = self.modem.sms_send(config.SERVER_PHONE, body)
        ms = int((time.time() - t0) * 1000)
        if ok:
            log.info(f"[{rid}] SMS OK ({ms}ms)")
            db.mark_sent(rid, 'SMS', 'sms_queued')
            db.log_tx(rid, 'SMS', True, rssi=rssi, duration_ms=ms)
            db.update_state(last_success=_now(), last_channel='SMS', consec_fails=0)
        else:
            db.log_tx(rid, 'SMS', False, error='send_fail', rssi=rssi, duration_ms=ms)
        return ok

    # ── Batch ────────────────────────────────────────────────

    def process_outbox(self, limit: int = 5) -> int:
        pending = db.get_pending(limit)
        if not pending:
            return 0
        log.info(f"Outbox: {len(pending)} records")
        sent = 0
        for rec in pending:
            try:
                payload = json.loads(rec['payload'])
                if self.send_record(rec['record_id'], payload):
                    sent += 1
                time.sleep(1)
            except Exception as e:
                log.error(f"Send error {rec['record_id']}: {e}")
                db.mark_failed(rec['record_id'], str(e))
        return sent


def _now():
    return time.strftime('%Y-%m-%dT%H:%M:%S')
