"""
Persistent Transmission Queue

SQLite-backed queue that survives power loss.
Handles retry logic with configurable max retries.
"""
import sqlite3
import time
import json
import logging
from pathlib import Path
from typing import Optional
from config import DB_PATH, MAX_RETRIES, RETRY_INTERVAL_SECONDS

log = logging.getLogger("nbogne.transport.queue")


class TransmissionQueue:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS queue (
                    id TEXT PRIMARY KEY,
                    msg_id BLOB,
                    destination TEXT,
                    wire_data BLOB,
                    segments_json TEXT,
                    patient_record_id TEXT,
                    fhir_resource_type TEXT,
                    raw_size INTEGER,
                    compressed_size INTEGER,
                    wire_size INTEGER,
                    sms_segment_count INTEGER,
                    template_id INTEGER,
                    status TEXT DEFAULT 'PENDING',
                    created_at REAL,
                    last_attempt_at REAL,
                    completed_at REAL,
                    retry_count INTEGER DEFAULT 0,
                    error TEXT DEFAULT '',
                    carrier TEXT DEFAULT ''
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_status ON queue(status)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_msg_id ON queue(msg_id)")

    def enqueue(self, id: str, msg_id: bytes, destination: str, wire_data: bytes,
                segments: list[bytes], patient_record_id: str = "",
                fhir_resource_type: str = "", raw_size: int = 0,
                compressed_size: int = 0, template_id: int = 0):
        """Add a transmission to the queue."""
        # Hex-encode binary segments for JSON storage
        segments_hex = [seg.hex() for seg in segments]
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO queue
                (id, msg_id, destination, wire_data, segments_json,
                 patient_record_id, fhir_resource_type, raw_size, compressed_size,
                 wire_size, sms_segment_count, template_id, status, created_at, retry_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, 0)
            """, (id, msg_id, destination, wire_data, json.dumps(segments_hex),
                  patient_record_id, fhir_resource_type, raw_size, compressed_size,
                  len(wire_data), len(segments), template_id, time.time()))
        log.info(
            f"Enqueued {id}: {len(segments)} segments, {len(wire_data)}B wire")

    def get_pending(self) -> list[dict]:
        """Get all pending transmissions ready for (re)sending."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT * FROM queue
                WHERE status IN ('PENDING', 'RETRY')
                AND retry_count < ?
                AND (last_attempt_at IS NULL OR last_attempt_at < ?)
                ORDER BY created_at ASC
            """, (MAX_RETRIES, time.time() - RETRY_INTERVAL_SECONDS)).fetchall()
        return [dict(r) for r in rows]

    def mark_sending(self, id: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE queue SET status='SENDING', last_attempt_at=? WHERE id=?",
                         (time.time(), id))

    def mark_sent(self, id: str):
        """Mark as sent (awaiting ACK)."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE queue SET status='SENT' WHERE id=?", (id,))

    def mark_complete(self, msg_id: bytes):
        """Mark as complete (ACK received)."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE queue SET status='COMPLETE', completed_at=? WHERE msg_id=?",
                         (time.time(), msg_id))
        log.info(f"Transmission complete: msg_id={msg_id.hex()}")

    def mark_retry(self, id: str, error: str = ""):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE queue SET status='RETRY', retry_count=retry_count+1, error=?
                WHERE id=?
            """, (error, id))

    def mark_failed(self, id: str, error: str = ""):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE queue SET status='FAILED', error=? WHERE id=?",
                         (error, id))
        log.warning(f"Transmission failed: {id} - {error}")

    def get_by_msg_id(self, msg_id: bytes) -> Optional[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM queue WHERE msg_id=?", (msg_id,)).fetchone()
        return dict(row) if row else None

    def get_stats(self) -> dict:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) as cnt FROM queue GROUP BY status").fetchall()
        return {r[0]: r[1] for r in rows}

    def cleanup_completed(self, older_than_hours: int = 24):
        cutoff = time.time() - (older_than_hours * 3600)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "DELETE FROM queue WHERE status='COMPLETE' AND completed_at < ?", (cutoff,))
