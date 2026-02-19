# Backend Engineer Study Topics — nBogne

**For:** New Backend Engineer
**Purpose:** Get up to speed on nBogne's technical stack and use cases

---

## 1. Health Data Standards & Systems

- **FHIR (Fast Healthcare Interoperability Resources)** — resource types, JSON structure, patient/observation resources
- **OpenMRS REST API** — authentication, patient endpoints, data retrieval
- **OpenHIM architecture** — channels, mediators, transaction logging
- **DHIS2 basics** — data elements, aggregate vs tracker data, API structure
- **HL7 overview** — message types, how it differs from FHIR

---

## 2. Data Compression & Encoding

- **gzip/zlib compression** — Python implementation, compression ratios
- **MessagePack vs JSON** — binary serialization, size comparison
- **Protocol Buffers basics** — schema definition, encoding efficiency
- **Base64 encoding** — when and why to use it
- **Payload optimization** — stripping unnecessary fields, minification

---

## 3. Low-Bandwidth Transmission

- **GPRS/2G fundamentals** — packet data, connection persistence, throughput limits
- **SMS gateway integration** — Africa's Talking API, Twilio, message segmentation
- **USSD basics** — session-based communication, character limits
- **AT commands** — modem communication, sending data over cellular
- **APN configuration** — carrier settings, data routing

---

## 4. Queue & Retry Systems

- **Message queue patterns** — producer/consumer, pub/sub
- **Redis queues** — basic operations, persistence
- **RabbitMQ or Celery** — task queuing, retry logic
- **Exponential backoff** — retry strategies, jitter
- **Idempotency** — ensuring safe retries, deduplication

---

## 5. Python Backend Specifics

- **FastAPI or Flask** — REST endpoint design, async handling
- **pytest** — unit testing, fixtures, mocking external APIs
- **Docker basics** — containerization, docker-compose for multi-service
- **Environment management** — .env files, secrets handling
- **Logging best practices** — structured logs, log levels

---

## 6. nBogne Use Cases (Read Technical Design Doc)

- **Use Case 1:** OpenMRS → nBogne Adapter → 2G → Mediator → OpenHIM (unidirectional)
- **Use Case 2:** Bidirectional flow — queries from central to facility
- **Use Case 3:** Multi-EMR support — OpenEMR, other systems
- **Wire format design** — header structure, payload schema
- **Dashboard** — transmission history, queue status display

---

## 7. Networking & Infrastructure

- **HTTP vs raw TCP** — when to use each over constrained networks
- **Connection pooling** — managing limited connections
- **Timeout handling** — graceful degradation
- **Network simulation** — testing with throttled bandwidth (tc, toxiproxy)
- **Modem interfacing** — serial communication, USB modems

---

## Suggested Learning Order

| Week | Focus Area |
|------|------------|
| 1 | FHIR basics + OpenMRS API |
| 2 | OpenHIM architecture + existing adapter code |
| 3 | Compression techniques + payload optimization |
| 4 | Queue systems + retry logic |
| 5 | GPRS/SMS transmission concepts |
| 6 | Integration testing + Docker setup |

---

## Resources

- FHIR: https://hl7.org/fhir/
- OpenMRS: https://wiki.openmrs.org/display/docs/REST+Web+Services+API+For+Clients
- OpenHIM: https://openhim.org/docs/
- Africa's Talking: https://africastalking.com/docs
- DHIS2: https://docs.dhis2.org/

---

*Review the TECHNICAL_DESIGN_DOCUMENT.md for full context on nBogne architecture and current implementation status.*
