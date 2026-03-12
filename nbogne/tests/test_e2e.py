"""
End-to-End Test

Proves the full nBogne pipeline works:
  FHIR JSON → compress → encrypt → wire → SMS segments → reassemble → decrypt → decompress → FHIR JSON

Uses LoopbackTransport (no hardware needed).
Run: python -m tests.test_e2e (from nbogne/ directory)
"""
import sys
import json
import logging
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from transport.sms import LoopbackTransport
from adapter.sender import SendingAdapter
from adapter.receiver import ReceivingAdapter

logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")
log = logging.getLogger("test_e2e")


# ============================================================
# Sample FHIR records for testing
# ============================================================

SAMPLE_ENCOUNTER = {
    "resourceType": "Bundle",
    "type": "transaction",
    "entry": [
        {"resource": {
            "resourceType": "Patient",
            "id": "patient-001",
            "name": [{"family": "Mensah", "given": ["Kofi"]}],
            "gender": "male",
            "birthDate": "1985-03-15",
        }},
        {"resource": {
            "resourceType": "Encounter",
            "status": "finished",
            "type": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "AMB"}]}],
            "period": {"start": "2026-03-10"},
            "participant": [{"individual": {"reference": "Practitioner/dr-owusu"}}],
        }},
        {"resource": {
            "resourceType": "Observation",
            "status": "final",
            "code": {"coding": [{"system": "http://loinc.org", "code": "8480-6", "display": "Systolic blood pressure"}]},
            "valueQuantity": {"value": 128, "unit": "mmHg", "system": "http://unitsofmeasure.org", "code": "mmHg"},
            "effectiveDateTime": "2026-03-10",
        }},
        {"resource": {
            "resourceType": "Observation",
            "status": "final",
            "code": {"coding": [{"system": "http://loinc.org", "code": "8462-4", "display": "Diastolic blood pressure"}]},
            "valueQuantity": {"value": 82, "unit": "mmHg", "system": "http://unitsofmeasure.org", "code": "mmHg"},
            "effectiveDateTime": "2026-03-10",
        }},
        {"resource": {
            "resourceType": "Observation",
            "status": "final",
            "code": {"coding": [{"system": "http://loinc.org", "code": "8867-4", "display": "Heart rate"}]},
            "valueQuantity": {"value": 76, "unit": "/min", "system": "http://unitsofmeasure.org", "code": "/min"},
            "effectiveDateTime": "2026-03-10",
        }},
        {"resource": {
            "resourceType": "Observation",
            "status": "final",
            "code": {"coding": [{"system": "http://loinc.org", "code": "8310-5", "display": "Body temperature"}]},
            "valueQuantity": {"value": 36.8, "unit": "Cel", "system": "http://unitsofmeasure.org", "code": "Cel"},
            "effectiveDateTime": "2026-03-10",
        }},
        {"resource": {
            "resourceType": "Observation",
            "status": "final",
            "code": {"coding": [{"system": "http://loinc.org", "code": "29463-7", "display": "Body weight"}]},
            "valueQuantity": {"value": 72.5, "unit": "kg", "system": "http://unitsofmeasure.org", "code": "kg"},
            "effectiveDateTime": "2026-03-10",
        }},
        {"resource": {
            "resourceType": "Condition",
            "clinicalStatus": {"coding": [{"code": "active"}]},
            "code": {"coding": [{"system": "http://hl7.org/fhir/sid/icd-10", "code": "I10", "display": "Essential hypertension"}]},
        }},
        {"resource": {
            "resourceType": "Condition",
            "clinicalStatus": {"coding": [{"code": "active"}]},
            "code": {"coding": [{"system": "http://hl7.org/fhir/sid/icd-10", "code": "E11.9", "display": "Type 2 diabetes"}]},
        }},
        {"resource": {
            "resourceType": "MedicationRequest",
            "status": "active",
            "intent": "order",
            "medicationCodeableConcept": {"coding": [{"code": "amlodipine-5mg"}]},
        }},
        {"resource": {
            "resourceType": "MedicationRequest",
            "status": "active",
            "intent": "order",
            "medicationCodeableConcept": {"coding": [{"code": "metformin-500mg"}]},
        }},
    ]
}

SAMPLE_LAB = {
    "resourceType": "Bundle",
    "type": "transaction",
    "entry": [
        {"resource": {"resourceType": "Patient", "id": "patient-002"}},
        {"resource": {
            "resourceType": "Observation",
            "status": "final",
            "code": {"coding": [{"system": "http://loinc.org", "code": "2339-0", "display": "Glucose"}]},
            "valueQuantity": {"value": 142.5, "unit": "mg/dL"},
            "effectiveDateTime": "2026-03-10",
            "referenceRange": [{"low": {"value": 70}, "high": {"value": 100}}],
            "interpretation": [{"coding": [{"code": "H"}]}],
            "performer": [{"reference": "Practitioner/lab-tech-1"}],
        }},
    ]
}


def run_test():
    print("\n" + "=" * 70)
    print("  nBogne End-to-End Test")
    print("=" * 70)

    # Set up loopback transport (simulates two modems)
    facility_modem = LoopbackTransport()
    server_modem = LoopbackTransport()
    facility_modem.connect(server_modem)

    sender = SendingAdapter(transport=facility_modem, destination="+233000000000")
    receiver = ReceivingAdapter(transport=server_modem, forward_to="none")

    tests = [
        ("Basic Encounter (vitals + dx + meds)", SAMPLE_ENCOUNTER),
        ("Lab Result", SAMPLE_LAB),
    ]

    all_passed = True
    for name, fhir_input in tests:
        print(f"\n{'─' * 60}")
        print(f"  TEST: {name}")
        print(f"{'─' * 60}")

        original_json = json.dumps(fhir_input, separators=(',', ':'))
        original_size = len(original_json.encode('utf-8'))
        print(f"  Original FHIR JSON: {original_size:,} bytes")

        # SEND: facility → SMS segments
        queue_id = sender.send_record(fhir_input, patient_record_id="test-patient")

        # Check what's in the server modem inbox
        inbox = server_modem.read_all_sms()
        print(f"  SMS segments sent: {len(inbox)}")
        for i, msg in enumerate(inbox):
            print(f"    Segment {i+1}: {len(msg['text'])} chars")

        # RECEIVE: SMS segments → FHIR JSON
        reconstructed = None
        for msg in inbox:
            result = receiver.receive_sms(msg["text"], msg["from"])
            if result:
                reconstructed = result

        if reconstructed is None:
            print(f"  ❌ FAILED: No FHIR record reconstructed")
            all_passed = False
            continue

        reconstructed_json = json.dumps(reconstructed, separators=(',', ':'))
        reconstructed_size = len(reconstructed_json.encode('utf-8'))

        # Check ACK was sent back
        facility_inbox = facility_modem.read_all_sms()
        ack_received = len(facility_inbox) > 0

        # Validate key fields survived
        passed = True
        if fhir_input.get("resourceType") == "Bundle":
            orig_resources = {e["resource"]["resourceType"] for e in fhir_input.get("entry", [])}
            recon_resources = {e["resource"]["resourceType"] for e in reconstructed.get("entry", [])}

            # Check vital signs survived
            orig_vitals = {}
            recon_vitals = {}
            for entry in fhir_input.get("entry", []):
                r = entry["resource"]
                if r["resourceType"] == "Observation":
                    code = r["code"]["coding"][0]["code"]
                    val = r.get("valueQuantity", {}).get("value")
                    orig_vitals[code] = val
            for entry in reconstructed.get("entry", []):
                r = entry["resource"]
                if r["resourceType"] == "Observation":
                    code = r["code"]["coding"][0]["code"]
                    val = r.get("valueQuantity", {}).get("value")
                    recon_vitals[code] = val

            for code, orig_val in orig_vitals.items():
                recon_val = recon_vitals.get(code)
                if recon_val is None:
                    print(f"  ❌ Missing observation: {code}")
                    passed = False
                elif abs(float(orig_val) - float(recon_val)) > 0.1:
                    print(f"  ❌ Value mismatch for {code}: {orig_val} → {recon_val}")
                    passed = False

        # Calculate compression stats
        wire_size = sum(len(m["text"]) for m in inbox)
        ratio = original_size / wire_size if wire_size else 0

        print(f"  Compressed wire: {wire_size:,} chars across {len(inbox)} SMS")
        print(f"  Compression ratio: {ratio:.1f}x ({original_size:,}B → {wire_size:,} chars)")
        print(f"  ACK received: {'✓' if ack_received else '✗'}")
        print(f"  Values preserved: {'✓' if passed else '✗'}")

        if not passed:
            all_passed = False

        # Clean up
        server_modem.clear()
        facility_modem.clear()

    # Summary
    print(f"\n{'=' * 70}")
    if all_passed:
        print("  ✅ ALL TESTS PASSED")
    else:
        print("  ❌ SOME TESTS FAILED")
    print(f"{'=' * 70}")

    # Show queue stats
    print(f"\n  Queue stats: {sender.get_status()}")

    return all_passed


if __name__ == "__main__":
    success = run_test()
    sys.exit(0 if success else 1)
