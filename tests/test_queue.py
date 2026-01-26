"""
Tests for the persistent queue module.

These tests verify:
    - Message persistence across restarts
    - Atomic get/ack/nack operations
    - Retry scheduling with backoff
    - Dead letter queue behavior
    - Thread safety
"""

import pytest
import tempfile
import time
import threading
from pathlib import Path
from datetime import datetime, timedelta

from nbogne.queue import PersistentQueue, QueueItem, QueueItemStatus
from nbogne.exceptions import QueueError, QueueFullError


class TestPersistentQueue:
    """Test suite for PersistentQueue class."""
    
    @pytest.fixture
    def queue(self, tmp_path):
        """Create a temporary queue for testing."""
        db_path = tmp_path / "test_queue.db"
        q = PersistentQueue(str(db_path), max_size=100, max_retries=3)
        yield q
        q.close()
    
    @pytest.fixture
    def sample_payload(self):
        """Create sample payload data."""
        return b"test message payload"
    
    def test_put_and_get(self, queue, sample_payload):
        """Test basic put and get operations."""
        # Put a message
        queue_id = queue.put(
            message_id="msg-001",
            destination="FAC-002",
            payload=sample_payload,
        )
        
        assert queue_id > 0
        
        # Get the message
        item = queue.get()
        
        assert item is not None
        assert item.message_id == "msg-001"
        assert item.destination == "FAC-002"
        assert item.payload == sample_payload
        assert item.status == QueueItemStatus.SENDING
        assert item.attempts == 1
    
    def test_ack_removes_from_pending(self, queue, sample_payload):
        """Test that ack marks message as acknowledged."""
        queue.put(
            message_id="msg-001",
            destination="FAC-002",
            payload=sample_payload,
        )
        
        item = queue.get()
        queue.ack(item.id)
        
        # Should not get the same message again
        next_item = queue.get()
        assert next_item is None
        
        # Verify status changed
        acked_item = queue.peek(item.id)
        assert acked_item.status == QueueItemStatus.ACKED
    
    def test_nack_schedules_retry(self, queue, sample_payload):
        """Test that nack schedules a retry."""
        queue.put(
            message_id="msg-001",
            destination="FAC-002",
            payload=sample_payload,
        )
        
        item = queue.get()
        queue.nack(item.id, error="Network timeout")
        
        # Verify status and error
        nacked_item = queue.peek(item.id)
        assert nacked_item.status == QueueItemStatus.PENDING
        assert nacked_item.last_error == "Network timeout"
        assert nacked_item.next_retry_at is not None
    
    def test_max_retries_moves_to_dead(self, queue, sample_payload):
        """Test that exceeding max retries moves to dead letter."""
        queue.put(
            message_id="msg-001",
            destination="FAC-002",
            payload=sample_payload,
        )
        
        # Exhaust all retries
        for _ in range(queue.max_retries + 1):
            item = queue.get()
            if item:
                queue.nack(item.id, error="Still failing", retry_delay=0)
        
        # Should be in dead letter queue now
        item = queue.peek(1)
        assert item.status == QueueItemStatus.DEAD
    
    def test_priority_ordering(self, queue, sample_payload):
        """Test that higher priority messages are processed first."""
        # Add messages with different priorities
        queue.put(message_id="low", destination="DST", payload=sample_payload, priority=0)
        queue.put(message_id="high", destination="DST", payload=sample_payload, priority=10)
        queue.put(message_id="medium", destination="DST", payload=sample_payload, priority=5)
        
        # Should get high priority first
        item1 = queue.get()
        assert item1.message_id == "high"
        queue.ack(item1.id)
        
        # Then medium
        item2 = queue.get()
        assert item2.message_id == "medium"
        queue.ack(item2.id)
        
        # Then low
        item3 = queue.get()
        assert item3.message_id == "low"
    
    def test_fifo_within_priority(self, queue, sample_payload):
        """Test FIFO ordering within same priority."""
        queue.put(message_id="first", destination="DST", payload=sample_payload)
        queue.put(message_id="second", destination="DST", payload=sample_payload)
        queue.put(message_id="third", destination="DST", payload=sample_payload)
        
        item1 = queue.get()
        assert item1.message_id == "first"
        queue.ack(item1.id)
        
        item2 = queue.get()
        assert item2.message_id == "second"
    
    def test_duplicate_message_id_returns_existing(self, queue, sample_payload):
        """Test that duplicate message_id returns existing item ID."""
        id1 = queue.put(message_id="msg-001", destination="DST", payload=sample_payload)
        id2 = queue.put(message_id="msg-001", destination="DST", payload=sample_payload)
        
        assert id1 == id2
    
    def test_queue_full_raises_error(self, tmp_path, sample_payload):
        """Test that queue full raises QueueFullError."""
        db_path = tmp_path / "small_queue.db"
        small_queue = PersistentQueue(str(db_path), max_size=2)
        
        try:
            small_queue.put(message_id="msg-001", destination="DST", payload=sample_payload)
            small_queue.put(message_id="msg-002", destination="DST", payload=sample_payload)
            
            with pytest.raises(QueueFullError):
                small_queue.put(message_id="msg-003", destination="DST", payload=sample_payload)
        finally:
            small_queue.close()
    
    def test_size_counts_correctly(self, queue, sample_payload):
        """Test queue size counting."""
        assert queue.size() == 0
        
        queue.put(message_id="msg-001", destination="DST", payload=sample_payload)
        assert queue.size() == 1
        
        queue.put(message_id="msg-002", destination="DST", payload=sample_payload)
        assert queue.size() == 2
        
        # Get and ack one
        item = queue.get()
        queue.ack(item.id)
        
        # Still 2 total (acked items are kept for audit)
        assert queue.size() == 2
        
        # But only 1 pending
        assert queue.size(QueueItemStatus.PENDING) == 1
    
    def test_get_batch(self, queue, sample_payload):
        """Test getting a batch of messages."""
        for i in range(5):
            queue.put(message_id=f"msg-{i}", destination="DST", payload=sample_payload)
        
        items = queue.get_batch(batch_size=3)
        
        assert len(items) == 3
        assert all(item.status == QueueItemStatus.SENDING for item in items)
    
    def test_destination_filter(self, queue, sample_payload):
        """Test filtering by destination."""
        queue.put(message_id="msg-1", destination="FAC-A", payload=sample_payload)
        queue.put(message_id="msg-2", destination="FAC-B", payload=sample_payload)
        queue.put(message_id="msg-3", destination="FAC-A", payload=sample_payload)
        
        # Get only FAC-B messages
        item = queue.get(destination="FAC-B")
        assert item.message_id == "msg-2"
        queue.ack(item.id)
        
        # No more FAC-B messages
        item = queue.get(destination="FAC-B")
        assert item is None
    
    def test_peek_does_not_modify(self, queue, sample_payload):
        """Test that peek doesn't change status."""
        queue_id = queue.put(
            message_id="msg-001",
            destination="DST",
            payload=sample_payload,
        )
        
        # Peek multiple times
        item1 = queue.peek(queue_id)
        item2 = queue.peek(queue_id)
        
        assert item1.status == QueueItemStatus.PENDING
        assert item2.status == QueueItemStatus.PENDING
        assert item1.attempts == 0  # Not incremented by peek
    
    def test_delete(self, queue, sample_payload):
        """Test message deletion."""
        queue_id = queue.put(
            message_id="msg-001",
            destination="DST",
            payload=sample_payload,
        )
        
        assert queue.delete(queue_id) is True
        assert queue.peek(queue_id) is None
        assert queue.delete(queue_id) is False  # Already deleted
    
    def test_purge_by_status(self, queue, sample_payload):
        """Test purging messages by status."""
        queue.put(message_id="msg-1", destination="DST", payload=sample_payload)
        queue.put(message_id="msg-2", destination="DST", payload=sample_payload)
        
        # Ack one
        item = queue.get()
        queue.ack(item.id)
        
        # Purge only acked
        count = queue.purge(status=QueueItemStatus.ACKED)
        assert count == 1
        
        # One still remaining
        assert queue.size() == 1
    
    def test_get_stats(self, queue, sample_payload):
        """Test statistics retrieval."""
        queue.put(message_id="msg-1", destination="DST", payload=sample_payload)
        queue.put(message_id="msg-2", destination="DST", payload=sample_payload)
        
        item = queue.get()
        queue.ack(item.id)
        
        stats = queue.get_stats()
        
        assert stats["total"] == 2
        assert "pending" in stats["by_status"] or "sending" in stats["by_status"]
        assert stats["max_size"] == 100
        assert stats["max_retries"] == 3
    
    def test_iter_items(self, queue, sample_payload):
        """Test iteration over items."""
        for i in range(5):
            queue.put(message_id=f"msg-{i}", destination="DST", payload=sample_payload)
        
        items = list(queue.iter_items(limit=10))
        assert len(items) == 5
        
        # Filter by status
        pending = list(queue.iter_items(status=QueueItemStatus.PENDING))
        assert len(pending) == 5
    
    def test_metadata_storage(self, queue, sample_payload):
        """Test metadata is stored and retrieved."""
        metadata = {"source": "openmrs", "resource_type": "Patient"}
        
        queue_id = queue.put(
            message_id="msg-001",
            destination="DST",
            payload=sample_payload,
            metadata=metadata,
        )
        
        item = queue.peek(queue_id)
        assert item.metadata == metadata
    
    def test_persistence_across_reopen(self, tmp_path, sample_payload):
        """Test that messages persist when queue is closed and reopened."""
        db_path = tmp_path / "persist_test.db"
        
        # Create queue and add message
        q1 = PersistentQueue(str(db_path))
        q1.put(message_id="persistent-msg", destination="DST", payload=sample_payload)
        q1.close()
        
        # Reopen queue
        q2 = PersistentQueue(str(db_path))
        
        try:
            item = q2.get()
            assert item is not None
            assert item.message_id == "persistent-msg"
        finally:
            q2.close()
    
    def test_context_manager(self, tmp_path, sample_payload):
        """Test queue works as context manager."""
        db_path = tmp_path / "context_test.db"
        
        with PersistentQueue(str(db_path)) as queue:
            queue.put(message_id="msg-001", destination="DST", payload=sample_payload)
            assert queue.size() == 1
        
        # Queue should be closed now
        # No assertion needed - just verify no exception


class TestQueueThreadSafety:
    """Test thread safety of queue operations."""
    
    @pytest.fixture
    def queue(self, tmp_path):
        """Create a temporary queue for testing."""
        db_path = tmp_path / "thread_test.db"
        q = PersistentQueue(str(db_path), max_size=1000)
        yield q
        q.close()
    
    def test_concurrent_puts(self, queue):
        """Test concurrent put operations."""
        errors = []
        
        def put_messages(start_id):
            try:
                for i in range(50):
                    queue.put(
                        message_id=f"msg-{start_id}-{i}",
                        destination="DST",
                        payload=b"test",
                    )
            except Exception as e:
                errors.append(e)
        
        threads = [
            threading.Thread(target=put_messages, args=(i,))
            for i in range(5)
        ]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(errors) == 0
        assert queue.size() == 250  # 5 threads * 50 messages
    
    def test_concurrent_get_and_ack(self, queue):
        """Test concurrent get and ack operations."""
        # Pre-populate queue
        for i in range(100):
            queue.put(message_id=f"msg-{i}", destination="DST", payload=b"test")
        
        processed = []
        errors = []
        lock = threading.Lock()
        
        def process_messages():
            try:
                while True:
                    item = queue.get()
                    if item is None:
                        break
                    queue.ack(item.id)
                    with lock:
                        processed.append(item.message_id)
            except Exception as e:
                errors.append(e)
        
        threads = [
            threading.Thread(target=process_messages)
            for _ in range(5)
        ]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(errors) == 0
        assert len(processed) == 100
        assert len(set(processed)) == 100  # All unique (no duplicates)
