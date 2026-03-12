# nBogne — SMS Transport Layer for Health Data

## What This Is

nBogne moves structured FHIR health records between health information systems
over SMS when internet is unavailable. It sits beneath OpenHIM and DHIS2 as
a transport layer they didn't have before.

A typical outpatient encounter (~2.5 KB of FHIR JSON) compresses to **58 bytes**
and fits in **1 binary SMS segment** — a ~45x compression ratio.

## Architecture

```
FACILITY                                       CENTRAL SERVER
┌──────────┐                                   ┌──────────────┐
│  OpenMRS │──FHIR──→ SendingAdapter           │ ReceivingAdapter ──HTTP──→ OpenHIM / DHIS2
│  or any  │         ┌──────────────┐          │ ┌──────────────┐│
│  EMR     │         │ 1. Compress  │          │ │ 5. Decrypt L2 ││
└──────────┘         │ 2. Encrypt L1│          │ │ 6. Verify CRC ││
                     │ 3. Wire pack │          │ │ 7. Decrypt L1 ││
                     │ 4. Encrypt L2│          │ │ 8. Decompress ││
                     └──────┬───────┘          │ └───────┬──────┘│
                            ↓                  │         ↑       │
                     ┌────────────┐       ┌────┴─────────────┐
                     │ USB Modem A│─SMS──→│ USB Modem B      │
                     │  (Gammu)   │←─ACK──│  (Gammu)         │
                     └────────────┘       └──────────────────┘
```

## Compression Pipeline

```
FHIR JSON (~2.5 KB)
    ↓ template match?
    │
    ├─ YES ─→ extract fields → codebook lookup (ICD-10, LOINC, meds → uint16)
    │         → binary encode (uint8 vitals, offset_uint8 temp, dates as uint16)
    │         → ~58 bytes
    │
    └─ NO ──→ minify JSON → zstd level 19 + trained FHIR dictionary
              → ~600–1200 bytes
    ↓
Encrypt L1 (E2E, AES-256-GCM, nonce derived from msg_id — no nonce on wire)
    ↓                                            overhead: +16 bytes (tag only)
Wire packet: [magic 2B][ver 1B][flags 1B][template 1B][msg_id 4B]
             [dest_len 1B][dest ~13B][payload_len 2B][payload][CRC16 2B]
    ↓                                            overhead: ~25 bytes
Encrypt L2 (transport, AES-256-GCM, random nonce)
    ↓                                            overhead: +28 bytes (nonce+tag)
Binary SMS segments (132 data bytes per segment, 2-byte framing header)
    ↓
Gammu → GSM → Modem B
```

### Size Budget (typical encounter)

| Stage | Bytes | Notes |
|---|---|---|
| Compressed payload | 58 | Template + codebook + tight types |
| + L1 tag | +16 | GCM tag only (nonce derived, not on wire) |
| + Wire header | ~25 | Magic, version, flags, msg_id, dest, CRC |
| + L2 nonce + tag | +28 | Random nonce + GCM tag |
| **Total wire** | **~127** | |
| + 2-byte segment header | +2 | Index + total count |
| **Per SMS segment** | **~129** | **1 SMS** |

### Compression Techniques

| Technique | What it does | Savings |
|---|---|---|
| **Template matching** | 4 built-in FHIR templates (encounter, lab, referral, immunization) extract only variable fields; all structure is implicit | 2.5 KB → ~100 B |
| **Code dictionaries** | ICD-10, LOINC, CVX, medication, UCUM codes mapped to uint16 indices; 170+ codes across 8 codebooks | 3–15 B per code field |
| **Tight numeric types** | BP, HR, height → uint8; temperature → offset_uint8 (base 25°C, 0.1 precision); SpO2 → uint8 | ~1 B per vital saved |
| **Deterministic L1 nonce** | GCM nonce derived from msg_id via SHA-256 — not stored on wire | 12 B saved |
| **Binary SMS** | Raw binary segments (132 B data + 2 B header) instead of Base64 text — eliminates 33% encoding expansion | ~22% more capacity |
| **Zstd dictionary** (fallback) | Pre-trained ~110 KB dictionary on FHIR JSON patterns, compression level 19 | 50–70% reduction |

### Built-in Templates

| ID | Name | Use Case | Key Fields |
|---|---|---|---|
| 1 | `basic_encounter` | Outpatient visit | Patient, date, practitioner, BP, HR, temp, SpO2, weight, height, 3 diagnoses, 2 meds, note |
| 2 | `lab_result` | Lab observation | Patient, date, LOINC code, value, unit, ref range, interpretation |
| 3 | `referral` | Inter-facility transfer | Patient, date, from/to facility, priority, reason, vitals, meds |
| 4 | `immunization` | Vaccination record | Patient, date, CVX code, dose, site, lot, performer |

## Wire Protocol

```
Byte offset:
  0..1   MAGIC     0x6E42 ("nB")
  2      VERSION   0x01
  3      FLAGS     bit 0: fallback, bit 1: handshake, bit 2: reserved
  4      TEMPLATE  template_id (0 = fallback, 1–4 = built-in)
  5..8   MSG_ID    4 random bytes (also seeds L1 nonce)
  9      DEST_LEN  length of destination phone number
  10..N  DEST      ASCII phone number (e.g. "+233000000000")
  N+1..  PAYLOAD   [2B length][encrypted compressed data]
  last 2 CRC16     CRC-16/CCITT-FALSE over everything before it
```

## Encryption

| Layer | Purpose | Key | Nonce | Overhead |
|---|---|---|---|---|
| **L1** (E2E) | Confidentiality of FHIR data; only endpoints can decrypt | `NBOGNE_L1_KEY` (256-bit) | Derived from msg_id (not on wire) | **16 B** (GCM tag) |
| **L2** (Transport) | Protects against GSM interception; hop-by-hop | `NBOGNE_L2_KEY` (256-bit) | Random 12 B (prepended) | **28 B** (nonce + tag) |

## Directory Structure

```
nbogne/
├── config.py                 # All settings (modem, SMS limits, keys, paths)
├── models.py                 # WirePacket, Handshake, CRC16, generate_msg_id
├── README.md
│
├── compression/
│   ├── codebook.py           # Medical code dictionaries (ICD-10, LOINC, CVX, meds…)
│   ├── templates.py          # FHIR template registry, extraction, reconstruction
│   ├── encoder.py            # Binary field encoder/decoder (string, code, uint8, offset_uint8…)
│   ├── dictionary.py         # Zstd dictionary compression (training + compress/decompress)
│   └── pipeline.py           # Orchestrates template vs fallback compression
│
├── crypto/
│   └── encryption.py         # AES-256-GCM: L1 (deterministic nonce) + L2 (random nonce)
│
├── transport/
│   ├── sms.py                # GammuTransport (USB modem) + LoopbackTransport (testing)
│   ├── wire.py               # Binary SMS segmentation (132 B data/segment) + reassembly
│   └── queue.py              # SQLite persistent queue with retry logic
│
├── adapter/
│   ├── sender.py             # Facility-side: FHIR → compress → encrypt → SMS
│   └── receiver.py           # Server-side: SMS → decrypt → decompress → HTTP POST
│
├── logging_db/
│   └── transmission_log.py   # SQLite transmission metrics (for future ML routing)
│
├── tests/
│   └── test_e2e.py           # End-to-end test with LoopbackTransport
│
└── data/
    └── fhir.zstd_dict        # Pre-trained zstd dictionary (generated)
```

## Quick Start

### Requirements

- Python 3.10+
- `pip install zstandard cryptography`
- For real SMS: `sudo apt install gammu` + USB GSM modem

### Run End-to-End Test (no hardware needed)

```bash
cd nbogne/
python -m tests.test_e2e
```

Expected output:
```
TEST: Basic Encounter (vitals + dx + meds)
  Original FHIR JSON: 2,585 bytes
  Template 1: 2585B → 58B (44.6x)
  Binary wire: 131 bytes across 1 SMS
  Compression ratio: 19.7x
  Values preserved: ✓
  ACK received: ✓

TEST: Lab Result
  Original FHIR JSON: 502 bytes
  Template 2: 502B → 56B (9.0x)
  Binary wire: 129 bytes across 1 SMS
  Values preserved: ✓
  ✅ ALL TESTS PASSED
```

### Deploy on Two Machines

1. Copy `nbogne/` to both machines
2. Set environment variables on each:
   ```bash
   export NBOGNE_L1_KEY="<64-char hex key>"   # Same on both
   export NBOGNE_L2_KEY="<64-char hex key>"   # Same on both
   export NBOGNE_MODEM_PORT="/dev/ttyUSB0"
   export NBOGNE_DEST_NUMBER="+233XXXXXXXXX"  # The other machine's modem
   ```
3. Facility side: integrate `SendingAdapter.send_record(fhir_json)` with your EMR
4. Server side: run the receiver to listen for SMS and forward to OpenHIM/DHIS2

## Configuration

All settings live in `config.py`. Key ones:

| Setting | Default | Description |
|---|---|---|
| `SMS_MAX_SEGMENTS` | 6 | Max concatenated SMS segments per transmission |
| `SMS_BINARY_BYTES_PER_SEGMENT` | 134 | Raw bytes per binary SMS (140 - 6 UDH) |
| `ZSTD_COMPRESSION_LEVEL` | 19 | Compression level for fallback path (1–22) |
| `MAX_RETRIES` | 5 | Queue retry attempts before marking failed |
| `L1_KEY` / `L2_KEY` | Test keys | **Change in production** |
