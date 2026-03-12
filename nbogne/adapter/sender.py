"""
Sending Adapter (Facility Side)

The main orchestrator at the facility. Takes FHIR JSON from the EMR,
runs it through the full pipeline, and sends via SMS.

Pipeline: FHIR JSON → compress → encrypt L1 → wire packet → encrypt L2 → SMS segments → send
"""
import json
import time
import logging
from typing import Optional

from models import WirePacket, PacketType, Handshake, generate_msg_id
from compression.pipeline import CompressionPipeline
from crypto.encryption import encrypt_l1, decrypt_l2, encrypt_l2
from transport.wire import packet_to_sms_segments, sms_segments_to_packet
from transport.queue import TransmissionQueue
from logging_db.transmission_log import TransmissionLog
from config import L1_KEY, L2_KEY, DESTINATION_NUMBER

log = logging.getLogger("nbogne.adapter.sender")


class SendingAdapter:
    """Facility-side adapter: EMR → compress → encrypt → SMS."""

    def __init__(self, transport, destination: str = DESTINATION_NUMBER):
        self.transport = transport  # GammuTransport or LoopbackTransport
        self.destination = destination
        self.pipeline = CompressionPipeline()
        self.queue = TransmissionQueue()
        self.tx_log = TransmissionLog()

    def send_record(self, fhir_json: dict, patient_record_id: str = "") -> str:
        """Send a FHIR record through the full pipeline. Returns queue ID."""
        start = time.time()

        # Step 1: Compress
        result = self.pipeline.compress(fhir_json)
        log.info(f"Compressed: {result.original_size}B → {result.compressed_size}B "
                 f"({result.ratio:.1f}x, method={result.method})")

        # Step 2: Encrypt L1 (E2EE)
        encrypted_l1 = encrypt_l1(result.compressed, L1_KEY)

        # Step 3: Build wire packet
        msg_id = generate_msg_id()
        ptype = PacketType.TEMPLATED if result.template_id > 0 else PacketType.FALLBACK
        packet = WirePacket(
            msg_id=msg_id,
            template_id=result.template_id,
            destination=self.destination,
            payload=encrypted_l1,
            packet_type=ptype,
        )
        wire_bytes = packet.encode()

        # Step 4: Encrypt L2 (transport)
        encrypted_l2 = encrypt_l2(wire_bytes, L2_KEY)

        # Step 5: Segment for SMS
        segments = packet_to_sms_segments(encrypted_l2)

        # Step 6: Enqueue
        queue_id = f"tx_{msg_id.hex()}_{int(time.time())}"
        self.queue.enqueue(
            id=queue_id,
            msg_id=msg_id,
            destination=self.destination,
            wire_data=encrypted_l2,
            segments=segments,
            patient_record_id=patient_record_id,
            fhir_resource_type=fhir_json.get("resourceType", ""),
            raw_size=result.original_size,
            compressed_size=result.compressed_size,
            template_id=result.template_id,
        )

        # Step 7: Send immediately
        self._send_from_queue(queue_id, segments, msg_id, result, patient_record_id)

        elapsed = (time.time() - start) * 1000
        log.info(f"Pipeline complete in {elapsed:.0f}ms: {result.original_size}B → "
                 f"{len(encrypted_l2)}B wire → {len(segments)} SMS")

        return queue_id

    def _send_from_queue(self, queue_id: str, segments: list[str],
                         msg_id: bytes, result, patient_record_id: str):
        self.queue.mark_sending(queue_id)

        # Log the attempt
        self.tx_log.log_send(
            msg_id=msg_id.hex(),
            patient_record_id=patient_record_id,
            destination=self.destination,
            payload_bytes=result.original_size,
            compressed_bytes=result.compressed_size,
            sms_segments=len(segments),
            template_id=result.template_id,
            compression_ratio=result.ratio,
        )

        # Send via transport
        success = self.transport.send_segments(self.destination, segments)

        if success:
            self.queue.mark_sent(queue_id)
            self.tx_log.log_outcome(msg_id.hex(), "SENT")
            log.info(f"Sent {len(segments)} SMS segments for msg_id={msg_id.hex()}")
        else:
            self.queue.mark_retry(queue_id, "SMS send failed")
            self.tx_log.log_outcome(msg_id.hex(), "FAILED", error_code="SEND_FAIL")
            log.warning(f"Send failed for {queue_id}, will retry")

    def process_incoming_sms(self, sms_text: str, from_number: str):
        """Process incoming SMS (handshake ACK from server)."""
        try:
            wire_bytes = sms_segments_to_packet([sms_text])
            decrypted = decrypt_l2(wire_bytes, L2_KEY)
            packet = WirePacket.decode(decrypted)

            if packet.packet_type == PacketType.HANDSHAKE:
                ack = Handshake.from_bytes(packet.payload)
                self.queue.mark_complete(ack.msg_id)
                elapsed = (time.time() - ack.timestamp) * 1000
                self.tx_log.log_outcome(
                    ack.msg_id.hex(), "SUCCESS",
                    handshake_latency_ms=elapsed
                )
                log.info(f"ACK received for msg_id={ack.msg_id.hex()} ({elapsed:.0f}ms)")
        except Exception as e:
            log.error(f"Failed to process incoming SMS: {e}")

    def retry_pending(self):
        """Retry any pending/failed transmissions."""
        pending = self.queue.get_pending()
        for item in pending:
            segments = json.loads(item["segments_json"])
            log.info(f"Retrying {item['id']} (attempt {item['retry_count'] + 1})")
            self.queue.mark_sending(item["id"])
            success = self.transport.send_segments(item["destination"], segments)
            if success:
                self.queue.mark_sent(item["id"])
            else:
                if item["retry_count"] + 1 >= 5:  # MAX_RETRIES
                    self.queue.mark_failed(item["id"], "Max retries exceeded")
                else:
                    self.queue.mark_retry(item["id"], "Retry failed")

    def get_status(self) -> dict:
        return {
            "queue": self.queue.get_stats(),
            "log": self.tx_log.get_stats(),
        }
