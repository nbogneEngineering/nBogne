#!/usr/bin/env python3
"""
Queue Management Utility for nBogne Adapter.

This script provides command-line tools for managing the persistent queue:
    - View queue status and statistics
    - List pending/failed messages
    - Retry failed messages
    - Purge old messages
    - Export messages for debugging

Usage:
    python -m scripts.queue_manager stats
    python -m scripts.queue_manager list --status pending --limit 10
    python -m scripts.queue_manager retry --id 123
    python -m scripts.queue_manager purge --status acked --older-than 7d
    python -m scripts.queue_manager export --output messages.json
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from nbogne.queue import PersistentQueue, QueueItemStatus


def parse_duration(duration_str: str) -> timedelta:
    """Parse duration string like '7d', '24h', '30m' into timedelta."""
    if not duration_str:
        raise ValueError("Empty duration string")
    
    unit = duration_str[-1].lower()
    try:
        value = int(duration_str[:-1])
    except ValueError:
        raise ValueError(f"Invalid duration: {duration_str}")
    
    if unit == 'd':
        return timedelta(days=value)
    elif unit == 'h':
        return timedelta(hours=value)
    elif unit == 'm':
        return timedelta(minutes=value)
    else:
        raise ValueError(f"Unknown duration unit: {unit}. Use d/h/m")


def cmd_stats(args):
    """Show queue statistics."""
    queue = PersistentQueue(args.db_path)
    
    try:
        stats = queue.get_stats()
        
        print("\n" + "=" * 50)
        print("  nBogne Queue Statistics")
        print("=" * 50)
        print(f"  Database: {stats['db_path']}")
        print(f"  Total Messages: {stats['total']}")
        print(f"  Max Size: {stats['max_size']}")
        print()
        print("  By Status:")
        for status, count in sorted(stats['by_status'].items()):
            pct = (count / stats['total'] * 100) if stats['total'] > 0 else 0
            bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
            print(f"    {status:12} {count:6}  {bar} {pct:5.1f}%")
        print()
        if stats['oldest']:
            print(f"  Oldest Message: {stats['oldest']}")
        if stats['newest']:
            print(f"  Newest Message: {stats['newest']}")
        print("=" * 50 + "\n")
        
    finally:
        queue.close()


def cmd_list(args):
    """List queue items."""
    queue = PersistentQueue(args.db_path)
    
    try:
        status = QueueItemStatus(args.status) if args.status else None
        items = list(queue.iter_items(status=status, limit=args.limit))
        
        if not items:
            print(f"\nNo messages found" + (f" with status '{args.status}'" if args.status else ""))
            return
        
        print(f"\n{'ID':>6} {'Message ID':36} {'Status':10} {'Dest':10} {'Attempts':8} {'Created'}")
        print("-" * 100)
        
        for item in items:
            msg_id_short = item.message_id[:8] + "..." if len(item.message_id) > 11 else item.message_id
            created = item.created_at.strftime("%Y-%m-%d %H:%M")
            print(f"{item.id:>6} {item.message_id:36} {item.status.value:10} {item.destination:10} {item.attempts:>8} {created}")
        
        print(f"\nShowing {len(items)} of {queue.size(status)} messages\n")
        
    finally:
        queue.close()


def cmd_show(args):
    """Show details of a specific message."""
    queue = PersistentQueue(args.db_path)
    
    try:
        item = queue.peek(args.id)
        
        if not item:
            print(f"Message with ID {args.id} not found")
            return 1
        
        print(f"\n{'=' * 50}")
        print(f"  Message Details: #{item.id}")
        print(f"{'=' * 50}")
        print(f"  Message ID:    {item.message_id}")
        print(f"  Destination:   {item.destination}")
        print(f"  Status:        {item.status.value}")
        print(f"  Priority:      {item.priority}")
        print(f"  Attempts:      {item.attempts}")
        print(f"  Created:       {item.created_at}")
        print(f"  Updated:       {item.updated_at}")
        if item.next_retry_at:
            print(f"  Next Retry:    {item.next_retry_at}")
        if item.last_error:
            print(f"  Last Error:    {item.last_error}")
        print(f"  Payload Size:  {len(item.payload)} bytes")
        if item.metadata:
            print(f"  Metadata:      {json.dumps(item.metadata, indent=2)}")
        print(f"{'=' * 50}\n")
        
        if args.show_payload:
            print("Payload (hex):")
            print(item.payload[:200].hex())
            if len(item.payload) > 200:
                print(f"... ({len(item.payload) - 200} more bytes)")
        
    finally:
        queue.close()


def cmd_retry(args):
    """Retry a failed message."""
    queue = PersistentQueue(args.db_path)
    
    try:
        if args.id:
            # Retry specific message
            item = queue.peek(args.id)
            if not item:
                print(f"Message with ID {args.id} not found")
                return 1
            
            if item.status not in (QueueItemStatus.FAILED, QueueItemStatus.DEAD):
                print(f"Message {args.id} is not in failed/dead status (current: {item.status.value})")
                return 1
            
            # Reset to pending with cleared retry time
            conn = queue._get_connection()
            conn.execute(
                """
                UPDATE queue
                SET status = ?, next_retry_at = NULL, updated_at = ?
                WHERE id = ?
                """,
                (QueueItemStatus.PENDING.value, datetime.utcnow().isoformat(), args.id)
            )
            print(f"Message {args.id} reset to pending status")
            
        elif args.all_failed:
            # Retry all failed messages
            conn = queue._get_connection()
            cursor = conn.execute(
                """
                UPDATE queue
                SET status = ?, next_retry_at = NULL, updated_at = ?
                WHERE status IN (?, ?)
                """,
                (
                    QueueItemStatus.PENDING.value,
                    datetime.utcnow().isoformat(),
                    QueueItemStatus.FAILED.value,
                    QueueItemStatus.DEAD.value,
                )
            )
            print(f"Reset {cursor.rowcount} messages to pending status")
        
    finally:
        queue.close()


def cmd_purge(args):
    """Purge messages from the queue."""
    queue = PersistentQueue(args.db_path)
    
    try:
        status = QueueItemStatus(args.status) if args.status else None
        older_than = None
        
        if args.older_than:
            delta = parse_duration(args.older_than)
            older_than = datetime.utcnow() - delta
        
        # Confirm before purging
        count_query = "SELECT COUNT(*) FROM queue WHERE 1=1"
        params = []
        if status:
            count_query += " AND status = ?"
            params.append(status.value)
        if older_than:
            count_query += " AND created_at < ?"
            params.append(older_than.isoformat())
        
        conn = queue._get_connection()
        cursor = conn.execute(count_query, params)
        count = cursor.fetchone()[0]
        
        if count == 0:
            print("No messages match the criteria")
            return
        
        if not args.force:
            confirm = input(f"This will delete {count} messages. Continue? [y/N]: ")
            if confirm.lower() != 'y':
                print("Aborted")
                return
        
        deleted = queue.purge(status=status, older_than=older_than)
        print(f"Purged {deleted} messages")
        
    finally:
        queue.close()


def cmd_export(args):
    """Export messages to JSON file."""
    queue = PersistentQueue(args.db_path)
    
    try:
        status = QueueItemStatus(args.status) if args.status else None
        items = list(queue.iter_items(status=status, limit=args.limit))
        
        export_data = {
            "exported_at": datetime.utcnow().isoformat(),
            "db_path": args.db_path,
            "filter_status": args.status,
            "count": len(items),
            "messages": []
        }
        
        for item in items:
            export_data["messages"].append({
                "id": item.id,
                "message_id": item.message_id,
                "destination": item.destination,
                "status": item.status.value,
                "priority": item.priority,
                "attempts": item.attempts,
                "created_at": item.created_at.isoformat(),
                "updated_at": item.updated_at.isoformat(),
                "next_retry_at": item.next_retry_at.isoformat() if item.next_retry_at else None,
                "last_error": item.last_error,
                "payload_size": len(item.payload),
                "metadata": item.metadata,
            })
        
        output_path = Path(args.output)
        with open(output_path, 'w') as f:
            json.dump(export_data, f, indent=2)
        
        print(f"Exported {len(items)} messages to {output_path}")
        
    finally:
        queue.close()


def main():
    parser = argparse.ArgumentParser(
        description="nBogne Queue Management Utility",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    
    parser.add_argument(
        "--db-path",
        default="data/outbox.db",
        help="Path to queue database (default: data/outbox.db)"
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Command")
    
    # stats command
    stats_parser = subparsers.add_parser("stats", help="Show queue statistics")
    stats_parser.set_defaults(func=cmd_stats)
    
    # list command
    list_parser = subparsers.add_parser("list", help="List queue items")
    list_parser.add_argument("--status", choices=[s.value for s in QueueItemStatus])
    list_parser.add_argument("--limit", type=int, default=20)
    list_parser.set_defaults(func=cmd_list)
    
    # show command
    show_parser = subparsers.add_parser("show", help="Show message details")
    show_parser.add_argument("id", type=int, help="Message ID")
    show_parser.add_argument("--show-payload", action="store_true")
    show_parser.set_defaults(func=cmd_show)
    
    # retry command
    retry_parser = subparsers.add_parser("retry", help="Retry failed messages")
    retry_group = retry_parser.add_mutually_exclusive_group(required=True)
    retry_group.add_argument("--id", type=int, help="Specific message ID")
    retry_group.add_argument("--all-failed", action="store_true", help="Retry all failed/dead")
    retry_parser.set_defaults(func=cmd_retry)
    
    # purge command
    purge_parser = subparsers.add_parser("purge", help="Purge messages")
    purge_parser.add_argument("--status", choices=[s.value for s in QueueItemStatus])
    purge_parser.add_argument("--older-than", help="Duration (e.g., 7d, 24h, 30m)")
    purge_parser.add_argument("--force", action="store_true", help="Skip confirmation")
    purge_parser.set_defaults(func=cmd_purge)
    
    # export command
    export_parser = subparsers.add_parser("export", help="Export messages to JSON")
    export_parser.add_argument("--output", "-o", default="queue_export.json")
    export_parser.add_argument("--status", choices=[s.value for s in QueueItemStatus])
    export_parser.add_argument("--limit", type=int, default=1000)
    export_parser.set_defaults(func=cmd_export)
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    result = args.func(args)
    sys.exit(result or 0)


if __name__ == "__main__":
    main()
