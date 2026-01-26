# nBogne Adapter

**Reliable health data transmission over GPRS/2G networks for African health facilities.**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Features](#features)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Wire Format Protocol](#wire-format-protocol)
- [API Reference](#api-reference)
- [Integration Guide](#integration-guide)
- [Deployment](#deployment)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)

---

## Overview

nBogne Adapter is a transport layer designed to reliably transmit health data (FHIR bundles) over unreliable 2G/GPRS networks commonly found in rural African health facilities. It bridges the gap between local Electronic Medical Record (EMR) systems and central Health Information Exchanges (HIE) by implementing proven store-and-forward patterns.

### The Problem

Rural health facilities often have:
- **Unreliable GPRS connectivity** (20-50 kbps, frequent dropouts)
- **Power outages** (data loss risk)
- **Limited technical expertise** (needs to "just work")
- **Critical health data** (referrals, lab results) that must not be lost

### The Solution

nBogne Adapter provides:
- **SQLite-backed persistent queue** - Messages survive power failures
- **Automatic retry with exponential backoff** - Handles network instability
- **Compression** - 60-80% bandwidth reduction
- **Simple HTTP interface** - Easy EMR integration

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        HEALTH FACILITY                              │
│                                                                     │
│  ┌─────────────┐        ┌────────────────────────────────────────┐ │
│  │             │  HTTP  │           nBogne Adapter               │ │
│  │   OpenMRS   │───────▶│                                        │ │
│  │   OpenEMR   │  POST  │  ┌──────────┐    ┌─────────────────┐  │ │
│  │   DHIS2     │  FHIR  │  │ Receiver │───▶│ Persistent Queue│  │ │
│  │             │        │  └──────────┘    │    (SQLite)     │  │ │
│  └─────────────┘        │                  └────────┬────────┘  │ │
│                         │                           │           │ │
│                         │                  ┌────────▼────────┐  │ │
│                         │                  │   Transmitter   │  │ │
│                         │                  │  (Retry Logic)  │  │ │
│                         │                  └────────┬────────┘  │ │
│                         └───────────────────────────┼───────────┘ │
└─────────────────────────────────────────────────────┼─────────────┘
                                                      │
                                                      │ GPRS
                                                      │ (gzip + base64)
                                                      │
┌─────────────────────────────────────────────────────▼─────────────┐
│                         CENTRAL HIE                               │
│                                                                   │
│  ┌─────────────────┐    ┌──────────┐    ┌─────────────────────┐  │
│  │ nBogne Mediator │───▶│ OpenHIM  │───▶│ Destination Systems │  │
│  │ (decode/route)  │    │ (log)    │    │ (SHR, Lab, etc.)    │  │
│  └─────────────────┘    └──────────┘    └─────────────────────┘  │
└───────────────────────────────────────────────────────────────────┘
```

### Components

| Component | Description |
|-----------|-------------|
| **EMR Receiver** | HTTP server receiving FHIR bundles from local EMR |
| **Wire Format** | 48-byte binary header + compressed payload |
| **Persistent Queue** | SQLite-backed store-and-forward queue |
| **Transmitter** | GPRS transmission with exponential backoff |
| **nBogne Mediator** | Central receiver (separate project) |

---

## Features

### Reliability
- ✅ **Persistent queue** - Messages survive crashes and power outages
- ✅ **Automatic retries** - Exponential backoff with full jitter
- ✅ **Idempotency keys** - Safe retries without duplicates
- ✅ **Dead letter queue** - Failed messages preserved for analysis

### Efficiency
- ✅ **Gzip compression** - 60-80% size reduction for FHIR bundles
- ✅ **Connection pooling** - Reuses TCP connections
- ✅ **Batched processing** - Configurable batch size
- ✅ **GPRS-optimized timeouts** - Based on RFC 3481

### Operations
- ✅ **Health check endpoint** - `/health` for monitoring
- ✅ **Statistics endpoint** - `/stats` for observability
- ✅ **Structured logging** - JSON-compatible, rotated
- ✅ **Graceful shutdown** - Clean handling of SIGTERM/SIGINT

---

## Installation

### Prerequisites

- Python 3.10 or higher
- pip package manager
- Network access to central mediator

### From Source

```bash
# Clone repository
git clone https://github.com/nbogne/nbogne-adapter.git
cd nbogne-adapter

# Create virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or: venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Install in development mode
pip install -e .
```

### Verify Installation

```bash
python -c "from nbogne import NBogneAdapter; print('OK')"
```

---

## Quick Start

### 1. Create Configuration

```bash
cp config/default.yaml config/local.yaml
```

Edit `config/local.yaml`:

```yaml
facility:
  id: "FAC-001"
  name: "My Health Facility"
  phone_number: "+233500000000"

mediator:
  endpoint: "https://mediator.example.com/gsm/inbound"
  sms_number: "+233000000000"

emr:
  type: "openmrs"
  base_url: "http://localhost:8080"
```

### 2. Start the Adapter

```bash
python -m scripts.run_adapter --config config/local.yaml
```

You should see:

```
2024-01-15 10:30:00 | INFO     | nbogne | ============================================================
2024-01-15 10:30:00 | INFO     | nbogne | nBogne Adapter Starting
2024-01-15 10:30:00 | INFO     | nbogne | ============================================================
2024-01-15 10:30:00 | INFO     | nbogne | Facility: FAC-001 (My Health Facility)
2024-01-15 10:30:00 | INFO     | nbogne | Mediator: https://mediator.example.com/gsm/inbound
2024-01-15 10:30:00 | INFO     | nbogne | EMR Receiver: http://0.0.0.0:8080/fhir
2024-01-15 10:30:00 | INFO     | nbogne | ============================================================
```

### 3. Send Test Data

```bash
# Send a FHIR bundle to the adapter
curl -X POST http://localhost:8080/fhir \
  -H "Content-Type: application/json" \
  -H "X-Destination: CENTRAL" \
  -d '{
    "resourceType": "Bundle",
    "type": "message",
    "entry": [{
      "resource": {
        "resourceType": "Patient",
        "name": [{"family": "Doe", "given": ["John"]}]
      }
    }]
  }'
```

Response:

```json
{
  "status": "queued",
  "message_id": "550e8400-e29b-41d4-a716-446655440000",
  "queue_id": 1,
  "timestamp": "2024-01-15T10:30:15.123456"
}
```

---

## Configuration

### Full Configuration Reference

```yaml
# =============================================================================
# nBogne Adapter Configuration
# =============================================================================

# -----------------------------------------------------------------------------
# Facility Configuration
# -----------------------------------------------------------------------------
facility:
  id: "FAC-001"              # Unique ID (max 8 characters)
  name: "Sample Facility"    # Human-readable name
  phone_number: "+233500000000"  # SIM card number for SMS fallback

# -----------------------------------------------------------------------------
# Mediator Configuration
# -----------------------------------------------------------------------------
mediator:
  endpoint: "https://mediator.example.com/gsm/inbound"
  sms_number: "+233000000000"
  api_key: null              # Set via NBOGNE_MEDIATOR_API_KEY

# -----------------------------------------------------------------------------
# EMR Configuration
# -----------------------------------------------------------------------------
emr:
  type: "openmrs"            # openmrs, openemr, dhis2, custom
  base_url: "http://localhost:8080"
  fhir_endpoint: "/openmrs/ws/fhir2/R4"
  auth_token: null
  polling_interval: 0        # 0 = push mode (EMR sends to adapter)

# -----------------------------------------------------------------------------
# Transmission Configuration (GPRS-optimized)
# -----------------------------------------------------------------------------
transmission:
  timeout_connect: 30.0      # TCP connection timeout (seconds)
  timeout_read: 120.0        # HTTP read timeout (seconds)
  max_retries: 5             # Attempts before dead letter
  base_delay: 3.0            # Exponential backoff base (seconds)
  max_delay: 300.0           # Maximum retry delay (seconds)
  jitter: true               # Full jitter (recommended)
  keepalive_interval: 55.0   # HTTP keep-alive (seconds)

# -----------------------------------------------------------------------------
# Queue Configuration
# -----------------------------------------------------------------------------
queue:
  db_path: "data/outbox.db"  # SQLite database path
  max_size: 10000            # Maximum queue size (0 = unlimited)
  batch_size: 10             # Messages per drain cycle
  drain_interval: 5.0        # Seconds between drain attempts
  retention_days: 30         # Days to keep acknowledged messages

# -----------------------------------------------------------------------------
# Modem Configuration
# -----------------------------------------------------------------------------
modem:
  port: "/dev/ttyUSB0"       # Serial port
  baudrate: 115200           # Baud rate
  apn: "internet"            # Mobile carrier APN
  apn_user: ""               # APN username
  apn_password: ""           # APN password
  pin: null                  # SIM PIN (if required)
  model: "auto"              # quectel, simcom, huawei, auto

# -----------------------------------------------------------------------------
# Server Configuration
# -----------------------------------------------------------------------------
server:
  host: "0.0.0.0"            # Bind address
  port: 8080                 # Port number
  path: "/fhir"              # Endpoint path

# -----------------------------------------------------------------------------
# Logging Configuration
# -----------------------------------------------------------------------------
logging:
  level: "INFO"              # DEBUG, INFO, WARNING, ERROR
  file: "logs/nbogne.log"    # Log file path (null = stdout only)
  max_bytes: 10485760        # 10 MB max file size
  backup_count: 5            # Number of backup files
```

### Environment Variables

| Variable | Config Path | Example |
|----------|-------------|---------|
| `NBOGNE_FACILITY_ID` | facility.id | `FAC-002` |
| `NBOGNE_FACILITY_NAME` | facility.name | `My Clinic` |
| `NBOGNE_MEDIATOR_ENDPOINT` | mediator.endpoint | `https://...` |
| `NBOGNE_MEDIATOR_API_KEY` | mediator.api_key | `secret123` |
| `NBOGNE_EMR_TYPE` | emr.type | `openmrs` |
| `NBOGNE_EMR_URL` | emr.base_url | `http://...` |
| `NBOGNE_MODEM_PORT` | modem.port | `/dev/ttyACM0` |
| `NBOGNE_MODEM_APN` | modem.apn | `safaricom` |
| `NBOGNE_QUEUE_PATH` | queue.db_path | `/data/queue.db` |
| `NBOGNE_LOG_LEVEL` | logging.level | `DEBUG` |

---

## Wire Format Protocol

### Header Structure (48 bytes, big-endian)

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| 0 | 2 | Version | Protocol version (0x0001) |
| 2 | 16 | Message ID | UUID v4 as raw bytes |
| 18 | 8 | Source Facility | Left-padded with 0x00 |
| 26 | 8 | Dest Facility | Left-padded with 0x00 |
| 34 | 2 | Message Type | See table below |
| 36 | 4 | Timestamp | Unix timestamp (seconds) |
| 40 | 4 | Payload Length | Original (uncompressed) |
| 44 | 1 | Segment Number | 0 if not fragmented |
| 45 | 1 | Total Segments | 1 if not fragmented |
| 46 | 2 | Reference Number | For segment reassembly |

### Message Types

| Code | Name | Description |
|------|------|-------------|
| 0x0001 | REFERRAL | Patient referral |
| 0x0002 | OBSERVATION | Lab results, vital signs |
| 0x0003 | PATIENT | Patient demographics |
| 0x0004 | ENCOUNTER | Clinical encounter |
| 0x0005 | BUNDLE | Generic FHIR bundle |
| 0x0006 | RESPONSE | Response to message |
| 0x0007 | ACK | Delivery acknowledgment |
| 0x0008 | NACK | Negative acknowledgment |
| 0x00FE | HEARTBEAT | Keep-alive |
| 0x00FF | ERROR | Error message |

### Encoding Pipeline

```
┌─────────────────────────────────────────────────────────────┐
│  Original FHIR JSON (e.g., 5,000 bytes)                     │
└─────────────────────┬───────────────────────────────────────┘
                      │ gzip (level 6)
                      ▼
┌─────────────────────────────────────────────────────────────┐
│  Compressed bytes (~1,500 bytes, 70% reduction)             │
└─────────────────────┬───────────────────────────────────────┘
                      │ base64 encode
                      ▼
┌─────────────────────────────────────────────────────────────┐
│  Base64 string (~2,000 bytes, SMS-safe)                     │
└─────────────────────┬───────────────────────────────────────┘
                      │ prepend 48-byte header
                      ▼
┌─────────────────────────────────────────────────────────────┐
│  Final message (~2,048 bytes)                               │
│  [48-byte header][base64 payload]                           │
└─────────────────────────────────────────────────────────────┘
```

---

## API Reference

### POST /fhir

Submit a FHIR resource for transmission.

**Request:**
```http
POST /fhir HTTP/1.1
Host: localhost:8080
Content-Type: application/json
X-Destination: FAC-002
X-Priority: 5

{"resourceType": "Bundle", "type": "message", ...}
```

**Headers:**
| Header | Required | Description |
|--------|----------|-------------|
| X-Destination | Yes | Target facility ID |
| X-Priority | No | Priority (higher = more urgent, default: 0) |

**Response (202 Accepted):**
```json
{
  "status": "queued",
  "message_id": "550e8400-e29b-41d4-a716-446655440000",
  "queue_id": 1,
  "timestamp": "2024-01-15T10:30:15.123456"
}
```

### GET /health

Health check endpoint.

**Response (200 OK):**
```json
{
  "status": "healthy",
  "timestamp": "2024-01-15T10:30:15.123456",
  "queue_size": 5
}
```

### GET /stats

Detailed statistics.

**Response (200 OK):**
```json
{
  "queue": {
    "total": 100,
    "by_status": {"pending": 5, "acked": 95},
    "max_size": 10000
  },
  "received": {
    "received": 100,
    "queued": 100,
    "errors": 0
  },
  "timestamp": "2024-01-15T10:30:15.123456"
}
```

---

## Integration Guide

### OpenMRS Integration

```python
# Example: Send patient referral from OpenMRS
import requests

referral = {
    "resourceType": "Bundle",
    "type": "message",
    "entry": [
        {
            "resource": {
                "resourceType": "ServiceRequest",
                "status": "active",
                "intent": "order",
                "subject": {"reference": "Patient/123"},
                "requester": {"reference": "Practitioner/456"}
            }
        }
    ]
}

requests.post(
    "http://localhost:8080/fhir",
    json=referral,
    headers={"X-Destination": "REGIONAL-HOSPITAL"}
)
```

### DHIS2 Integration

Point DHIS2 program notifications to the adapter endpoint.

### CommCare Integration

Configure CommCare form submissions to forward to nBogne.

---

## Deployment

### Systemd Service (Recommended for Production)

```ini
# /etc/systemd/system/nbogne-adapter.service
[Unit]
Description=nBogne Adapter
After=network.target

[Service]
Type=simple
User=nbogne
WorkingDirectory=/opt/nbogne-adapter
ExecStart=/opt/nbogne-adapter/venv/bin/python -m scripts.run_adapter
Restart=always
RestartSec=10
Environment=NBOGNE_CONFIG_PATH=/opt/nbogne-adapter/config/production.yaml
Environment=NBOGNE_MEDIATOR_API_KEY=your-secret-key

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable nbogne-adapter
sudo systemctl start nbogne-adapter
sudo journalctl -u nbogne-adapter -f
```

---

## Troubleshooting

### Queue Growing Without Draining

1. Check mediator connectivity: `curl https://mediator.example.com/health`
2. Check logs: `tail -f logs/nbogne.log`
3. Verify API key is correct

### Connection Timeouts

Increase timeouts for very slow networks:
```yaml
transmission:
  timeout_connect: 60.0
  timeout_read: 180.0
```

### Debug Mode

```bash
python -m scripts.run_adapter --log-level DEBUG
```

---

## Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=nbogne --cov-report=html

# Run specific test file
pytest tests/test_wire_format.py -v
```

---

## License

MIT License - see [LICENSE](LICENSE) for details.

---

## Acknowledgments

Informed by documented patterns from CommCare, DHIS2, OpenMRS, ODK, and AWS Architecture Blog.

**Contact:** tsteve@nbogne.com | https://nbogne.com
