#!/usr/bin/env python3
"""
nBogne Transport — Main Daemon
Runs on Raspberry Pi at each health facility.

Loop:
  1. Check for incoming SMS triggers from server
  2. If trigger received → immediately process outbox via USSD
  3. On schedule (every SYNC_INTERVAL) → process outbox via best channel
  4. Watchdog runs in background thread checking modem health

Usage:
  python3 main.py                    # Run daemon
  python3 main.py --enqueue          # Add test record to outbox
  python3 main.py --status           # Print device state + outbox count
"""

import sys
import time
import json
import signal
import logging
from pathlib import Path

import config
import db
from modem import Modem
from transport import Transport
from watchdog import Watchdog


# ── Logging Setup ────────────────────────────────────────────

def setup_logging():
    Path(config.LOG_PATH).parent.mkdir(parents=True, exist_ok=True)
    fmt = '%(asctime)s %(name)-18s %(levelname)-5s %(message)s'
    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL),
        format=fmt,
        handlers=[
            logging.FileHandler(config.LOG_PATH),
            logging.StreamHandler()
        ]
    )

log = logging.getLogger('nbogne.main')


# ── SMS Trigger Handler ─────────────────────────────────────

def handle_incoming_sms(modem: Modem, transport: Transport):
    """Check for SMS from server. If FETCH trigger → flush outbox now."""
    indices = modem.check_sms()
    for idx in indices:
        sms = modem.sms_read(idx)
        modem.sms_delete(idx)
        if not sms:
            continue

        body = sms['body']
        log.info(f"SMS from {sms['sender']}: {body[:40]}")

        if body.startswith(config.SMS_TRIGGER_PREFIX):
            # Server is asking us to sync now
            log.info("Server trigger → flushing outbox")
            transport.process_outbox(limit=5)

        elif body.startswith('CMD:'):
            # Simple remote commands
            cmd = body[4:].strip().upper()
            if cmd == 'STATUS':
                state = db.get_state()
                pending = db.pending_count()
                modem.sms_send(sms['sender'],
                    f"FID:{config.FACILITY_ID} RSSI:{state.get('rssi',0)} "
                    f"PEND:{pending} FAILS:{state.get('consec_fails',0)}")
            elif cmd == 'RESET':
                modem.hardware_reset()


# ── Main Loop ────────────────────────────────────────────────

def daemon_loop():
    setup_logging()
    log.info("=" * 50)
    log.info(f"nBogne Transport starting — {config.FACILITY_ID}")
    log.info("=" * 50)

    # Initialize
    modem = Modem()
    modem.open()
    transport = Transport(modem)
    dog = Watchdog(modem)
    dog.start()

    # Graceful shutdown
    running = True
    def on_signal(sig, frame):
        nonlocal running
        log.info(f"Signal {sig} received, shutting down...")
        running = False
    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)

    last_sync = 0

    log.info(f"Entering main loop (sync every {config.SYNC_INTERVAL}s)")

    while running:
        try:
            # 1) Check for incoming SMS triggers
            handle_incoming_sms(modem, transport)

            # 2) Scheduled outbox flush
            now = time.time()
            if now - last_sync >= config.SYNC_INTERVAL:
                pending = db.pending_count()
                if pending > 0:
                    log.info(f"Scheduled sync: {pending} records pending")
                    transport.process_outbox(limit=5)
                last_sync = now

            # 3) Sleep briefly (keep responsive to SMS)
            time.sleep(2)

        except KeyboardInterrupt:
            break
        except Exception as e:
            log.error(f"Main loop error: {e}", exc_info=True)
            time.sleep(10)

    # Cleanup
    dog.stop()
    modem.close()
    log.info("Daemon stopped")


# ── CLI Commands ─────────────────────────────────────────────

def cmd_enqueue():
    """Add a sample health record to the outbox for testing."""
    sample = {
        'patient_id': 'GH-TEST-001',
        'temperature': 36.8,
        'heart_rate': 78,
        'blood_pressure': '125/82',
        'spo2': 97,
        'weight': 72.5,
        'diagnosis': 'routine_checkup',
        'visit_type': 'OPD',
    }
    rid = db.enqueue(sample)
    print(f"Enqueued record: {rid}")
    print(f"Total pending: {db.pending_count()}")


def cmd_status():
    """Print device state and outbox summary."""
    state = db.get_state()
    pending = db.pending_count()
    print(f"\n  Facility:     {config.FACILITY_ID}")
    print(f"  RSSI:         {state.get('rssi', '?')}")
    print(f"  Registered:   {'Yes' if state.get('registered') else 'No'}")
    print(f"  GPRS:         {'OK' if state.get('gprs_ok') else 'No'}")
    print(f"  Last success: {state.get('last_success', 'never')}")
    print(f"  Last channel: {state.get('last_channel', 'none')}")
    print(f"  Consec fails: {state.get('consec_fails', 0)}")
    print(f"  Boot count:   {state.get('boot_count', 0)}")
    print(f"  Pending:      {pending}")
    print()


# ── Entry Point ──────────────────────────────────────────────

if __name__ == '__main__':
    if '--enqueue' in sys.argv:
        cmd_enqueue()
    elif '--status' in sys.argv:
        cmd_status()
    else:
        daemon_loop()
