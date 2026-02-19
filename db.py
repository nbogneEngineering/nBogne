"""
nBogne Transport — Database
Persistent outbox queue, transaction log, device state.
WAL mode for safe concurrent reads from watchdog + main loop.
"""

import sqlite3
import json
import uuid
import random
from datetime import datetime, timedelta
from pathlib import Path
import config


def get_db():
    Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    _ensure_tables(conn)
    return conn


def _ensure_tables(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS outbox (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        record_id    TEXT UNIQUE NOT NULL,
        payload      TEXT NOT NULL,
        priority     INTEGER DEFAULT 0,
        created_at   TEXT DEFAULT (datetime('now')),
        status       TEXT DEFAULT 'pending',
        channel      TEXT,
        retry_count  INTEGER DEFAULT 0,
        next_retry   TEXT,
        last_attempt TEXT,
        acked_at     TEXT,
        server_ack   TEXT
    );
    CREATE TABLE IF NOT EXISTS tx_log (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        record_id   TEXT NOT NULL,
        channel     TEXT NOT NULL,
        attempted   TEXT DEFAULT (datetime('now')),
        success     INTEGER NOT NULL,
        error_code  TEXT,
        rssi        INTEGER,
        duration_ms INTEGER
    );
    CREATE TABLE IF NOT EXISTS device_state (
        id              INTEGER PRIMARY KEY CHECK (id = 1),
        gprs_ok         INTEGER DEFAULT 0,
        rssi            INTEGER DEFAULT 0,
        registered      INTEGER DEFAULT 0,
        last_success    TEXT,
        last_channel    TEXT,
        consec_fails    INTEGER DEFAULT 0,
        boot_count      INTEGER DEFAULT 0
    );
    INSERT OR IGNORE INTO device_state (id) VALUES (1);
    CREATE INDEX IF NOT EXISTS idx_outbox_status ON outbox(status, next_retry);
    """)
    conn.commit()


# ── Outbox ───────────────────────────────────────────────────

def enqueue(payload: dict, priority: int = 0, record_id: str = None) -> str:
    rid = record_id or uuid.uuid4().hex[:8]
    db = get_db()
    db.execute(
        """INSERT OR IGNORE INTO outbox
           (record_id, payload, priority, status, next_retry)
           VALUES (?, ?, ?, 'pending', datetime('now'))""",
        (rid, json.dumps(payload), priority)
    )
    db.commit()
    db.close()
    return rid


def get_pending(limit: int = 10) -> list:
    db = get_db()
    rows = db.execute(
        """SELECT * FROM outbox
           WHERE status IN ('pending','failed')
             AND (next_retry IS NULL OR next_retry <= datetime('now'))
             AND retry_count < ?
           ORDER BY priority DESC, created_at
           LIMIT ?""",
        (config.RETRY_MAX_ATTEMPTS, limit)
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


def mark_sending(record_id: str):
    db = get_db()
    db.execute("UPDATE outbox SET status='sending', last_attempt=datetime('now') WHERE record_id=?",
               (record_id,))
    db.commit(); db.close()


def mark_sent(record_id: str, channel: str, server_ack: str = ''):
    db = get_db()
    db.execute(
        "UPDATE outbox SET status='acked', channel=?, acked_at=datetime('now'), server_ack=? WHERE record_id=?",
        (channel, server_ack, record_id))
    db.commit(); db.close()


def mark_failed(record_id: str, error: str = ''):
    db = get_db()
    row = db.execute("SELECT retry_count FROM outbox WHERE record_id=?", (record_id,)).fetchone()
    if row:
        count = row['retry_count'] + 1
        delay = min(config.RETRY_BASE_SECONDS * (2 ** count), config.RETRY_MAX_SECONDS)
        jittered = random.uniform(0, delay)
        nxt = (datetime.utcnow() + timedelta(seconds=jittered)).strftime('%Y-%m-%d %H:%M:%S')
        db.execute("UPDATE outbox SET status='failed', retry_count=?, next_retry=? WHERE record_id=?",
                   (count, nxt, record_id))
    db.commit(); db.close()


def pending_count() -> int:
    db = get_db()
    r = db.execute("SELECT COUNT(*) c FROM outbox WHERE status IN ('pending','failed') AND retry_count<?",
                   (config.RETRY_MAX_ATTEMPTS,)).fetchone()
    db.close()
    return r['c']


# ── Transaction Log ──────────────────────────────────────────

def log_tx(record_id, channel, success, error='', rssi=0, duration_ms=0):
    db = get_db()
    db.execute("INSERT INTO tx_log (record_id,channel,success,error_code,rssi,duration_ms) VALUES (?,?,?,?,?,?)",
               (record_id, channel, int(success), error, rssi, duration_ms))
    db.commit(); db.close()


# ── Device State ─────────────────────────────────────────────

def update_state(**kw):
    db = get_db()
    sets = ', '.join(f'{k}=?' for k in kw)
    db.execute(f"UPDATE device_state SET {sets} WHERE id=1", list(kw.values()))
    db.commit(); db.close()


def get_state() -> dict:
    db = get_db()
    r = db.execute("SELECT * FROM device_state WHERE id=1").fetchone()
    db.close()
    return dict(r) if r else {}
