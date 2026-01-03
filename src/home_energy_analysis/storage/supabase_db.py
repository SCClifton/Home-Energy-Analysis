"""
Supabase Postgres database client for home energy analysis data.
"""
import os
import json
import time
import hashlib
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
import psycopg
from psycopg.rows import dict_row


def get_conn() -> psycopg.Connection:
    """
    Get a connection to Supabase Postgres database.
    
    Requires SUPABASE_DB_URL environment variable to be set.
    The connection uses autocommit=False (transactions must be committed explicitly).
    
    Implements retry logic with exponential backoff (8 attempts, 0.5s initial,
    doubling each time, capped at 8s).
    
    Returns:
        psycopg.Connection instance
        
    Raises:
        KeyError: if SUPABASE_DB_URL is not set
        psycopg.Error: if connection fails after all retries
    """
    db_url = os.environ.get("SUPABASE_DB_URL")
    if not db_url:
        raise KeyError("SUPABASE_DB_URL environment variable is required")
    
    max_attempts = 8
    sleep_time = 0.5
    max_sleep = 8.0
    last_exception = None
    
    for attempt in range(max_attempts):
        try:
            return psycopg.connect(
                db_url,
                autocommit=False,
                connect_timeout=10,
                keepalives=1,
                keepalives_idle=30,
                keepalives_interval=10,
                keepalives_count=5
            )
        except Exception as e:
            last_exception = e
            if attempt < max_attempts - 1:
                # Sleep before retry, but cap at max_sleep
                actual_sleep = min(sleep_time, max_sleep)
                time.sleep(actual_sleep)
                sleep_time *= 2
            # On last attempt, don't sleep, just raise
    
    # If we get here, all attempts failed
    raise last_exception


def _compute_payload_hash(payload_dict: Dict[str, Any]) -> str:
    """
    Compute SHA256 hash of canonical JSON representation of payload.
    
    Args:
        payload_dict: Dictionary to hash
        
    Returns:
        Hexadecimal hash string
    """
    # Sort keys for canonical representation
    canonical_json = json.dumps(payload_dict, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(canonical_json.encode('utf-8')).hexdigest()


def insert_ingest_event(
    conn: psycopg.Connection,
    source: str,
    kind: str,
    payload_dict: Dict[str, Any],
    window_start: Optional[datetime] = None,
    window_end: Optional[datetime] = None,
    status: str = "ok",
    error: Optional[str] = None
) -> str:
    """
    Insert or get existing ingest event, deduplicating by (source, kind, payload_hash).
    
    Args:
        conn: Database connection
        source: Data source identifier (e.g., 'amber', 'powerpal')
        kind: Event kind (e.g., 'prices', 'usage')
        payload_dict: Raw payload dictionary (will be hashed and stored as JSONB)
        window_start: Optional start of time window for this ingestion
        window_end: Optional end of time window for this ingestion
        status: Status string (default: 'ok')
        error: Optional error message
        
    Returns:
        UUID string of the ingest event (existing or newly created)
    """
    payload_hash = _compute_payload_hash(payload_dict)
    fetched_at = datetime.now(timezone.utc)
    
    # Try to get existing event first
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id FROM ingest_events
            WHERE source = %s AND kind = %s AND payload_hash = %s
            LIMIT 1
        """, (source, kind, payload_hash))
        
        row = cur.fetchone()
        if row:
            return str(row[0])
    
    # Insert new event
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO ingest_events (
                source, kind, fetched_at, window_start, window_end,
                payload_hash, payload, status, error
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            source, kind, fetched_at, window_start, window_end,
            payload_hash, json.dumps(payload_dict), status, error
        ))
        
        event_id = cur.fetchone()[0]
        conn.commit()
        return str(event_id)


def upsert_price_intervals(conn: psycopg.Connection, rows: List[Dict[str, Any]]) -> int:
    """
    Upsert price interval rows into the database.
    
    Uses INSERT ... ON CONFLICT DO UPDATE with COALESCE to preserve existing
    non-null values when new data has nulls.
    
    Args:
        conn: Database connection
        rows: List of dictionaries with keys:
            - site_id (required)
            - interval_start (required, datetime or ISO string)
            - interval_end (required, datetime or ISO string)
            - is_forecast (optional, bool, default False)
            - price_cents_per_kwh (optional, numeric)
            - spot_per_kwh (optional, numeric)
            - descriptor (optional, text)
            - spike_status (optional, text)
            - renewables_percent (optional, numeric)
            - source (optional, text, default 'amber')
            - raw_event_id (optional, UUID string)
            
    Returns:
        Number of rows inserted/updated
    """
    if not rows:
        return 0
    
    # Normalize datetime fields
    normalized_rows = []
    for row in rows:
        norm_row = row.copy()
        
        # Convert interval_start/interval_end to timezone-aware datetime if needed
        for field in ['interval_start', 'interval_end']:
            if field in norm_row and norm_row[field] is not None:
                if isinstance(norm_row[field], str):
                    # Parse ISO string
                    dt = datetime.fromisoformat(norm_row[field].replace('Z', '+00:00'))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    norm_row[field] = dt
                elif isinstance(norm_row[field], datetime):
                    # Ensure timezone-aware
                    if norm_row[field].tzinfo is None:
                        norm_row[field] = norm_row[field].replace(tzinfo=timezone.utc)
        
        # Ensure is_forecast is boolean
        if 'is_forecast' in norm_row:
            norm_row['is_forecast'] = bool(norm_row.get('is_forecast', False))
        else:
            norm_row['is_forecast'] = False
        
        # Default source
        if 'source' not in norm_row:
            norm_row['source'] = 'amber'
        
        normalized_rows.append(norm_row)
    
    with conn.cursor() as cur:
        cur.executemany("""
            INSERT INTO price_intervals (
                site_id, interval_start, interval_end, is_forecast,
                price_cents_per_kwh, spot_per_kwh, descriptor, spike_status,
                renewables_percent, source, raw_event_id
            ) VALUES (
                %(site_id)s, %(interval_start)s, %(interval_end)s, %(is_forecast)s,
                %(price_cents_per_kwh)s, %(spot_per_kwh)s, %(descriptor)s, %(spike_status)s,
                %(renewables_percent)s, %(source)s, %(raw_event_id)s
            )
            ON CONFLICT (site_id, interval_start, is_forecast, source)
            DO UPDATE SET
                interval_end = EXCLUDED.interval_end,
                price_cents_per_kwh = COALESCE(EXCLUDED.price_cents_per_kwh, price_intervals.price_cents_per_kwh),
                spot_per_kwh = COALESCE(EXCLUDED.spot_per_kwh, price_intervals.spot_per_kwh),
                descriptor = COALESCE(EXCLUDED.descriptor, price_intervals.descriptor),
                spike_status = COALESCE(EXCLUDED.spike_status, price_intervals.spike_status),
                renewables_percent = COALESCE(EXCLUDED.renewables_percent, price_intervals.renewables_percent),
                raw_event_id = COALESCE(EXCLUDED.raw_event_id, price_intervals.raw_event_id),
                ingested_at = NOW()
        """, normalized_rows)
        
        count = cur.rowcount
        conn.commit()
        return count


def upsert_usage_intervals(conn: psycopg.Connection, rows: List[Dict[str, Any]]) -> int:
    """
    Upsert usage interval rows into the database.
    
    Uses INSERT ... ON CONFLICT DO UPDATE with COALESCE to preserve existing
    non-null values when new data has nulls.
    
    Args:
        conn: Database connection
        rows: List of dictionaries with keys:
            - site_id (required)
            - channel_type (required, text, default 'general')
            - interval_start (required, datetime or ISO string)
            - interval_end (required, datetime or ISO string)
            - kwh (required, numeric)
            - cost_aud (optional, numeric)
            - quality (optional, text)
            - meter_identifier (optional, text)
            - source (optional, text, default 'amber')
            - raw_event_id (optional, UUID string)
            
    Returns:
        Number of rows inserted/updated
    """
    if not rows:
        return 0
    
    # Normalize datetime fields
    normalized_rows = []
    for row in rows:
        norm_row = row.copy()
        
        # Convert interval_start/interval_end to timezone-aware datetime if needed
        for field in ['interval_start', 'interval_end']:
            if field in norm_row and norm_row[field] is not None:
                if isinstance(norm_row[field], str):
                    # Parse ISO string
                    dt = datetime.fromisoformat(norm_row[field].replace('Z', '+00:00'))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    norm_row[field] = dt
                elif isinstance(norm_row[field], datetime):
                    # Ensure timezone-aware
                    if norm_row[field].tzinfo is None:
                        norm_row[field] = norm_row[field].replace(tzinfo=timezone.utc)
        
        # Default channel_type
        if 'channel_type' not in norm_row:
            norm_row['channel_type'] = 'general'
        
        # Default source
        if 'source' not in norm_row:
            norm_row['source'] = 'amber'
        
        normalized_rows.append(norm_row)
    
    with conn.cursor() as cur:
        cur.executemany("""
            INSERT INTO usage_intervals (
                site_id, channel_type, interval_start, interval_end,
                kwh, cost_aud, quality, meter_identifier, source, raw_event_id
            ) VALUES (
                %(site_id)s, %(channel_type)s, %(interval_start)s, %(interval_end)s,
                %(kwh)s, %(cost_aud)s, %(quality)s, %(meter_identifier)s, %(source)s, %(raw_event_id)s
            )
            ON CONFLICT (site_id, channel_type, interval_start, source)
            DO UPDATE SET
                interval_end = EXCLUDED.interval_end,
                kwh = EXCLUDED.kwh,
                cost_aud = COALESCE(EXCLUDED.cost_aud, usage_intervals.cost_aud),
                quality = COALESCE(EXCLUDED.quality, usage_intervals.quality),
                meter_identifier = COALESCE(EXCLUDED.meter_identifier, usage_intervals.meter_identifier),
                raw_event_id = COALESCE(EXCLUDED.raw_event_id, usage_intervals.raw_event_id),
                ingested_at = NOW()
        """, normalized_rows)
        
        count = cur.rowcount
        conn.commit()
        return count

