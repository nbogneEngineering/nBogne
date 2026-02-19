"""
nBogne Transport — Configuration
Edit this file for each facility deployment.
"""

# ── MODEM HARDWARE ───────────────────────────────────────────
MODEM_PORT = '/dev/serial0'       # RPi UART (GPIO 14/15)
MODEM_BAUD = 115200
MODEM_RESET_PIN = 23              # BCM GPIO → SIM800C RST
MODEM_DTR_PIN = 24                # BCM GPIO → SIM800C DTR (sleep control)

# ── CARRIER ──────────────────────────────────────────────────
APN = 'internet'                  # MTN Ghana APN

# ── USSD ─────────────────────────────────────────────────────
USSD_SHORTCODE = '*384*72#'       # Your Africa's Talking shortcode
USSD_TIMEOUT = 20                 # Seconds to wait per exchange
USSD_CHAR_LIMIT = 178             # Safe GSM 7-bit limit per exchange

# ── SMS ──────────────────────────────────────────────────────
SMS_TRIGGER_PREFIX = 'FETCH:'     # Server → device wake-up SMS prefix
SMS_DATA_PREFIX = 'DATA:'         # Device → server SMS data prefix

# ── CENTRAL SERVER ───────────────────────────────────────────
SERVER_URL = 'https://api.nbogne.com'
GPRS_POST_ENDPOINT = '/api/v1/data'
GPRS_TIMEOUT = 30

# Server phone number (for SMS fallback sending)
SERVER_PHONE = '+233XXXXXXXXX'

# ── FACILITY IDENTITY ────────────────────────────────────────
FACILITY_ID = 'GH-CHPS-001'      # Unique per deployment

# ── RETRY ────────────────────────────────────────────────────
RETRY_BASE_SECONDS = 5
RETRY_MAX_SECONDS = 300
RETRY_MAX_ATTEMPTS = 10

# ── WATCHDOG ─────────────────────────────────────────────────
WATCHDOG_INTERVAL = 60            # Health check every 60s
WATCHDOG_MAX_FAILURES = 3         # Reset after 3 consecutive failures
MIN_RSSI = 5                      # Signal floor

# ── SCHEDULER ────────────────────────────────────────────────
SYNC_INTERVAL = 900               # 15 min between scheduled outbox flushes

# ── DATABASE ─────────────────────────────────────────────────
DB_PATH = '/var/lib/nbogne/transport.db'

# ── LOGGING ──────────────────────────────────────────────────
LOG_PATH = '/var/log/nbogne/transport.log'
LOG_LEVEL = 'INFO'
