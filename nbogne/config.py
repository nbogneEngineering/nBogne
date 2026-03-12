"""
nBogne Configuration
All settings in one place. Edit this file per deployment.
"""
import os
from pathlib import Path

# === PATHS ===
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "nbogne.db"
DICT_PATH = DATA_DIR / "fhir.zstd_dict"
TEMPLATES_PATH = DATA_DIR / "templates.json"

# === SMS / MODEM ===
MODEM_PORT = os.getenv("NBOGNE_MODEM_PORT", "/dev/ttyUSB0")  # USB modem device
DESTINATION_NUMBER = os.getenv("NBOGNE_DEST_NUMBER", "+233000000000")  # Central server modem number
FACILITY_NUMBER = os.getenv("NBOGNE_FACILITY_NUMBER", "+233000000001")  # This facility's modem number
SMS_MAX_SEGMENTS = 6  # Max concatenated SMS segments per transmission
SMS_BINARY_BYTES_PER_SEGMENT = 134  # Usable bytes per segment (140 - 6 UDH)
SMS_MAX_PAYLOAD = SMS_MAX_SEGMENTS * SMS_BINARY_BYTES_PER_SEGMENT  # ~804 bytes

# === COMPRESSION ===
ZSTD_COMPRESSION_LEVEL = 19  # High compression (1-22)
ZSTD_DICT_SIZE = 110000  # ~100KB dictionary

# === ENCRYPTION ===
# In production, these come from secure key exchange during setup.
# For testing, using static keys. CHANGE THESE.
L1_KEY = os.getenv("NBOGNE_L1_KEY", "0" * 64)  # 256-bit hex key (E2EE)
L2_KEY = os.getenv("NBOGNE_L2_KEY", "1" * 64)  # 256-bit hex key (transport)

# === QUEUE / RETRY ===
MAX_RETRIES = 5
RETRY_INTERVAL_SECONDS = 3  # Between retries
QUEUE_CHECK_INTERVAL = 1  # Seconds between queue checks

# === WIRE PROTOCOL ===
WIRE_MAGIC = b'\x6e\x42'  # "nB"
WIRE_VERSION = 1

# === OPENHIM ===
OPENHIM_URL = os.getenv("NBOGNE_OPENHIM_URL", "http://localhost:5001")
OPENHIM_USER = os.getenv("NBOGNE_OPENHIM_USER", "root@openhim.org")
OPENHIM_PASS = os.getenv("NBOGNE_OPENHIM_PASS", "password")

# === DHIS2 ===
DHIS2_URL = os.getenv("NBOGNE_DHIS2_URL", "http://localhost:8080/api")
DHIS2_USER = os.getenv("NBOGNE_DHIS2_USER", "admin")
DHIS2_PASS = os.getenv("NBOGNE_DHIS2_PASS", "district")

# === LOGGING ===
LOG_LEVEL = os.getenv("NBOGNE_LOG_LEVEL", "INFO")
