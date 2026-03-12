# nBogne - SMS Transport Layer for Health Data

## What This Is

nBogne moves structured FHIR health records between health information systems
over SMS when internet is unavailable. It sits beneath OpenHIM and DHIS2 as
a transport layer they didn't have before.

## Architecture

```
FACILITY                              CENTRAL SERVER
┌──────────┐                          ┌──────────────┐
│  OpenMRS │──FHIR──→ Adapter         │   Receiver   │──HTTP──→ OpenHIM/DHIS2
│  or any  │         (compress+       │   (decrypt+  │
│  EMR     │          encrypt+        │    decompress+│
└──────────┘          encode)         │    reconstruct)│
                       ↓              │       ↑       │
                  ┌─────────┐        ┌┴───────────┐
                  │ Gammu + │──SMS──→│ Gammu +     │
                  │ Modem A │←──SMS──│ Modem B     │
                  └─────────┘  ACK  └─────────────┘
```

## Directory Structure

```
nbogne/
├── README.md                 # This file
├── config.py                 # Configuration (modem numbers, paths, keys)
├── models.py                 # Data models and wire protocol
│
├── compression/
│   ├── __init__.py
│   ├── templates.py          # FHIR template registry + value extraction
│   ├── encoder.py            # Binary value encoder (bit-packing)
│   ├── dictionary.py         # Zstd dictionary training + compression
│   └── pipeline.py           # Full compression pipeline orchestrator
│
├── crypto/
│   ├── __init__.py
│   └── encryption.py         # L1 (E2EE) and L2 (transport) encryption
│
├── transport/
│   ├── __init__.py
│   ├── sms.py                # Gammu SMS send/receive via AT commands
│   ├── wire.py               # Wire protocol: header + payload + CRC
│   └── queue.py              # SQLite persistent queue with retry logic
│
├── adapter/
│   ├── __init__.py
│   ├── sender.py             # Sending adapter (facility side)
│   └── receiver.py           # Receiving adapter (server side)
│
├── logging_db/
│   ├── __init__.py
│   └── transmission_log.py   # SQLite transmission logging (WS0)
│
├── tests/
│   ├── test_compression.py   # Compression round-trip tests
│   ├── test_wire.py          # Wire protocol tests
│   ├── test_e2e.py           # End-to-end without SMS (loopback)
│   └── sample_fhir.py        # Sample FHIR records for testing
│
└── tools/
    ├── train_dictionary.py   # Train zstd dictionary from FHIR samples
    └── generate_templates.py # Generate FHIR templates from sample data
```

## How To Test (Two Laptops)

1. Install Python 3.10+ on both laptops
2. `pip install zstandard cryptography`
3. Copy this entire `nbogne/` folder to both laptops
4. On laptop A (facility): `python -m adapter.sender`
5. On laptop B (server): `python -m adapter.receiver`
6. For loopback test (no modem): `python -m tests.test_e2e`

## Compression Pipeline

```
FHIR JSON (20KB)
    ↓ template match?
    ├── YES → extract variable values → bit-pack binary (35-300 bytes)
    └── NO  → FhirProto-style binary encode → trained zstd (800-1500 bytes)
    ↓
Encrypted L1 (E2EE, AES-256-GCM)
    ↓
Wire header added (template_id, msg_id, dest, CRC)
    ↓
Encrypted L2 (transport, AES-256-GCM)
    ↓
Base64 encoded for SMS
    ↓
Gammu AT+CMGS → GSM → Modem B
```
