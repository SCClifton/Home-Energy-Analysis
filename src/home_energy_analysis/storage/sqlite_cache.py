"""
SQLite cache for Amber API price and usage data.
"""
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any
from importlib import resources


def init_db(db_path: str) -> None:
    """
    Initialize the SQLite database by creating parent directories and tables.
    
    Args:
        db_path: Path to the SQLite database file
    """
    # Create parent directories if they don't exist
    db_file = Path(db_path)
    db_file.parent.mkdir(parents=True, exist_ok=True)
    
    # Read schema file using importlib.resources (works when installed as package)
    try:
        # Python 3.9+ style
        schema_text = resources.files(__package__).joinpath("sqlite_schema.sql").read_text(encoding="utf-8")
    except AttributeError:
        # Fallback for older Python versions
        with resources.open_text(__package__, "sqlite_schema.sql", encoding="utf-8") as f:
            schema_text = f.read()
    
    # Create connection and execute schema
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(schema_text)
        conn.commit()
    finally:
        conn.close()


def upsert_prices(db_path: str, rows: List[Dict[str, Any]]) -> None:
    """
    Insert or update price rows in the database.
    
    Args:
        db_path: Path to the SQLite database file
        rows: List of dictionaries with keys: site_id, interval_start, interval_end,
              channel_type, per_kwh, renewables (optional), descriptor (optional)
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        updated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        
        for row in rows:
            cursor.execute("""
                INSERT INTO prices (
                    site_id, interval_start, interval_end, channel_type,
                    per_kwh, renewables, descriptor, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (site_id, interval_start, channel_type)
                DO UPDATE SET
                    interval_end = excluded.interval_end,
                    per_kwh = excluded.per_kwh,
                    renewables = excluded.renewables,
                    descriptor = excluded.descriptor,
                    updated_at = excluded.updated_at
            """, (
                row["site_id"],
                row["interval_start"],
                row["interval_end"],
                row["channel_type"],
                row["per_kwh"],
                row.get("renewables"),
                row.get("descriptor"),
                updated_at
            ))
        
        conn.commit()
    finally:
        conn.close()


def upsert_usage(db_path: str, rows: List[Dict[str, Any]]) -> None:
    """
    Insert or update usage rows in the database.
    
    Args:
        db_path: Path to the SQLite database file
        rows: List of dictionaries with keys: site_id, interval_start, interval_end,
              channel_type, kwh
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        updated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        
        for row in rows:
            cursor.execute("""
                INSERT INTO usage (
                    site_id, interval_start, interval_end, channel_type,
                    kwh, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (site_id, interval_start, channel_type)
                DO UPDATE SET
                    interval_end = excluded.interval_end,
                    kwh = excluded.kwh,
                    updated_at = excluded.updated_at
            """, (
                row["site_id"],
                row["interval_start"],
                row["interval_end"],
                row["channel_type"],
                row["kwh"],
                updated_at
            ))
        
        conn.commit()
    finally:
        conn.close()


def get_latest_price(db_path: str, site_id: str, channel_type: str = "general") -> Optional[Dict[str, Any]]:
    """
    Get the latest price row for a given site and channel type.
    
    Args:
        db_path: Path to the SQLite database file
        site_id: Site ID to query
        channel_type: Channel type (default: "general")
        
    Returns:
        Dictionary with price data or None if not found
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT site_id, interval_start, interval_end, channel_type,
                   per_kwh, renewables, descriptor, updated_at
            FROM prices
            WHERE site_id = ? AND channel_type = ?
            ORDER BY interval_start DESC
            LIMIT 1
        """, (site_id, channel_type))
        
        row = cursor.fetchone()
        if row is None:
            return None
        
        return {
            "site_id": row[0],
            "interval_start": row[1],
            "interval_end": row[2],
            "channel_type": row[3],
            "per_kwh": row[4],
            "renewables": row[5],
            "descriptor": row[6],
            "updated_at": row[7]
        }
    finally:
        conn.close()


def get_latest_usage(db_path: str, site_id: str, channel_type: str = "general") -> Optional[Dict[str, Any]]:
    """
    Get the latest usage row for a given site and channel type.
    
    Args:
        db_path: Path to the SQLite database file
        site_id: Site ID to query
        channel_type: Channel type (default: "general")
        
    Returns:
        Dictionary with usage data or None if not found
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT site_id, interval_start, interval_end, channel_type,
                   kwh, updated_at
            FROM usage
            WHERE site_id = ? AND channel_type = ?
            ORDER BY interval_start DESC
            LIMIT 1
        """, (site_id, channel_type))
        
        row = cursor.fetchone()
        if row is None:
            return None
        
        return {
            "site_id": row[0],
            "interval_start": row[1],
            "interval_end": row[2],
            "channel_type": row[3],
            "kwh": row[4],
            "updated_at": row[5]
        }
    finally:
        conn.close()


def get_price_for_interval(db_path: str, site_id: str, interval_start: str, channel_type: str = "general") -> Optional[Dict[str, Any]]:
    """
    Get a price row for a specific interval.
    
    Args:
        db_path: Path to the SQLite database file
        site_id: Site ID to query
        interval_start: Interval start time (ISO8601 string)
        channel_type: Channel type (default: "general")
        
    Returns:
        Dictionary with price data or None if not found
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT site_id, interval_start, interval_end, channel_type,
                   per_kwh, renewables, descriptor, updated_at
            FROM prices
            WHERE site_id = ? AND interval_start = ? AND channel_type = ?
            LIMIT 1
        """, (site_id, interval_start, channel_type))
        
        row = cursor.fetchone()
        if row is None:
            return None
        
        return {
            "site_id": row[0],
            "interval_start": row[1],
            "interval_end": row[2],
            "channel_type": row[3],
            "per_kwh": row[4],
            "renewables": row[5],
            "descriptor": row[6],
            "updated_at": row[7]
        }
    finally:
        conn.close()


def get_usage_for_interval(db_path: str, site_id: str, interval_start: str, channel_type: str = "general") -> Optional[Dict[str, Any]]:
    """
    Get a usage row for a specific interval.
    
    Args:
        db_path: Path to the SQLite database file
        site_id: Site ID to query
        interval_start: Interval start time (ISO8601 string)
        channel_type: Channel type (default: "general")
        
    Returns:
        Dictionary with usage data or None if not found
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT site_id, interval_start, interval_end, channel_type,
                   kwh, updated_at
            FROM usage
            WHERE site_id = ? AND interval_start = ? AND channel_type = ?
            LIMIT 1
        """, (site_id, interval_start, channel_type))
        
        row = cursor.fetchone()
        if row is None:
            return None
        
        return {
            "site_id": row[0],
            "interval_start": row[1],
            "interval_end": row[2],
            "channel_type": row[3],
            "kwh": row[4],
            "updated_at": row[5]
        }
    finally:
        conn.close()


def prune_old_data(db_path: str, retention_days: int) -> int:
    """
    Delete rows older than the retention period.
    
    Args:
        db_path: Path to the SQLite database file
        retention_days: Number of days to retain data
        
    Returns:
        Number of rows deleted (from both tables combined)
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    cutoff_str = cutoff.isoformat().replace("+00:00", "Z")
    
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        
        # Delete old prices
        cursor.execute("""
            DELETE FROM prices
            WHERE interval_start < ?
        """, (cutoff_str,))
        prices_deleted = cursor.rowcount
        
        # Delete old usage
        cursor.execute("""
            DELETE FROM usage
            WHERE interval_start < ?
        """, (cutoff_str,))
        usage_deleted = cursor.rowcount
        
        conn.commit()
        return prices_deleted + usage_deleted
    finally:
        conn.close()

