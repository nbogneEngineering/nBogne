"""
Hardware test — run on Raspberry Pi with SIM800C connected.
Tests each modem capability independently.

  python3 tests/test_modem_hw.py
"""

import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from modem import Modem


def run_tests():
    m = Modem()

    print("=" * 50)
    print("nBogne SIM800C Hardware Test")
    print("=" * 50)
    print()

    # ── 1. Open serial port ──────────────────────────────────
    print("[1] Opening modem...")
    try:
        m.open()
        print("    ✓ Serial port open, modem initialized")
    except Exception as e:
        print(f"    ✗ FAILED: {e}")
        print("    Check wiring and config.MODEM_PORT")
        return

    # ── 2. Basic AT ──────────────────────────────────────────
    print("[2] AT command test...")
    resp = m.at('AT')
    if 'OK' in resp:
        print("    ✓ Modem responds to AT")
    else:
        print(f"    ✗ No OK response: {resp.strip()}")
        return

    # ── 3. SIM card ──────────────────────────────────────────
    print("[3] SIM card check...")
    resp = m.at('AT+CPIN?')
    if 'READY' in resp:
        print("    ✓ SIM card ready (no PIN needed)")
    elif 'SIM PIN' in resp:
        print("    ! SIM requires PIN — enter it or use a PIN-free SIM")
    else:
        print(f"    ✗ SIM issue: {resp.strip()}")

    # ── 4. Network registration ──────────────────────────────
    print("[4] Network registration...")
    if m.is_registered():
        print("    ✓ Registered on network")
    else:
        print("    ✗ Not registered — waiting 15s...")
        time.sleep(15)
        if m.is_registered():
            print("    ✓ Now registered")
        else:
            print("    ✗ Still not registered. Check antenna/SIM.")

    # ── 5. Signal strength ───────────────────────────────────
    print("[5] Signal strength...")
    rssi = m.get_rssi()
    dbm = -113 + (2 * rssi) if rssi != 99 else -999
    bars = min(rssi // 6, 5) if rssi != 99 else 0
    print(f"    RSSI: {rssi} ({dbm} dBm) {'█' * bars}{'░' * (5-bars)}")
    if rssi == 99:
        print("    ✗ No signal!")
    elif rssi < 5:
        print("    ! Very weak — check antenna")
    else:
        print("    ✓ Signal OK")

    # ── 6. Operator ──────────────────────────────────────────
    print("[6] Operator...")
    resp = m.at('AT+COPS?')
    print(f"    {resp.strip()}")

    # ── 7. USSD test (carrier balance check) ─────────────────
    print(f"[7] USSD test (dialing {config.CARRIER_BALANCE_CODE if hasattr(config, 'CARRIER_BALANCE_CODE') else '*124#'})...")
    code = getattr(config, 'CARRIER_BALANCE_CODE', '*124#')
    resp = m.ussd_send(code, timeout=15)
    if resp:
        print(f"    Status: {resp['status']}")
        print(f"    Text: {resp['text'][:80]}")
        print("    ✓ USSD working")
        if resp['status'] == 1:
            m.ussd_cancel()
    else:
        print("    ✗ USSD timeout or error")

    # ── 8. GPRS check ────────────────────────────────────────
    print("[8] GPRS attachment...")
    if m.gprs_attached():
        print("    ✓ GPRS attached")
    else:
        print("    ✗ GPRS not attached (USSD still works without it)")

    # ── 9. SMS send test (optional) ──────────────────────────
    print("[9] SMS (skipped — uncomment to test)")
    # Uncomment to test:
    # ok = m.sms_send('+233XXXXXXXXX', 'nBogne test SMS')
    # print(f"    {'✓' if ok else '✗'} SMS send")

    # ── Done ─────────────────────────────────────────────────
    print()
    print("=" * 50)
    print("Hardware test complete")
    print("=" * 50)

    m.close()


if __name__ == '__main__':
    run_tests()
