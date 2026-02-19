# nBogne Transport — Health Data Over Cellular

SMS-triggered USSD transport for health facility data in connectivity-challenged areas.
Runs on Raspberry Pi + SIM800C GSM modem at each facility. Sends data over GPRS → USSD → SMS
(automatic fallback). Server receives via Africa's Talking USSD callback + HTTP API.

---

## How It Works

```
┌─────────────────────┐       SMS "FETCH:sync"       ┌──────────────────────┐
│   CENTRAL SERVER    │ ──────────────────────────►   │   RASPBERRY PI       │
│                     │                               │   + SIM800C          │
│  Flask app receives │   ◄── MO-USSD session ──────  │                      │
│  USSD callbacks     │       (device dials *384*72#) │  Daemon detects SMS  │
│  from Africa's      │                               │  → dials shortcode   │
│  Talking            │   ◄── GPRS HTTP POST ───────  │  → sends health data │
│                     │       (when internet works)   │    in USSD chunks    │
│  Also receives:     │                               │                      │
│  - GPRS HTTP POST   │   ◄── SMS data ────────────   │  Fallback: sends     │
│  - SMS webhook      │       (last resort)           │  compact SMS         │
└─────────────────────┘                               └──────────────────────┘
```

**The core pattern**: Your server sends a wake-up SMS → the Pi daemon detects it →
initiates a USSD session to your Africa's Talking shortcode → server receives data
via HTTP callback → responds with ACK. This gives you **server-push semantics**
using only mobile-originated protocols.

**Why not just GPRS?** GPRS needs a data connection that's often unavailable.
USSD runs on the GSM signaling channel (SDCCH) — it works with bare 2G signal,
no data plan needed. SMS is the final fallback.

**Why not MT-USSD (server-initiated)?** MNOs don't expose it to third parties.
SMS trigger + MO-USSD achieves the same result with technology available today.

---

## Hardware Required

### Shopping List

| Item | Model | Price (approx) | Notes |
|------|-------|-----------------|-------|
| Single-board computer | Raspberry Pi Zero 2 W | $15-20 | Or Pi 3B/4 for dev |
| GSM modem module | SIM800C (Waveshare) | $15-25 | UART version preferred |
| SIM card | MTN Ghana prepaid | $1-2 | PIN-free, with airtime |
| Antenna | GSM/GPRS antenna | $2-5 | Usually included with module |
| Power supply | 5V 2.5A USB-C/Micro | $5-10 | Must supply ≥2A (SIM800C bursts) |
| MicroSD card | 16GB+ Class 10 | $5-8 | For Raspberry Pi OS |
| Jumper wires | Female-to-female | $2-3 | 6 wires needed |

**Total: ~$45-75 per facility unit**

### Why SIM800C?

The Waveshare SIM800C GSM/GPRS HAT is purpose-built for Raspberry Pi. It sits directly
on the GPIO header. If you buy the standalone SIM800C module, you wire it manually
(see below). The SIM800C supports USSD Phase 2 (multi-step sessions), SMS, GPRS,
and has built-in HTTP/FTP stack — no PPP needed.

---

## Wiring

### Option A: Waveshare SIM800C HAT (easiest)

Just plug the HAT onto the Pi's 40-pin header. No wiring needed.
The HAT connects TXD/RXD to GPIO 14/15 and provides its own voltage regulator.

### Option B: Standalone SIM800C Module

```
Raspberry Pi              SIM800C Module
─────────────             ──────────────
GPIO 14 (TXD) ──────────► RXD
GPIO 15 (RXD) ◄────────── TXD
GPIO 23       ──────────► RST  (reset control)
GPIO 24       ──────────► DTR  (sleep control, optional)
GND           ──────────── GND
5V            ──────────── VCC  (⚠ SIM800C needs 3.4-4.4V,
                                  use module's onboard regulator
                                  or a buck converter. Do NOT
                                  connect 5V directly to bare chip)
```

**Voltage warning**: The SIM800C chip runs at 3.4-4.4V (typ 4.0V) and draws
up to 2A during transmission bursts. The Waveshare module has a regulator.
If using a bare module, you need a 5V→4V buck converter rated for 2A.
The Pi's 3.3V GPIO is fine for TXD/RXD since SIM800C accepts 2.8V logic.

### SIM Card

1. Insert a **PIN-free** SIM (or disable PIN: put SIM in a phone, go to
   Settings → Security → SIM Lock → disable)
2. Ensure the SIM has **airtime credit** (USSD costs ~GH₵0.01/session on MTN)
3. Nano-SIM for Waveshare HAT, or whatever your module takes

### Antenna

Screw the GSM antenna into the SMA/U.FL connector on the module.
**Without an antenna, the module may not register on the network.**

---

## Software Setup

### Raspberry Pi (device side)

```bash
# 1. Flash Raspberry Pi OS Lite (64-bit) to SD card
# 2. Enable SSH, set WiFi for initial setup
# 3. SSH into the Pi, then:

# Clone the project
git clone https://github.com/your-org/nbogne-transport.git
cd nbogne-transport

# Run installer (configures UART, installs dependencies, creates systemd service)
sudo bash scripts/install.sh

# Edit config for your facility
sudo nano /opt/nbogne/config.py
# Set: FACILITY_ID, USSD_SHORTCODE, SERVER_URL, SERVER_PHONE

# Reboot (required for UART changes)
sudo reboot

# After reboot, test hardware:
cd /opt/nbogne
python3 tests/test_modem_hw.py

# Start the daemon
sudo systemctl start nbogne
sudo journalctl -u nbogne -f   # Watch logs
```

### Central Server (cloud VPS)

```bash
# On your server (Ubuntu VPS, Heroku, Railway, etc.)
pip install flask africastalking

# Start the USSD callback server
cd server
python3 app.py
# Runs on port 5000

# For production, use gunicorn:
pip install gunicorn
gunicorn -w 2 -b 0.0.0.0:5000 app:app
```

### Africa's Talking Setup

1. Create account at [africastalking.com](https://africastalking.com)
2. Get a **USSD shortcode** for Ghana (sandbox is free for testing)
3. Set callback URL: `https://yourserver.com/ussd`
4. Set SMS callback URL: `https://yourserver.com/api/v1/sms`
5. Note your API key for the SMS trigger sender

---

## File Structure

```
nbogne-transport/
├── config.py          ← All settings (edit per facility)
├── main.py            ← Daemon entry point (runs on Pi)
├── modem.py           ← SIM800C AT commands (USSD, SMS, GPRS, reset)
├── encoding.py        ← Pack health data into USSD-safe chunks
├── transport.py       ← Multi-channel sender (GPRS→USSD→SMS fallback)
├── watchdog.py        ← Background modem health monitor
├── db.py              ← SQLite outbox queue + transaction log
├── requirements.txt
│
├── server/
│   ├── app.py         ← USSD callback + GPRS endpoint (runs on cloud)
│   └── sms_trigger.py ← Send wake-up SMS to devices from server
│
├── tests/
│   ├── test_encoding.py   ← Unit tests (no hardware needed)
│   ├── test_modem_hw.py   ← Hardware tests (run on Pi)
│   └── test_server.py     ← Server callback tests (no hardware needed)
│
└── scripts/
    ├── install.sh     ← Raspberry Pi setup script
    └── nbogne.service ← systemd service file
```

---

## Testing Guide

### Phase 1: No hardware needed (laptop/desktop)

```bash
# 1. Encoding tests
python3 tests/test_encoding.py
# or: python3 -m pytest tests/test_encoding.py -v

# 2. Server callback tests
python3 tests/test_server.py

# 3. Start server locally and test with curl
python3 server/app.py &

# Simulate USSD session start
curl -X POST http://localhost:5000/ussd \
  -d "sessionId=test1&phoneNumber=+233549000000&text="

# Simulate chunk 1
curl -X POST http://localhost:5000/ussd \
  -d "sessionId=test1&phoneNumber=+233549000000&text=1/2:a3f1:RID=t1:P=GH42:T=36.5"

# Simulate chunk 2 (Africa's Talking concatenates with *)
curl -X POST http://localhost:5000/ussd \
  -d "sessionId=test1&phoneNumber=+233549000000&text=1/2:a3f1:RID=t1:P=GH42:T=36.5*2/2:a3f1:DX=malaria"

# Test GPRS endpoint
curl -X POST http://localhost:5000/api/v1/data \
  -H "Content-Type: application/json" \
  -d '{"facility_id":"TEST","record_id":"r1","data":{"temperature":36.5}}'
```

### Phase 2: Hardware test (on Raspberry Pi)

```bash
# After install.sh and reboot:

# Test modem hardware (signal, USSD, SMS)
python3 tests/test_modem_hw.py

# Add a test record and check status
python3 main.py --enqueue
python3 main.py --status

# Start daemon in foreground to watch it work
python3 main.py
```

### Phase 3: End-to-end (Pi ↔ Server)

```bash
# 1. Server running on your VPS with Africa's Talking callback configured
# 2. Pi running daemon with correct shortcode in config

# On the Pi: add a record
python3 main.py --enqueue

# Watch Pi logs
sudo journalctl -u nbogne -f

# On server: watch received data
tail -f /var/lib/nbogne-server/received.jsonl

# Force immediate sync from server side (send SMS trigger)
python3 server/sms_trigger.py +233549XXXXXX
```

### Africa's Talking Sandbox (free testing)

1. Go to [simulator.africastalking.com](https://simulator.africastalking.com)
2. Enter a test phone number
3. Dial your sandbox shortcode
4. The simulator shows your server's CON/END responses
5. This tests your **server logic** without needing real hardware

---

## Data Flow Detail

### 1. Health record enters the system

A health worker enters data (or an EHR system pushes it) into the local SQLite outbox:

```python
import db
db.enqueue({
    'patient_id': 'GH-PAT-042',
    'temperature': 36.5,
    'heart_rate': 72,
    'blood_pressure': '120/80',
    'spo2': 98,
    'diagnosis': 'routine_checkup',
})
```

### 2. Transport tries GPRS first

If GPRS is available (SIM800C reports `AT+CGATT: 1`), the record is JSON-encoded
and HTTP POSTed to the server using SIM800C's built-in HTTP stack. No PPP session
needed — the `AT+HTTP*` commands handle everything internally.

### 3. GPRS fails → USSD

The encoding module packs the record into GSM 7-bit safe chunks of ≤178 characters.
The daemon dials your Africa's Talking shortcode. Africa's Talking POSTs to your
server. Your server responds with "CON READY". The daemon sends each chunk as a
USSD reply. Server ACKs each one. Last chunk gets "END CONFIRMED|TXN:xxxx".

A typical 2-chunk session takes 8-15 seconds.

### 4. USSD fails → SMS

Essential fields are packed into a 160-character SMS and sent to the server's phone
number. Africa's Talking (or Twilio) forwards it to your server's SMS webhook.

### 5. Everything fails → Retry

The record stays in the SQLite outbox with exponential backoff. The watchdog monitors
modem health. If the modem hangs, it gets a hardware reset via the GPIO RST pin.
The daemon retries up to 10 times with increasing delays (5s → 10s → 20s → ... → 5min max).

### 6. SMS trigger (server-push)

When the server needs data NOW (disease outbreak alert, end-of-day reporting deadline),
it sends an SMS: `FETCH:sync`. The Pi daemon sees this and immediately flushes its outbox.

---

## Remote Management

Send these SMS commands to the device's phone number:

| SMS body | Action |
|----------|--------|
| `FETCH:sync` | Immediately flush outbox |
| `CMD:STATUS` | Device replies with signal/pending/fail count |
| `CMD:RESET` | Hardware reset the modem |

---

## Production Checklist

- [ ] SIM card: PIN disabled, has airtime, auto-renew data bundle
- [ ] config.py: FACILITY_ID unique, USSD_SHORTCODE correct, SERVER_URL reachable
- [ ] Antenna: connected and positioned (near window if indoors)
- [ ] Power: reliable supply (consider USB battery backup for outages)
- [ ] test_modem_hw.py: all checks pass
- [ ] Server: USSD callback URL configured in Africa's Talking dashboard
- [ ] Server: SMS webhook URL configured
- [ ] End-to-end: enqueue → transmit → received.jsonl confirmed

---

## Cost Per Facility

| Item | Monthly cost |
|------|-------------|
| SIM airtime (MTN Ghana) | GH₵5-15 (~$0.40-$1.20) |
| USSD sessions (~300/month) | ~GH₵3 (~$0.25) |
| SMS fallback (~20/month) | ~GH₵1 (~$0.08) |
| Africa's Talking USSD | $10/month (shortcode) |
| Server hosting (shared) | $5-10/month (split across facilities) |
| **Total per facility** | **~$1-3/month** (excl. shared server) |

Hardware is a one-time ~$50-75 cost per facility.
