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
        
        # Run idempotent migrations for existing databases
        _migrate_usage_table(conn)
        conn.commit()
    finally:
        conn.close()


def _migrate_usage_table(conn: sqlite3.Connection) -> None:
    """
    Idempotent migration to add cost_aud, quality, channel_identifier columns to usage table.
    Safe to run multiple times - checks for column existence before adding.
    """
    cursor = conn.cursor()
    
    # Get existing columns
    cursor.execute("PRAGMA table_info(usage)")
    existing_columns = {row[1] for row in cursor.fetchall()}
    
    # Add missing columns if they don't exist
    if "cost_aud" not in existing_columns:
        cursor.execute("ALTER TABLE usage ADD COLUMN cost_aud REAL")
    
    if "quality" not in existing_columns:
        cursor.execute("ALTER TABLE usage ADD COLUMN quality TEXT")
    
    if "channel_identifier" not in existing_columns:
        cursor.execute("ALTER TABLE usage ADD COLUMN channel_identifier TEXT")


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
              channel_type, kwh, and optionally cost_aud, quality, channel_identifier
    """
    conn = sqlite3.connect(db_path)
    try:
        # Ensure migrations are run (idempotent)
        _migrate_usage_table(conn)
        conn.commit()
        
        cursor = conn.cursor()
        updated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        
        for row in rows:
            cursor.execute("""
                INSERT INTO usage (
                    site_id, interval_start, interval_end, channel_type,
                    kwh, cost_aud, quality, channel_identifier, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (site_id, interval_start, channel_type)
                DO UPDATE SET
                    interval_end = excluded.interval_end,
                    kwh = excluded.kwh,
                    cost_aud = excluded.cost_aud,
                    quality = excluded.quality,
                    channel_identifier = excluded.channel_identifier,
                    updated_at = excluded.updated_at
            """, (
                row["site_id"],
                row["interval_start"],
                row["interval_end"],
                row["channel_type"],
                row["kwh"],
                row.get("cost_aud"),
                row.get("quality"),
                row.get("channel_identifier"),
                updated_at
            ))
        
        conn.commit()
    finally:
        conn.close()


def get_latest_price(db_path: str, site_id: str, channel_type: str = "general", max_interval_start: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Get the latest price row for a given site and channel type.
    
    Only considers intervals that have started (interval_start <= max_interval_start if provided).
    This prevents selecting future intervals cached for forecast purposes.
    
    Args:
        db_path: Path to the SQLite database file
        site_id: Site ID to query
        channel_type: Channel type (default: "general")
        max_interval_start: Maximum interval_start (ISO8601 string). If None, no time filter is applied.
        
    Returns:
        Dictionary with price data or None if not found
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        if max_interval_start:
            cursor.execute("""
                SELECT site_id, interval_start, interval_end, channel_type,
                       per_kwh, renewables, descriptor, updated_at
                FROM prices
                WHERE site_id = ? AND channel_type = ? AND interval_start <= ?
                ORDER BY interval_start DESC
                LIMIT 1
            """, (site_id, channel_type, max_interval_start))
        else:
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


def get_latest_usage(db_path: str, site_id: str, channel_type: str = "general", max_interval_start: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Get the latest usage row for a given site and channel type.
    
    Only considers intervals that have started (interval_start <= max_interval_start if provided).
    This prevents selecting future intervals (usage should never be future, but keeps logic consistent).
    
    Args:
        db_path: Path to the SQLite database file
        site_id: Site ID to query
        channel_type: Channel type (default: "general")
        max_interval_start: Maximum interval_start (ISO8601 string). If None, no time filter is applied.
        
    Returns:
        Dictionary with usage data or None if not found
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        if max_interval_start:
            cursor.execute("""
                SELECT site_id, interval_start, interval_end, channel_type,
                       kwh, updated_at
                FROM usage
                WHERE site_id = ? AND channel_type = ? AND interval_start <= ?
                ORDER BY interval_start DESC
                LIMIT 1
            """, (site_id, channel_type, max_interval_start))
        else:
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
    
    Supports legacy :01Z timestamps by trying exact match first, then +1 second fallback.
    This allows reading cached rows with legacy :01Z timestamps when querying for :00Z.
    
    Args:
        db_path: Path to the SQLite database file
        site_id: Site ID to query
        interval_start: Interval start time (ISO8601 string, normalized :00Z)
        channel_type: Channel type (default: "general")
        
    Returns:
        Dictionary with price data or None if not found
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        
        # Try exact match first (preferred :00Z format)
        cursor.execute("""
            SELECT site_id, interval_start, interval_end, channel_type,
                   per_kwh, renewables, descriptor, updated_at
            FROM prices
            WHERE site_id = ? AND interval_start = ? AND channel_type = ?
            LIMIT 1
        """, (site_id, interval_start, channel_type))
        
        row = cursor.fetchone()
        if row is not None:
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
        
        # Fallback: try legacy :01Z pattern (target + 1 second)
        # Parse ISO timestamp, add 1 second, format back
        try:
            dt = datetime.fromisoformat(interval_start.replace("Z", "+00:00"))
            legacy_interval_start = (dt + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
        except Exception:
            # If parsing fails, return None
            return None
        
        cursor.execute("""
            SELECT site_id, interval_start, interval_end, channel_type,
                   per_kwh, renewables, descriptor, updated_at
            FROM prices
            WHERE site_id = ? AND interval_start = ? AND channel_type = ?
            LIMIT 1
        """, (site_id, legacy_interval_start, channel_type))
        
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
    
    Supports legacy :01Z timestamps by trying exact match first, then +1 second fallback.
    This allows reading cached rows with legacy :01Z timestamps when querying for :00Z.
    
    Args:
        db_path: Path to the SQLite database file
        site_id: Site ID to query
        interval_start: Interval start time (ISO8601 string, normalized :00Z)
        channel_type: Channel type (default: "general")
        
    Returns:
        Dictionary with usage data or None if not found
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        
        # Try exact match first (preferred :00Z format)
        cursor.execute("""
            SELECT site_id, interval_start, interval_end, channel_type,
                   kwh, updated_at
            FROM usage
            WHERE site_id = ? AND interval_start = ? AND channel_type = ?
            LIMIT 1
        """, (site_id, interval_start, channel_type))
        
        row = cursor.fetchone()
        if row is not None:
            return {
                "site_id": row[0],
                "interval_start": row[1],
                "interval_end": row[2],
                "channel_type": row[3],
                "kwh": row[4],
                "updated_at": row[5]
            }
        
        # Fallback: try legacy :01Z pattern (target + 1 second)
        # Parse ISO timestamp, add 1 second, format back
        try:
            dt = datetime.fromisoformat(interval_start.replace("Z", "+00:00"))
            legacy_interval_start = (dt + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
        except Exception:
            # If parsing fails, return None
            return None
        
        cursor.execute("""
            SELECT site_id, interval_start, interval_end, channel_type,
                   kwh, updated_at
            FROM usage
            WHERE site_id = ? AND interval_start = ? AND channel_type = ?
            LIMIT 1
        """, (site_id, legacy_interval_start, channel_type))
        
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


def get_forecast_intervals(db_path: str, site_id: str, channel_type: str = "general", max_intervals: int = 24) -> List[Dict[str, Any]]:
    """
    Get forecast intervals (future prices) from cache.
    
    Args:
        db_path: Path to the SQLite database file
        site_id: Site ID to query
        channel_type: Channel type (default: "general")
        max_intervals: Maximum number of intervals to return
        
    Returns:
        List of price dictionaries sorted by interval_start ASC
    """
    now_utc = datetime.now(timezone.utc)
    now_str = now_utc.isoformat().replace("+00:00", "Z")
    
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT site_id, interval_start, interval_end, channel_type,
                   per_kwh, renewables, descriptor, updated_at
            FROM prices
            WHERE site_id = ? AND channel_type = ? AND interval_start > ?
            ORDER BY interval_start ASC
            LIMIT ?
        """, (site_id, channel_type, now_str, max_intervals))
        
        rows = cursor.fetchall()
        return [
            {
                "site_id": row[0],
                "interval_start": row[1],
                "interval_end": row[2],
                "channel_type": row[3],
                "per_kwh": row[4],
                "renewables": row[5],
                "descriptor": row[6],
                "updated_at": row[7]
            }
            for row in rows
        ]
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

