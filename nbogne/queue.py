"""
SQLite-backed persistent message queue for reliable store-and-forward.

This module provides a durable message queue that survives power failures,
application restarts, and network outages. Messages are persisted to SQLite
and only removed after successful transmission acknowledgment.

This is the CRITICAL component for reliability over unreliable GPRS networks.
The pattern is proven in production systems like CommCare (400M+ users),
ODK (250M+ submissions), and DHIS2 (100+ countries).

Queue States:
    PENDING   -> Message queued, awaiting transmission
    SENDING   -> Transmission in progress
    SENT      -> Successfully transmitted, awaiting ACK (optional)
    ACKED     -> Acknowledged by receiver
    FAILED    -> Transmission failed after all retries
    DEAD      -> Moved to dead letter queue after max failures

Example:
    >>> from nbogne.queue import PersistentQueue
    >>> 
    >>> queue = PersistentQueue("data/outbox.db")
    >>> 
    >>> # Enqueue a message
    >>> item_id = queue.put(
    ...     message_id="550e8400-e29b-41d4-a716-446655440000",
    ...     destination="FAC-002",
    ...     payload=encoded_message,
    ... )
    >>> 
    >>> # Process messages (in queue drainer thread)
    >>> item = queue.get()
    >>> if item:
    ...     try:
    ...         send_via_gprs(item.payload)
    ...         queue.ack(item.id)
    ...     except TransmissionError:
    ...         queue.nack(item.id)
"""

import sqlite3
import threading
import time
import logging
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Optional, List, Iterator, Any
from contextlib import contextmanager

from nbogne.exceptions import (
    QueueError,
    QueueFullError,
    QueueCorruptedError,
)

logger = logging.getLogger(__name__)


class QueueItemStatus(Enum):
    """Status states for queue items."""
    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    ACKED = "acked"
    FAILED = "failed"
    DEAD = "dead"


@dataclass
class QueueItem:
    """Represents a message in the persistent queue.
    
    Attributes:
        id: Auto-generated primary key
        message_id: UUID of the message (from wire format)
        destination: Target facility ID
        payload: Encoded message bytes
        status: Current queue status
        priority: Message priority (higher = more urgent)
        attempts: Number of transmission attempts
        created_at: Timestamp when message was queued
        updated_at: Timestamp of last status change
        next_retry_at: Timestamp for next retry attempt
        last_error: Description of last transmission error
        metadata: Optional JSON metadata
    """
    id: int
    message_id: str
    destination: str
    payload: bytes
    status: QueueItemStatus
    priority: int
    attempts: int
    created_at: datetime
    updated_at: datetime
    next_retry_at: Optional[datetime]
    last_error: Optional[str]
    metadata: Optional[dict]
    
    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "QueueItem":
        """Create QueueItem from a database row."""
        return cls(
            id=row["id"],
            message_id=row["message_id"],
            destination=row["destination"],
            payload=row["payload"],
            status=QueueItemStatus(row["status"]),
            priority=row["priority"],
            attempts=row["attempts"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            next_retry_at=(
                datetime.fromisoformat(row["next_retry_at"])
                if row["next_retry_at"] else None
            ),
            last_error=row["last_error"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else None,
        )


class PersistentQueue:
    """SQLite-backed persistent message queue.
    
    This class provides a durable FIFO queue with priority support,
    retry tracking, and dead letter queue functionality.
    
    Thread Safety:
        This class is thread-safe. It uses SQLite's built-in locking
        and maintains a connection-per-thread model.
    
    Database Schema:
        The queue uses a single table with the following structure:
        
        CREATE TABLE queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id TEXT UNIQUE NOT NULL,
            destination TEXT NOT NULL,
            payload BLOB NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            priority INTEGER NOT NULL DEFAULT 0,
            attempts INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            next_retry_at TEXT,
            last_error TEXT,
            metadata TEXT
        );
    
    Example:
        >>> queue = PersistentQueue("data/outbox.db", max_size=10000)
        >>> 
        >>> # Producer: Add messages
        >>> queue.put(message_id="...", destination="FAC-002", payload=data)
        >>> 
        >>> # Consumer: Process messages
        >>> while True:
        ...     item = queue.get()
        ...     if item is None:
        ...         time.sleep(1)
        ...         continue
        ...     try:
        ...         transmit(item.payload)
        ...         queue.ack(item.id)
        ...     except Exception as e:
        ...         queue.nack(item.id, str(e))
    """
    
    # SQL statements
    CREATE_TABLE_SQL = """
        CREATE TABLE IF NOT EXISTS queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id TEXT UNIQUE NOT NULL,
            destination TEXT NOT NULL,
            payload BLOB NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            priority INTEGER NOT NULL DEFAULT 0,
            attempts INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            next_retry_at TEXT,
            last_error TEXT,
            metadata TEXT
        )
    """
    
    CREATE_INDEXES_SQL = [
        "CREATE INDEX IF NOT EXISTS idx_status ON queue (status)",
        "CREATE INDEX IF NOT EXISTS idx_priority ON queue (priority DESC)",
        "CREATE INDEX IF NOT EXISTS idx_next_retry ON queue (next_retry_at)",
        "CREATE INDEX IF NOT EXISTS idx_destination ON queue (destination)",
        "CREATE INDEX IF NOT EXISTS idx_created ON queue (created_at)",
    ]
    
    def __init__(
        self,
        db_path: str,
        max_size: int = 10000,
        max_retries: int = 10,
        wal_mode: bool = True,
    ):
        """Initialize the persistent queue.
        
        Args:
            db_path: Path to SQLite database file
            max_size: Maximum queue size (0 = unlimited)
            max_retries: Maximum retry attempts before moving to dead letter
            wal_mode: Enable WAL mode for better concurrent performance
        """
        self.db_path = Path(db_path)
        self.max_size = max_size
        self.max_retries = max_retries
        self.wal_mode = wal_mode
        
        # Thread-local storage for connections
        self._local = threading.local()
        self._lock = threading.RLock()
        
        # Ensure parent directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Initialize database
        self._init_db()
        
        logger.info(f"Initialized persistent queue: {self.db_path}")
    
    def _get_connection(self) -> sqlite3.Connection:
        """Get a thread-local database connection."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(
                str(self.db_path),
                timeout=30.0,
                isolation_level=None,  # Autocommit mode
                check_same_thread=False,
            )
            self._local.conn.row_factory = sqlite3.Row
            
            # Enable WAL mode for better concurrency
            if self.wal_mode:
                self._local.conn.execute("PRAGMA journal_mode=WAL")
            
            # Performance optimizations
            self._local.conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn.execute("PRAGMA cache_size=-64000")  # 64MB cache
            
        return self._local.conn
    
    @contextmanager
    def _transaction(self):
        """Context manager for database transactions."""
        conn = self._get_connection()
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    
    def _init_db(self) -> None:
        """Initialize the database schema."""
        conn = self._get_connection()
        try:
            conn.execute(self.CREATE_TABLE_SQL)
            for index_sql in self.CREATE_INDEXES_SQL:
                conn.execute(index_sql)
            logger.debug("Database schema initialized")
        except sqlite3.Error as e:
            raise QueueCorruptedError(
                f"Failed to initialize database: {e}",
                db_path=str(self.db_path)
            )
    
    def put(
        self,
        message_id: str,
        destination: str,
        payload: bytes,
        priority: int = 0,
        metadata: Optional[dict] = None,
    ) -> int:
        """Add a message to the queue.
        
        Args:
            message_id: Unique message identifier (UUID)
            destination: Target facility ID
            payload: Encoded message bytes
            priority: Message priority (higher = more urgent, default 0)
            metadata: Optional metadata dictionary
        
        Returns:
            Queue item ID
        
        Raises:
            QueueFullError: If queue has reached max_size
            QueueError: If insertion fails
        """
        with self._lock:
            # Check queue size
            if self.max_size > 0:
                current_size = self.size()
                if current_size >= self.max_size:
                    raise QueueFullError(self.max_size, current_size)
            
            now = datetime.utcnow().isoformat()
            
            try:
                with self._transaction() as conn:
                    cursor = conn.execute(
                        """
                        INSERT INTO queue 
                            (message_id, destination, payload, status, priority,
                             attempts, created_at, updated_at, metadata)
                        VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?)
                        """,
                        (
                            message_id,
                            destination,
                            payload,
                            QueueItemStatus.PENDING.value,
                            priority,
                            now,
                            now,
                            json.dumps(metadata) if metadata else None,
                        )
                    )
                    item_id = cursor.lastrowid
                    
                logger.debug(
                    f"Queued message: id={item_id}, message_id={message_id[:8]}..., "
                    f"destination={destination}, size={len(payload)} bytes"
                )
                return item_id
                
            except sqlite3.IntegrityError:
                # Duplicate message_id - message already queued
                logger.warning(f"Duplicate message_id: {message_id}")
                cursor = self._get_connection().execute(
                    "SELECT id FROM queue WHERE message_id = ?",
                    (message_id,)
                )
                row = cursor.fetchone()
                return row["id"] if row else -1
                
            except sqlite3.Error as e:
                raise QueueError(f"Failed to enqueue message: {e}")
    
    def get(
        self,
        destination: Optional[str] = None,
        lock_timeout: float = 60.0,
    ) -> Optional[QueueItem]:
        """Get the next message ready for transmission.
        
        This method atomically retrieves and locks the next pending message,
        marking it as SENDING to prevent duplicate processing.
        
        Args:
            destination: Optional filter by destination
            lock_timeout: Seconds before locked items are considered stale
        
        Returns:
            QueueItem if available, None if queue is empty
        """
        now = datetime.utcnow()
        now_iso = now.isoformat()
        
        # Also check for stale SENDING items (stuck in transmission)
        stale_cutoff = (now - timedelta(seconds=lock_timeout)).isoformat()
        
        with self._lock:
            try:
                with self._transaction() as conn:
                    # Build query
                    query = """
                        SELECT * FROM queue
                        WHERE (
                            status = ?
                            OR (status = ? AND updated_at < ?)
                        )
                        AND (next_retry_at IS NULL OR next_retry_at <= ?)
                    """
                    params: List[Any] = [
                        QueueItemStatus.PENDING.value,
                        QueueItemStatus.SENDING.value,
                        stale_cutoff,
                        now_iso,
                    ]
                    
                    if destination:
                        query += " AND destination = ?"
                        params.append(destination)
                    
                    query += " ORDER BY priority DESC, id ASC LIMIT 1"
                    
                    cursor = conn.execute(query, params)
                    row = cursor.fetchone()
                    
                    if not row:
                        return None
                    
                    # Mark as SENDING
                    conn.execute(
                        """
                        UPDATE queue
                        SET status = ?, updated_at = ?, attempts = attempts + 1
                        WHERE id = ?
                        """,
                        (QueueItemStatus.SENDING.value, now_iso, row["id"])
                    )
                    
                    # Re-fetch with updated values
                    cursor = conn.execute(
                        "SELECT * FROM queue WHERE id = ?",
                        (row["id"],)
                    )
                    row = cursor.fetchone()
                    
                return QueueItem.from_row(row)
                
            except sqlite3.Error as e:
                raise QueueError(f"Failed to get message from queue: {e}")
    
    def get_batch(
        self,
        batch_size: int = 10,
        destination: Optional[str] = None,
    ) -> List[QueueItem]:
        """Get a batch of messages for transmission.
        
        Args:
            batch_size: Maximum number of messages to retrieve
            destination: Optional filter by destination
        
        Returns:
            List of QueueItems (may be empty)
        """
        items = []
        for _ in range(batch_size):
            item = self.get(destination=destination)
            if item is None:
                break
            items.append(item)
        return items
    
    def ack(self, item_id: int) -> None:
        """Acknowledge successful transmission of a message.
        
        This marks the message as ACKED. Depending on retention settings,
        the message may be kept for audit purposes or deleted immediately.
        
        Args:
            item_id: Queue item ID to acknowledge
        """
        now = datetime.utcnow().isoformat()
        
        try:
            self._get_connection().execute(
                """
                UPDATE queue
                SET status = ?, updated_at = ?, last_error = NULL
                WHERE id = ?
                """,
                (QueueItemStatus.ACKED.value, now, item_id)
            )
            logger.debug(f"Acknowledged queue item: {item_id}")
            
        except sqlite3.Error as e:
            raise QueueError(f"Failed to acknowledge message: {e}")
    
    def nack(
        self,
        item_id: int,
        error: Optional[str] = None,
        retry_delay: Optional[float] = None,
    ) -> None:
        """Mark a message as failed and schedule retry.
        
        This method calculates the next retry time using exponential backoff
        and updates the queue item. If max_retries is exceeded, the message
        is moved to DEAD status.
        
        Args:
            item_id: Queue item ID that failed
            error: Optional error description
            retry_delay: Optional specific retry delay (otherwise calculated)
        """
        now = datetime.utcnow()
        now_iso = now.isoformat()
        
        try:
            # Get current attempt count
            cursor = self._get_connection().execute(
                "SELECT attempts FROM queue WHERE id = ?",
                (item_id,)
            )
            row = cursor.fetchone()
            
            if not row:
                logger.warning(f"Queue item not found for nack: {item_id}")
                return
            
            attempts = row["attempts"]
            
            # Check if max retries exceeded
            if attempts >= self.max_retries:
                logger.warning(
                    f"Max retries exceeded for item {item_id}, "
                    f"moving to dead letter queue"
                )
                self._get_connection().execute(
                    """
                    UPDATE queue
                    SET status = ?, updated_at = ?, last_error = ?
                    WHERE id = ?
                    """,
                    (QueueItemStatus.DEAD.value, now_iso, error, item_id)
                )
                return
            
            # Calculate retry delay with exponential backoff + jitter
            if retry_delay is None:
                import random
                base_delay = 3.0
                max_delay = 300.0
                delay = random.uniform(0, min(max_delay, base_delay * (2 ** attempts)))
                retry_delay = delay
            
            next_retry = (now + timedelta(seconds=retry_delay)).isoformat()
            
            self._get_connection().execute(
                """
                UPDATE queue
                SET status = ?, updated_at = ?, next_retry_at = ?, last_error = ?
                WHERE id = ?
                """,
                (
                    QueueItemStatus.PENDING.value,
                    now_iso,
                    next_retry,
                    error,
                    item_id,
                )
            )
            
            logger.debug(
                f"Nacked queue item: {item_id}, attempt {attempts}, "
                f"next retry in {retry_delay:.1f}s"
            )
            
        except sqlite3.Error as e:
            raise QueueError(f"Failed to nack message: {e}")
    
    def size(self, status: Optional[QueueItemStatus] = None) -> int:
        """Get the current queue size.
        
        Args:
            status: Optional filter by status
        
        Returns:
            Number of items in queue
        """
        try:
            if status:
                cursor = self._get_connection().execute(
                    "SELECT COUNT(*) as count FROM queue WHERE status = ?",
                    (status.value,)
                )
            else:
                cursor = self._get_connection().execute(
                    "SELECT COUNT(*) as count FROM queue"
                )
            return cursor.fetchone()["count"]
            
        except sqlite3.Error as e:
            raise QueueError(f"Failed to get queue size: {e}")
    
    def peek(self, item_id: int) -> Optional[QueueItem]:
        """Get a queue item without modifying its status.
        
        Args:
            item_id: Queue item ID
        
        Returns:
            QueueItem if found, None otherwise
        """
        try:
            cursor = self._get_connection().execute(
                "SELECT * FROM queue WHERE id = ?",
                (item_id,)
            )
            row = cursor.fetchone()
            return QueueItem.from_row(row) if row else None
            
        except sqlite3.Error as e:
            raise QueueError(f"Failed to peek queue item: {e}")
    
    def delete(self, item_id: int) -> bool:
        """Delete a queue item.
        
        Args:
            item_id: Queue item ID to delete
        
        Returns:
            True if item was deleted, False if not found
        """
        try:
            cursor = self._get_connection().execute(
                "DELETE FROM queue WHERE id = ?",
                (item_id,)
            )
            deleted = cursor.rowcount > 0
            if deleted:
                logger.debug(f"Deleted queue item: {item_id}")
            return deleted
            
        except sqlite3.Error as e:
            raise QueueError(f"Failed to delete queue item: {e}")
    
    def purge(
        self,
        status: Optional[QueueItemStatus] = None,
        older_than: Optional[datetime] = None,
    ) -> int:
        """Purge items from the queue.
        
        Args:
            status: Only purge items with this status
            older_than: Only purge items older than this datetime
        
        Returns:
            Number of items purged
        """
        conditions = []
        params: List[Any] = []
        
        if status:
            conditions.append("status = ?")
            params.append(status.value)
        
        if older_than:
            conditions.append("created_at < ?")
            params.append(older_than.isoformat())
        
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        try:
            cursor = self._get_connection().execute(
                f"DELETE FROM queue WHERE {where_clause}",
                params
            )
            count = cursor.rowcount
            logger.info(f"Purged {count} items from queue")
            return count
            
        except sqlite3.Error as e:
            raise QueueError(f"Failed to purge queue: {e}")
    
    def get_stats(self) -> dict:
        """Get queue statistics.
        
        Returns:
            Dictionary with queue statistics
        """
        try:
            conn = self._get_connection()
            
            # Count by status
            cursor = conn.execute(
                """
                SELECT status, COUNT(*) as count
                FROM queue
                GROUP BY status
                """
            )
            status_counts = {row["status"]: row["count"] for row in cursor.fetchall()}
            
            # Get oldest and newest
            cursor = conn.execute(
                "SELECT MIN(created_at) as oldest, MAX(created_at) as newest FROM queue"
            )
            row = cursor.fetchone()
            
            return {
                "total": sum(status_counts.values()),
                "by_status": status_counts,
                "oldest": row["oldest"],
                "newest": row["newest"],
                "max_size": self.max_size,
                "max_retries": self.max_retries,
                "db_path": str(self.db_path),
            }
            
        except sqlite3.Error as e:
            raise QueueError(f"Failed to get queue stats: {e}")
    
    def iter_items(
        self,
        status: Optional[QueueItemStatus] = None,
        limit: int = 100,
    ) -> Iterator[QueueItem]:
        """Iterate over queue items.
        
        Args:
            status: Optional filter by status
            limit: Maximum number of items to yield
        
        Yields:
            QueueItem instances
        """
        try:
            if status:
                cursor = self._get_connection().execute(
                    "SELECT * FROM queue WHERE status = ? ORDER BY id LIMIT ?",
                    (status.value, limit)
                )
            else:
                cursor = self._get_connection().execute(
                    "SELECT * FROM queue ORDER BY id LIMIT ?",
                    (limit,)
                )
            
            for row in cursor.fetchall():
                yield QueueItem.from_row(row)
                
        except sqlite3.Error as e:
            raise QueueError(f"Failed to iterate queue: {e}")
    
    def close(self) -> None:
        """Close the database connection."""
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None
            logger.debug("Closed database connection")
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
