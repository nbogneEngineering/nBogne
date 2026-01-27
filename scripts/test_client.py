#!/usr/bin/env python3
"""
Test Client for nBogne Adapter.

This script sends test FHIR bundles to the nBogne Adapter for testing
transmission and integration.

Usage:
    python -m scripts.test_client send --destination CENTRAL
    python -m scripts.test_client send --file patient.json --destination FAC-002
    python -m scripts.test_client batch --count 10 --destination CENTRAL
    python -m scripts.test_client health
    python -m scripts.test_client stats
"""

import argparse
import json
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

import requests

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


# Sample FHIR bundles for testing
SAMPLE_PATIENT_BUNDLE = {
    "resourceType": "Bundle",
    "type": "message",
    "timestamp": datetime.utcnow().isoformat(),
    "entry": [
        {
            "resource": {
                "resourceType": "MessageHeader",
                "eventCoding": {
                    "system": "http://example.org/fhir/message-events",
                    "code": "patient-create"
                },
                "source": {
                    "name": "nBogne Test Client",
                    "endpoint": "http://localhost:8080/fhir"
                }
            }
        },
        {
            "resource": {
                "resourceType": "Patient",
                "id": str(uuid.uuid4()),
                "identifier": [
                    {
                        "system": "http://example.org/fhir/patient-id",
                        "value": f"PAT-{uuid.uuid4().hex[:8].upper()}"
                    }
                ],
                "name": [
                    {
                        "use": "official",
                        "family": "Doe",
                        "given": ["John", "Robert"]
                    }
                ],
                "gender": "male",
                "birthDate": "1990-01-15",
                "address": [
                    {
                        "use": "home",
                        "city": "Accra",
                        "country": "Ghana"
                    }
                ],
                "telecom": [
                    {
                        "system": "phone",
                        "value": "+233201234567",
                        "use": "mobile"
                    }
                ]
            }
        }
    ]
}

SAMPLE_REFERRAL_BUNDLE = {
    "resourceType": "Bundle",
    "type": "message",
    "timestamp": datetime.utcnow().isoformat(),
    "entry": [
        {
            "resource": {
                "resourceType": "MessageHeader",
                "eventCoding": {
                    "system": "http://example.org/fhir/message-events",
                    "code": "referral-request"
                },
                "source": {
                    "name": "nBogne Test Client"
                }
            }
        },
        {
            "resource": {
                "resourceType": "ServiceRequest",
                "id": str(uuid.uuid4()),
                "status": "active",
                "intent": "order",
                "category": [
                    {
                        "coding": [
                            {
                                "system": "http://snomed.info/sct",
                                "code": "3457005",
                                "display": "Patient referral"
                            }
                        ]
                    }
                ],
                "priority": "urgent",
                "subject": {
                    "reference": f"Patient/{uuid.uuid4()}"
                },
                "authoredOn": datetime.utcnow().isoformat(),
                "requester": {
                    "reference": f"Practitioner/{uuid.uuid4()}"
                },
                "reasonCode": [
                    {
                        "coding": [
                            {
                                "system": "http://snomed.info/sct",
                                "code": "386661006",
                                "display": "Fever"
                            }
                        ],
                        "text": "High fever requiring specialist consultation"
                    }
                ],
                "note": [
                    {
                        "text": "Patient presenting with high fever for 3 days. Suspected malaria."
                    }
                ]
            }
        }
    ]
}

SAMPLE_OBSERVATION_BUNDLE = {
    "resourceType": "Bundle",
    "type": "message",
    "timestamp": datetime.utcnow().isoformat(),
    "entry": [
        {
            "resource": {
                "resourceType": "MessageHeader",
                "eventCoding": {
                    "system": "http://example.org/fhir/message-events",
                    "code": "observation-create"
                }
            }
        },
        {
            "resource": {
                "resourceType": "Observation",
                "id": str(uuid.uuid4()),
                "status": "final",
                "category": [
                    {
                        "coding": [
                            {
                                "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                                "code": "vital-signs"
                            }
                        ]
                    }
                ],
                "code": {
                    "coding": [
                        {
                            "system": "http://loinc.org",
                            "code": "8867-4",
                            "display": "Heart rate"
                        }
                    ]
                },
                "subject": {
                    "reference": f"Patient/{uuid.uuid4()}"
                },
                "effectiveDateTime": datetime.utcnow().isoformat(),
                "valueQuantity": {
                    "value": 72,
                    "unit": "beats/minute",
                    "system": "http://unitsofmeasure.org",
                    "code": "/min"
                }
            }
        }
    ]
}


def get_sample_bundle(bundle_type: str) -> dict:
    """Get a sample FHIR bundle by type."""
    bundles = {
        "patient": SAMPLE_PATIENT_BUNDLE,
        "referral": SAMPLE_REFERRAL_BUNDLE,
        "observation": SAMPLE_OBSERVATION_BUNDLE,
    }
    return bundles.get(bundle_type, SAMPLE_PATIENT_BUNDLE)


def cmd_send(args):
    """Send a FHIR bundle to the adapter."""
    base_url = f"http://{args.host}:{args.port}"
    endpoint = f"{base_url}{args.path}"
    
    # Load or generate bundle
    if args.file:
        with open(args.file) as f:
            bundle = json.load(f)
    else:
        bundle = get_sample_bundle(args.type)
    
    # Update timestamp
    bundle["timestamp"] = datetime.utcnow().isoformat()
    
    headers = {
        "Content-Type": "application/json",
        "X-Destination": args.destination,
    }
    
    if args.priority:
        headers["X-Priority"] = str(args.priority)
    
    print(f"\nSending {args.type} bundle to {endpoint}")
    print(f"Destination: {args.destination}")
    print(f"Size: {len(json.dumps(bundle))} bytes")
    
    try:
        start = time.time()
        response = requests.post(
            endpoint,
            json=bundle,
            headers=headers,
            timeout=(10, 30),
        )
        duration = (time.time() - start) * 1000
        
        print(f"\nResponse ({response.status_code}) in {duration:.0f}ms:")
        print(json.dumps(response.json(), indent=2))
        
        return 0 if response.status_code in (200, 201, 202) else 1
        
    except requests.exceptions.ConnectionError:
        print(f"\nError: Could not connect to {endpoint}")
        print("Is the adapter running?")
        return 1
    except Exception as e:
        print(f"\nError: {e}")
        return 1


def cmd_batch(args):
    """Send multiple test messages."""
    base_url = f"http://{args.host}:{args.port}"
    endpoint = f"{base_url}{args.path}"
    
    headers = {
        "Content-Type": "application/json",
        "X-Destination": args.destination,
    }
    
    print(f"\nSending {args.count} messages to {endpoint}")
    print(f"Destination: {args.destination}")
    print(f"Delay: {args.delay}s between messages\n")
    
    success = 0
    failed = 0
    total_time = 0
    
    bundle_types = ["patient", "referral", "observation"]
    
    for i in range(args.count):
        bundle_type = bundle_types[i % len(bundle_types)]
        bundle = get_sample_bundle(bundle_type)
        bundle["timestamp"] = datetime.utcnow().isoformat()
        
        try:
            start = time.time()
            response = requests.post(
                endpoint,
                json=bundle,
                headers=headers,
                timeout=(10, 30),
            )
            duration = (time.time() - start) * 1000
            total_time += duration
            
            if response.status_code in (200, 201, 202):
                success += 1
                status = "✓"
            else:
                failed += 1
                status = "✗"
            
            msg_id = response.json().get("message_id", "unknown")[:8]
            print(f"  [{i+1:3}/{args.count}] {status} {bundle_type:12} -> {msg_id}... ({duration:.0f}ms)")
            
        except Exception as e:
            failed += 1
            print(f"  [{i+1:3}/{args.count}] ✗ {bundle_type:12} -> Error: {e}")
        
        if args.delay and i < args.count - 1:
            time.sleep(args.delay)
    
    print(f"\nResults:")
    print(f"  Success: {success}")
    print(f"  Failed:  {failed}")
    if success > 0:
        print(f"  Avg Time: {total_time / success:.0f}ms")


def cmd_health(args):
    """Check adapter health."""
    base_url = f"http://{args.host}:{args.port}"
    endpoint = f"{base_url}/health"
    
    try:
        response = requests.get(endpoint, timeout=5)
        print(f"\nHealth Check: {endpoint}")
        print(f"Status: {response.status_code}")
        print(json.dumps(response.json(), indent=2))
        return 0 if response.status_code == 200 else 1
        
    except requests.exceptions.ConnectionError:
        print(f"\nHealth Check: {endpoint}")
        print("Status: UNREACHABLE")
        return 1


def cmd_stats(args):
    """Get adapter statistics."""
    base_url = f"http://{args.host}:{args.port}"
    endpoint = f"{base_url}/stats"
    
    try:
        response = requests.get(endpoint, timeout=5)
        print(f"\nStatistics from {endpoint}:")
        print(json.dumps(response.json(), indent=2))
        return 0
        
    except requests.exceptions.ConnectionError:
        print(f"\nCould not connect to {endpoint}")
        return 1


def main():
    parser = argparse.ArgumentParser(
        description="nBogne Adapter Test Client",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    
    parser.add_argument("--host", default="localhost", help="Adapter host")
    parser.add_argument("--port", type=int, default=8080, help="Adapter port")
    parser.add_argument("--path", default="/fhir", help="FHIR endpoint path")
    
    subparsers = parser.add_subparsers(dest="command", help="Command")
    
    # send command
    send_parser = subparsers.add_parser("send", help="Send a FHIR bundle")
    send_parser.add_argument("--destination", "-d", required=True, help="Target facility")
    send_parser.add_argument("--type", "-t", default="patient",
                            choices=["patient", "referral", "observation"])
    send_parser.add_argument("--file", "-f", help="JSON file to send")
    send_parser.add_argument("--priority", "-p", type=int, help="Message priority")
    send_parser.set_defaults(func=cmd_send)
    
    # batch command
    batch_parser = subparsers.add_parser("batch", help="Send multiple messages")
    batch_parser.add_argument("--destination", "-d", required=True, help="Target facility")
    batch_parser.add_argument("--count", "-n", type=int, default=10, help="Number of messages")
    batch_parser.add_argument("--delay", type=float, default=0.1, help="Delay between messages")
    batch_parser.set_defaults(func=cmd_batch)
    
    # health command
    health_parser = subparsers.add_parser("health", help="Check adapter health")
    health_parser.set_defaults(func=cmd_health)
    
    # stats command
    stats_parser = subparsers.add_parser("stats", help="Get adapter statistics")
    stats_parser.set_defaults(func=cmd_stats)
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    result = args.func(args)
    sys.exit(result or 0)


if __name__ == "__main__":
    main()
