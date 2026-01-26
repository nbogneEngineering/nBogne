#!/usr/bin/env python3
"""
Mock nBogne Mediator Server for Testing.

This script runs a simple HTTP server that mimics the central nBogne Mediator,
allowing local end-to-end testing of the adapter.

Features:
    - Receives encoded messages from the adapter
    - Decodes and logs message contents
    - Configurable latency simulation (for GPRS testing)
    - Configurable failure rates (for retry testing)
    - Saves received messages to disk

Usage:
    python -m scripts.mock_mediator
    python -m scripts.mock_mediator --port 9000 --latency 2.0
    python -m scripts.mock_mediator --fail-rate 0.3 --latency 1.0
"""

import argparse
import json
import logging
import random
import sys
import time
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from nbogne.wire_format import WireFormat, MessageType

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s"
)
logger = logging.getLogger("mock_mediator")


class MockMediatorHandler(BaseHTTPRequestHandler):
    """HTTP request handler for mock mediator."""
    
    # Class-level configuration (set by main)
    wire_format: WireFormat = None
    latency: float = 0.0
    fail_rate: float = 0.0
    output_dir: Path = None
    message_count: int = 0
    
    def log_message(self, format: str, *args) -> None:
        """Override to use our logger."""
        pass  # Handled in do_POST
    
    def do_GET(self) -> None:
        """Handle GET requests."""
        if self.path == "/health":
            self._send_json(200, {
                "status": "healthy",
                "type": "mock_mediator",
                "messages_received": MockMediatorHandler.message_count,
            })
        elif self.path == "/stats":
            self._send_json(200, {
                "messages_received": MockMediatorHandler.message_count,
                "fail_rate": MockMediatorHandler.fail_rate,
                "latency": MockMediatorHandler.latency,
            })
        else:
            self._send_json(404, {"error": "Not found"})
    
    def do_POST(self) -> None:
        """Handle POST requests (incoming messages from adapter)."""
        # Simulate GPRS latency
        if MockMediatorHandler.latency > 0:
            jitter = random.uniform(0.5, 1.5)  # ±50% jitter
            delay = MockMediatorHandler.latency * jitter
            logger.debug(f"Simulating {delay:.2f}s network latency")
            time.sleep(delay)
        
        # Simulate random failures
        if random.random() < MockMediatorHandler.fail_rate:
            error_codes = [500, 502, 503, 504, 408]
            error_code = random.choice(error_codes)
            logger.warning(f"Simulating failure: HTTP {error_code}")
            self._send_json(error_code, {"error": f"Simulated error {error_code}"})
            return
        
        # Read request body
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            self._send_json(400, {"error": "Empty request"})
            return
        
        body = self.rfile.read(content_length)
        
        # Decode the message
        try:
            header, payload = MockMediatorHandler.wire_format.decode(body)
            
            MockMediatorHandler.message_count += 1
            
            # Log message details
            logger.info(
                f"Received message #{MockMediatorHandler.message_count}: "
                f"id={header.message_id[:8]}..., "
                f"type={header.message_type.name}, "
                f"from={header.source_facility}, "
                f"to={header.destination_facility}, "
                f"size={len(payload)} bytes"
            )
            
            # Try to parse payload as JSON for logging
            try:
                fhir_data = json.loads(payload.decode("utf-8"))
                resource_type = fhir_data.get("resourceType", "Unknown")
                logger.info(f"  FHIR Resource: {resource_type}")
                
                # Log entries if Bundle
                if resource_type == "Bundle" and "entry" in fhir_data:
                    for entry in fhir_data.get("entry", [])[:3]:  # Max 3
                        res = entry.get("resource", {})
                        res_type = res.get("resourceType", "Unknown")
                        res_id = res.get("id", "")[:8]
                        logger.info(f"    - {res_type} ({res_id}...)")
                    if len(fhir_data.get("entry", [])) > 3:
                        logger.info(f"    ... and {len(fhir_data['entry']) - 3} more entries")
                        
            except (json.JSONDecodeError, UnicodeDecodeError):
                logger.info(f"  Payload: (binary, {len(payload)} bytes)")
            
            # Save to disk if output directory configured
            if MockMediatorHandler.output_dir:
                self._save_message(header, payload)
            
            # Send success response
            response = {
                "status": "received",
                "message_id": header.message_id,
                "received_at": datetime.utcnow().isoformat(),
            }
            self._send_json(200, response)
            
        except Exception as e:
            logger.error(f"Failed to decode message: {e}")
            self._send_json(400, {"error": f"Decode error: {e}"})
    
    def _save_message(self, header, payload):
        """Save received message to disk."""
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_{header.message_id[:8]}.json"
        filepath = MockMediatorHandler.output_dir / filename
        
        data = {
            "received_at": datetime.utcnow().isoformat(),
            "header": header.to_dict(),
            "payload_size": len(payload),
        }
        
        # Try to include decoded payload
        try:
            data["payload"] = json.loads(payload.decode("utf-8"))
        except:
            data["payload_base64"] = payload[:1000].hex()  # First 1KB hex
        
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)
        
        logger.debug(f"Saved message to {filepath}")
    
    def _send_json(self, status: int, data: dict) -> None:
        """Send JSON response."""
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    parser = argparse.ArgumentParser(
        description="Mock nBogne Mediator for Testing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Run with defaults
    python -m scripts.mock_mediator
    
    # Simulate slow GPRS (2 second average latency)
    python -m scripts.mock_mediator --latency 2.0
    
    # Simulate 30% failure rate for retry testing
    python -m scripts.mock_mediator --fail-rate 0.3
    
    # Save received messages to disk
    python -m scripts.mock_mediator --output-dir ./received_messages
        """
    )
    
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Bind address (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=9000,
        help="Port number (default: 9000)"
    )
    parser.add_argument(
        "--latency", "-l",
        type=float,
        default=0.0,
        help="Simulated network latency in seconds (default: 0)"
    )
    parser.add_argument(
        "--fail-rate", "-f",
        type=float,
        default=0.0,
        help="Random failure rate 0.0-1.0 (default: 0)"
    )
    parser.add_argument(
        "--output-dir", "-o",
        help="Directory to save received messages"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging"
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Configure handler
    MockMediatorHandler.wire_format = WireFormat()
    MockMediatorHandler.latency = args.latency
    MockMediatorHandler.fail_rate = args.fail_rate
    
    if args.output_dir:
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        MockMediatorHandler.output_dir = output_dir
        logger.info(f"Saving messages to: {output_dir}")
    
    # Start server
    server = HTTPServer((args.host, args.port), MockMediatorHandler)
    
    print()
    print("=" * 60)
    print("  nBogne Mock Mediator")
    print("=" * 60)
    print(f"  Listening: http://{args.host}:{args.port}/gsm/inbound")
    print(f"  Latency:   {args.latency}s (±50% jitter)")
    print(f"  Fail Rate: {args.fail_rate * 100:.0f}%")
    print("=" * 60)
    print()
    print("Configure your adapter with:")
    print(f"  mediator.endpoint: http://localhost:{args.port}/gsm/inbound")
    print()
    print("Press Ctrl+C to stop")
    print()
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()
        print(f"Total messages received: {MockMediatorHandler.message_count}")


if __name__ == "__main__":
    main()
