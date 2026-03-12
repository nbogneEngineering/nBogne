"""
Transmission Logging (WS0)

Logs every SMS send attempt with full context.
This data feeds future ML models for smart routing.
"""
import sqlite3
import time
from pathlib import Path
from config import DB_PATH


class TransmissionLog:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS transmission_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL,
                    msg_id TEXT,
                    patient_record_id TEXT,
                    carrier TEXT,
                    destination TEXT,
                    payload_bytes INTEGER,
                    compressed_bytes INTEGER,
                    wire_bytes INTEGER,
                    sms_segments INTEGER,
                    template_id INTEGER,
                    compression_ratio REAL,
                    channel TEXT DEFAULT 'SMS',
                    attempt_number INTEGER,
                    signal_strength INTEGER,
                    time_of_day TEXT,
                    day_of_week TEXT,
                    queue_depth INTEGER,
                    outcome TEXT,
                    latency_ms REAL,
                    error_code TEXT,
                    handshake_latency_ms REAL,
                    quality_score REAL
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_log_ts ON transmission_log(timestamp)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_log_carrier ON transmission_log(carrier)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_log_outcome ON transmission_log(outcome)")

    def log_send(self, msg_id: str, patient_record_id: str = "",
                 carrier: str = "", destination: str = "",
                 payload_bytes: int = 0, compressed_bytes: int = 0,
                 wire_bytes: int = 0, sms_segments: int = 0,
                 template_id: int = 0, compression_ratio: float = 0.0,
                 attempt_number: int = 1, signal_strength: int = 0,
                 queue_depth: int = 0):
        now = time.time()
        t = time.localtime(now)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO transmission_log
                (timestamp, msg_id, patient_record_id, carrier, destination,
                 payload_bytes, compressed_bytes, wire_bytes, sms_segments,
                 template_id, compression_ratio, attempt_number, signal_strength,
                 time_of_day, day_of_week, queue_depth, outcome)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'SENDING')
            """, (now, msg_id, patient_record_id, carrier, destination,
                  payload_bytes, compressed_bytes, wire_bytes, sms_segments,
                  template_id, compression_ratio, attempt_number, signal_strength,
                  f"{t.tm_hour:02d}:{t.tm_min:02d}",
                  ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][t.tm_wday],
                  queue_depth))

    def log_outcome(self, msg_id: str, outcome: str, latency_ms: float = 0,
                    error_code: str = "", handshake_latency_ms: float = 0):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE transmission_log
                SET outcome=?, latency_ms=?, error_code=?, handshake_latency_ms=?
                WHERE id = (
                    SELECT id FROM transmission_log
                    WHERE msg_id=? AND outcome='SENDING'
                    ORDER BY timestamp DESC LIMIT 1
                )
            """, (outcome, latency_ms, error_code, handshake_latency_ms, msg_id))

    def get_stats(self) -> dict:
        with sqlite3.connect(self.db_path) as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM transmission_log").fetchone()[0]
            success = conn.execute(
                "SELECT COUNT(*) FROM transmission_log WHERE outcome='SUCCESS'").fetchone()[0]
            avg_latency = conn.execute(
                "SELECT AVG(latency_ms) FROM transmission_log WHERE outcome='SUCCESS'").fetchone()[0]
            avg_ratio = conn.execute(
                "SELECT AVG(compression_ratio) FROM transmission_log WHERE compression_ratio > 0").fetchone()[0]
        return {
            "total_transmissions": total,
            "successful": success,
            "success_rate": success / total if total else 0,
            "avg_latency_ms": avg_latency or 0,
            "avg_compression_ratio": avg_ratio or 0,
        }
