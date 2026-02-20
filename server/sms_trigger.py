"""
nBogne Server — SMS Trigger
Sends SMS from server to Raspberry Pi devices to trigger immediate USSD sync.
Uses Africa's Talking SMS API.

Usage:
  python server/sms_trigger.py +233549XXXXXX           # Trigger one device
  python server/sms_trigger.py --all                    # Trigger all registered devices
  python server/sms_trigger.py +233549XXXXXX CMD:STATUS # Send remote command
"""

import sys
import os

# pip install africastalking
import africastalking

# ── Config (use environment variables in production) ─────────
AT_USERNAME = os.environ.get('AT_USERNAME', 'sandbox')
AT_API_KEY  = os.environ.get('AT_API_KEY', 'your_api_key_here')

# Set to True for testing with Africa's Talking sandbox
SANDBOX = AT_USERNAME == 'sandbox'

# Registered facility phones (replace with database in production)
FACILITY_PHONES = {
    'GH-CHPS-001': '+233549XXXXXX',
    'GH-CHPS-002': '+233549YYYYYY',
}


def init_at():
    africastalking.initialize(AT_USERNAME, AT_API_KEY)
    return africastalking.SMS


def send_trigger(phone: str, message: str = 'FETCH:sync'):
    """Send SMS trigger to a device."""
    sms = init_at()
    try:
        resp = sms.send(message, [phone])
        recipients = resp.get('SMSMessageData', {}).get('Recipients', [])
        for r in recipients:
            status = r.get('status', '')
            cost = r.get('cost', '')
            print(f"  → {r.get('number')}: {status} ({cost})")
        return True
    except Exception as e:
        print(f"  ERROR: {e}")
        return False


def trigger_all(message: str = 'FETCH:sync'):
    """Send trigger to all registered devices."""
    for fid, phone in FACILITY_PHONES.items():
        print(f"[{fid}] {phone}")
        send_trigger(phone, message)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python sms_trigger.py +233XXXXXXXXX              # Trigger sync")
        print("  python sms_trigger.py +233XXXXXXXXX CMD:STATUS   # Remote command")
        print("  python sms_trigger.py --all                      # Trigger all")
        sys.exit(1)

    if sys.argv[1] == '--all':
        msg = sys.argv[2] if len(sys.argv) > 2 else 'FETCH:sync'
        trigger_all(msg)
    else:
        phone = sys.argv[1]
        msg = sys.argv[2] if len(sys.argv) > 2 else 'FETCH:sync'
        print(f"Sending '{msg}' → {phone}")
        send_trigger(phone, msg)
