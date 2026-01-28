# nBogne Adapter

Health data transmission over unreliable networks.

---

## What It Does

nBogne guarantees health data delivery when networks fail. Rural clinics lose broadband constantly — we automatically retry and queue until data gets through.

**Current implementation:** GPRS/HTTP transmission with persistent queue.  
**Coming soon:** SMS fallback, mesh network support.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           FACILITY (Rural Clinic)                           │
│                                                                             │
│   ┌──────────────┐      ┌───────────────────────────────────────────────┐  │
│   │              │      │              nBogne Adapter                   │  │
│   │   OpenMRS    │ HTTP │  ┌─────────┐   ┌─────────┐   ┌────────────┐  │  │
│   │   (Docker)   │─────▶│  │Receiver │──▶│  Queue  │──▶│Transmitter │  │  │
│   │              │ POST │  │ :8081   │   │(SQLite) │   │  (Retry)   │  │  │
│   │   :8080      │ FHIR │  └─────────┘   └─────────┘   └─────┬──────┘  │  │
│   └──────────────┘      │                                    │         │  │
│                         └────────────────────────────────────┼─────────┘  │
│   ┌──────────────┐                                           │            │
│   │  Dashboard   │                                           │            │
│   │  (Streamlit) │                                           │            │
│   │   :8501      │                                           │            │
│   └──────────────┘                                           │            │
└──────────────────────────────────────────────────────────────┼────────────┘
                                                               │
                                                               │ GPRS / 2G
                                                               │ (unreliable)
                                                               │
┌──────────────────────────────────────────────────────────────┼────────────┐
│                          CENTRAL (Regional/National)         │            │
│                                                               ▼            │
│   ┌───────────────────┐      ┌──────────────┐      ┌──────────────────┐  │
│   │  nBogne Mediator  │─────▶│   OpenHIM    │─────▶│  Other Systems   │  │
│   │  (decode/route)   │      │   (log)      │      │  (SHR, Lab...)   │  │
│   │     :5001         │      │   :5000      │      │                  │  │
│   └───────────────────┘      └──────────────┘      └──────────────────┘  │
└───────────────────────────────────────────────────────────────────────────┘
```

---

## Components Explained

### At the Facility (this repo)

| Component | Port | Purpose |
|-----------|------|---------|
| **OpenMRS** | 8080 | EMR system. Stores patient data. Has FHIR API. |
| **nBogne Adapter** | 8081 | Receives FHIR from OpenMRS, queues, transmits to central. |
| **Dashboard** | 8501 | Web UI for health workers to send referrals. |

### At Central (separate deployment)

| Component | Port | Purpose |
|-----------|------|---------|
| **nBogne Mediator** | 5001 | Receives encoded data, decodes, routes to OpenHIM. |
| **OpenHIM** | 5000 | Logs transactions, routes to destination systems. |

---

## Code Structure

```
nbogne-adapter/
│
├── nbogne/                     # CORE LIBRARY
│   ├── wire_format.py         # Binary protocol: 48-byte header + gzip + base64
│   ├── queue.py               # SQLite persistent queue (survives power loss)
│   ├── transmitter.py         # HTTP transmission with exponential backoff
│   ├── receiver.py            # HTTP server receiving FHIR from OpenMRS
│   ├── adapter.py             # Main orchestrator (ties everything together)
│   ├── config.py              # Configuration management
│   └── exceptions.py          # Custom error types
│
├── ui/                         # WEB DASHBOARD (Flask)
│   ├── app.py                 # Flask application
│   └── templates/             # HTML templates
│       ├── base.html
│       ├── index.html
│       ├── patients.html
│       ├── send.html
│       ├── manual.html
│       ├── queue.html
│       └── settings.html
│
├── scripts/                    # CLI TOOLS
│   ├── run_adapter.py         # Start the adapter
│   ├── queue_manager.py       # Inspect/manage queue
│   ├── test_client.py         # Send test messages
│   └── mock_mediator.py       # Fake central server for testing
│
├── config/                     # CONFIGURATION
│   ├── default.yaml           # Default settings
│   ├── local.yaml             # Local development
│   └── docker.yaml            # Docker deployment
│
├── docker-compose.yml          # Deploy adapter + dashboard
├── Dockerfile                  # Adapter container
└── Dockerfile.ui               # Dashboard container
```

---

## Key Code Sections

### 1. Wire Format (`nbogne/wire_format.py`)

Encodes FHIR data for transmission over constrained networks.

```
Original FHIR JSON (5KB)
    ↓ gzip compress (60-80% reduction)
Compressed bytes (1.5KB)
    ↓ base64 encode (SMS-safe)
ASCII string (2KB)
    ↓ prepend 48-byte header
Final message (2KB)
```

**Header structure (48 bytes):**
- Version (2 bytes)
- Message ID (16 bytes, UUID)
- Source facility (8 bytes)
- Destination facility (8 bytes)
- Message type (2 bytes)
- Timestamp (4 bytes)
- Payload length (4 bytes)
- Fragmentation info (4 bytes)

### 2. Persistent Queue (`nbogne/queue.py`)

SQLite database that survives crashes and power outages.

**States:**
```
PENDING → SENDING → ACKED (success)
                  → FAILED → DEAD (after max retries)
```

**Why SQLite?**
- Works without internet
- Survives power loss
- Zero configuration
- Proven in CommCare, ODK (millions of users in Africa)

### 3. Transmitter (`nbogne/transmitter.py`)

Sends data to central server with automatic retry.

**Retry logic (exponential backoff with jitter):**
```
Attempt 1: fail → wait random(0, 3s)
Attempt 2: fail → wait random(0, 6s)
Attempt 3: fail → wait random(0, 12s)
Attempt 4: fail → wait random(0, 24s)
Attempt 5: fail → move to dead letter queue
```

**Timeouts (GPRS-optimized):**
- Connect: 30 seconds (GPRS needs 12-25s to establish)
- Read: 120 seconds (slow networks)

### 4. Receiver (`nbogne/receiver.py`)

HTTP server that OpenMRS sends data to.

**Endpoint:** `POST /fhir`

**Headers:**
- `X-Destination`: Target facility ID (required)
- `X-Priority`: 0-10, higher = more urgent (optional)

**Response:**
```json
{
  "status": "queued",
  "message_id": "550e8400-e29b-41d4-a716-446655440000",
  "queue_id": 1
}
```

---

## Deployment

### Scenario: Two Computers (2G Testing)

**Computer A (Facility):**
- OpenMRS (Docker)
- nBogne Adapter (Docker)
- Dashboard (Docker)
- Connected via 2G modem or throttled network

**Computer B (Central):**
- OpenHIM (Docker)
- nBogne Mediator (Docker)
- Connected via broadband

### Step 1: Setup Central Server (Computer B)

```bash
# Install OpenHIM (separate repo)
# Configure to receive on port 5001
# Note the IP address: e.g., 192.168.1.100
```

### Step 2: Setup Facility (Computer A)

```bash
# Clone this repo
git clone https://github.com/nbogne/nbogne-adapter.git
cd nbogne-adapter

# Edit docker-compose.yml
# Change CENTRAL_SERVER_IP to Computer B's IP
# Change OPENMRS_URL if OpenMRS is on different host

# Start
docker-compose up -d
```

### Step 3: Configure OpenMRS

Option A: **Manual send via Dashboard**
- Open http://localhost:8501
- Search patient, click Send

Option B: **Automatic via OpenMRS subscription**
- Install FHIR2 module in OpenMRS
- Configure outbound subscription to http://adapter:8081/fhir

### Step 4: Test 2G Conditions

Throttle network to simulate 2G:
```bash
# Linux (facility computer)
sudo tc qdisc add dev eth0 root tbf rate 50kbit latency 500ms burst 1540
```

Remove throttle:
```bash
sudo tc qdisc del dev eth0 root
```

---

## Running Without Docker

### Install Dependencies

```bash
pip install -r requirements.txt
pip install -r ui/requirements.txt
```

### Start Adapter

```bash
# Edit config/local.yaml first
python -m scripts.run_adapter --config config/local.yaml
```

### Start Dashboard

```bash
# Set URLs to match your setup
export OPENMRS_URL=http://localhost:8080/openmrs/ws/fhir2/R4
export ADAPTER_URL=http://localhost:8081
export FACILITY_NAME="My Clinic"

# Run with Flask dev server
python -m ui.app

# Or with gunicorn (production)
gunicorn -w 2 -b 0.0.0.0:8501 ui.app:app
```

### Local Testing (No OpenMRS)

```bash
# Terminal 1: Start mock central server
python -m scripts.mock_mediator --port 9000

# Terminal 2: Start adapter
python -m scripts.run_adapter --config config/local.yaml

# Terminal 3: Start dashboard
python -m ui.app

# Go to http://localhost:8501/manual to send test data
```

---

## Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `NBOGNE_FACILITY_ID` | Facility identifier (max 8 chars) | FAC-001 |
| `NBOGNE_FACILITY_NAME` | Display name | Health Facility |
| `NBOGNE_MEDIATOR_ENDPOINT` | Central server URL | http://localhost:5001/gsm/inbound |
| `NBOGNE_LOG_LEVEL` | DEBUG, INFO, WARNING, ERROR | INFO |
| `OPENMRS_URL` | OpenMRS FHIR endpoint (for dashboard) | http://localhost:8080/openmrs/ws/fhir2/R4 |
| `ADAPTER_URL` | Adapter endpoint (for dashboard) | http://localhost:8081 |

---

## Testing

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_queue.py -v

# Run with coverage
pytest --cov=nbogne
```

---

## Troubleshooting

### Dashboard can't connect to OpenMRS

1. Check OpenMRS is running: `curl http://localhost:8080/openmrs`
2. Check FHIR module installed: `curl http://localhost:8080/openmrs/ws/fhir2/R4/Patient`
3. Verify URL in dashboard sidebar matches your setup

### Dashboard can't connect to Adapter

1. Check adapter is running: `curl http://localhost:8081/health`
2. If using Docker, ensure containers are on same network
3. Check logs: `docker logs nbogne-adapter`

### Queue growing but not draining

1. Check mediator endpoint is correct in config
2. Check central server is reachable: `curl http://CENTRAL_IP:5001/health`
3. Check logs for transmission errors: `tail -f logs/nbogne.log`

### Messages failing repeatedly

1. Check adapter stats: `curl http://localhost:8081/stats`
2. Retry failed messages: `python -m scripts.queue_manager retry --all-failed`
3. Check dead letter queue: `python -m scripts.queue_manager list --status dead`

---

## License

MIT

---

## Contact

tsteve@nbogne.com | https://nbogne.com
