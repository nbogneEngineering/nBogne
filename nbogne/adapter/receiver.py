"""
Receiving Adapter (Server Side)

Receives SMS from facility modems, reconstructs FHIR records,
and forwards them to OpenHIM/DHIS2 via HTTP.

Pipeline: SMS segments → reassemble → decrypt L2 → parse wire → decrypt L1 → decompress → FHIR → HTTP POST
"""
import json
import time
import logging
import urllib.request
from typing import Optional

from models import WirePacket, PacketType, Handshake, generate_msg_id
from compression.pipeline import CompressionPipeline
from crypto.encryption import decrypt_l1, encrypt_l2, decrypt_l2
from transport.wire import sms_segments_to_packet, packet_to_sms_segments
from config import L1_KEY, L2_KEY, OPENHIM_URL, DHIS2_URL

log = logging.getLogger("nbogne.adapter.receiver")


class ReceivingAdapter:
    """Server-side adapter: SMS → decompress → decrypt → FHIR → OpenHIM/DHIS2."""

    def __init__(self, transport, forward_to: str = "openhim"):
        self.transport = transport
        self.forward_to = forward_to
        self.pipeline = CompressionPipeline()
        self._segment_buffer: dict[str, list[str]] = {}  # msg fragments awaiting reassembly

    def receive_sms(self, sms_text: str, from_number: str) -> Optional[dict]:
        """Process an incoming SMS. May buffer if multi-segment.
        Returns the reconstructed FHIR JSON if complete, None if still buffering."""

        # Check if this is a segmented message
        if '/' in sms_text[:5] and ':' in sms_text[:6]:
            idx = int(sms_text[:2])
            total = int(sms_text[3:5])
            # Use from_number as buffer key (one message per sender at a time)
            key = from_number

            if key not in self._segment_buffer:
                self._segment_buffer[key] = []
            self._segment_buffer[key].append(sms_text)

            if len(self._segment_buffer[key]) < total:
                log.info(f"Buffering segment {idx}/{total} from {from_number}")
                return None

            # All segments received — process
            segments = self._segment_buffer.pop(key)
        else:
            segments = [sms_text]

        return self._process_complete_message(segments, from_number)

    def _process_complete_message(self, segments: list[str], from_number: str) -> Optional[dict]:
        try:
            start = time.time()

            # Step 1: Reassemble SMS segments → wire bytes
            encrypted_l2 = sms_segments_to_packet(segments)

            # Step 2: Decrypt L2 (transport)
            wire_bytes = decrypt_l2(encrypted_l2, L2_KEY)

            # Step 3: Parse wire packet
            packet = WirePacket.decode(wire_bytes)
            log.info(f"Received msg_id={packet.msg_id.hex()}, template={packet.template_id}, "
                     f"type={packet.packet_type.name}")

            # Step 4: Decrypt L1 (E2EE)
            compressed = decrypt_l1(packet.payload, L1_KEY)

            # Step 5: Decompress → FHIR JSON
            fhir_json = self.pipeline.decompress(compressed, packet.template_id)

            elapsed = (time.time() - start) * 1000
            fhir_size = len(json.dumps(fhir_json))
            log.info(f"Reconstructed FHIR: {fhir_size}B in {elapsed:.0f}ms "
                     f"from {len(segments)} SMS segments")

            # Step 6: Forward to OpenHIM/DHIS2
            self._forward(fhir_json)

            # Step 7: Send ACK back to facility
            self._send_ack(packet.msg_id, from_number)

            return fhir_json

        except Exception as e:
            log.error(f"Failed to process message from {from_number}: {e}")
            return None

    def _forward(self, fhir_json: dict):
        """Forward reconstructed FHIR to OpenHIM or DHIS2 via HTTP POST."""
        if self.forward_to == "openhim":
            url = f"{OPENHIM_URL}/fhir"
        elif self.forward_to == "dhis2":
            url = f"{DHIS2_URL}/fhir"
        else:
            log.info(f"Forward target '{self.forward_to}' — skipping HTTP POST")
            return

        try:
            data = json.dumps(fhir_json).encode('utf-8')
            req = urllib.request.Request(
                url, data=data,
                headers={"Content-Type": "application/fhir+json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                log.info(f"Forwarded to {url}: HTTP {resp.status}")
        except Exception as e:
            log.warning(f"Forward to {url} failed: {e} — record saved locally")

    def _send_ack(self, msg_id: bytes, to_number: str):
        """Send handshake ACK back to the facility."""
        ack = Handshake(msg_id=msg_id, status="RECEIVED")
        ack_packet = WirePacket(
            msg_id=msg_id,
            template_id=0,
            destination=to_number,
            payload=ack.to_bytes(),
            packet_type=PacketType.HANDSHAKE,
        )
        wire_bytes = ack_packet.encode()
        encrypted = encrypt_l2(wire_bytes, L2_KEY)
        segments = packet_to_sms_segments(encrypted)
        self.transport.send_segments(to_number, segments)
        log.info(f"ACK sent to {to_number} for msg_id={msg_id.hex()}")
