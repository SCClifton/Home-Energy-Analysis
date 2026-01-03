#!/usr/bin/env python3
"""
Backfill Amber usage data into Supabase in chunks with resume support and adaptive chunking.

Usage:
    python scripts/backfill_amber_usage_to_supabase.py --start 2024-06-16 --end 2025-01-01 --chunk-days 7
"""
import argparse
import os
import sys
import logging
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List

from dotenv import load_dotenv
import psycopg

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from ingestion.amber_client import AmberClient, AmberAPIError
from home_energy_analysis.storage import supabase_db

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


def _parse_date(value: str) -> date:
    """Parse YYYY-MM-DD date string."""
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid date '{value}', expected YYYY-MM-DD") from exc


def _parse_bool(value: str) -> bool:
    """Parse true/false string to boolean."""
    return value.lower() == "true"


def get_max_interval_start(
    conn: psycopg.Connection,
    site_id: str,
    source: str,
    channel_type: str
) -> Optional[datetime]:
    """
    Query Supabase for the latest interval_start for the given site_id/source/channel_type.
    
    Returns:
        Latest interval_start as timezone-aware datetime, or None if no data exists.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT MAX(interval_start) as max_start
            FROM usage_intervals
            WHERE site_id = %s AND source = %s AND channel_type = %s
        """, (site_id, source, channel_type))
        
        row = cur.fetchone()
        if row and row[0]:
            return row[0] if row[0].tzinfo else row[0].replace(tzinfo=timezone.utc)
        return None


def normalize_usage_row(
    raw_usage: Dict[str, Any],
    site_id: str,
    source: str,
    channel_type: str,
    raw_event_id: str
) -> Dict[str, Any]:
    """
    Normalize a raw Amber usage API response to database format.
    
    Args:
        raw_usage: Raw usage dict from Amber API (with keys like startTime, endTime, kwh, etc.)
        site_id: Site ID
        source: Data source (default 'amber')
        channel_type: Channel type (default 'general')
        raw_event_id: UUID string of the ingest event
        
    Returns:
        Normalized dict with keys matching upsert_usage_intervals requirements
    """
    # Parse timestamps
    interval_start = None
    interval_end = None
    
    if "startTime" in raw_usage:
        interval_start = datetime.fromisoformat(raw_usage["startTime"].replace("Z", "+00:00"))
    elif "nemTime" in raw_usage:
        # Fallback to nemTime if startTime not available
        interval_start = datetime.fromisoformat(raw_usage["nemTime"].replace("Z", "+00:00"))
    
    if "endTime" in raw_usage:
        interval_end = datetime.fromisoformat(raw_usage["endTime"].replace("Z", "+00:00"))
    elif interval_start and "duration" in raw_usage:
        # Calculate end from start + duration (duration in minutes)
        duration_minutes = raw_usage.get("duration", 30)
        interval_end = interval_start + timedelta(minutes=duration_minutes)
    
    # Ensure timezone-aware
    if interval_start and interval_start.tzinfo is None:
        interval_start = interval_start.replace(tzinfo=timezone.utc)
    if interval_end and interval_end.tzinfo is None:
        interval_end = interval_end.replace(tzinfo=timezone.utc)
    
    # Required field: kwh
    kwh = None
    if "kwh" in raw_usage and raw_usage["kwh"] is not None:
        kwh = float(raw_usage["kwh"])
    
    # Optional fields
    cost_aud = None
    if "cost" in raw_usage and raw_usage["cost"] is not None:
        cost_aud = float(raw_usage["cost"])
    
    quality = raw_usage.get("quality")
    
    meter_identifier = None
    if "channelIdentifier" in raw_usage:
        meter_identifier = raw_usage["channelIdentifier"]
    elif "meterIdentifier" in raw_usage:
        meter_identifier = raw_usage["meterIdentifier"]
    
    return {
        "site_id": site_id,
        "channel_type": channel_type,
        "interval_start": interval_start,
        "interval_end": interval_end,
        "kwh": kwh,
        "cost_aud": cost_aud,
        "quality": quality,
        "meter_identifier": meter_identifier,
        "source": source,
        "raw_event_id": raw_event_id,
    }


def is_chunk_too_large_error(error: Exception) -> bool:
    """
    Check if an error indicates the chunk window is too large.
    
    Returns:
        True if the error suggests reducing chunk size
    """
    if isinstance(error, AmberAPIError):
        # 400 Bad Request might indicate invalid date range
        # 422 Unprocessable Entity might indicate range too large
        if error.status_code in (400, 422):
            error_text = (error.response_text or "").lower()
            # Check for common error messages
            if any(phrase in error_text for phrase in [
                "date range", "too large", "invalid", "exceed", "limit"
            ]):
                return True
    return False


def fetch_usage_with_retry(
    client: AmberClient,
    site_id: str,
    window_start: date,
    window_end: date,
    resolution: Optional[str] = None,
    max_retries: int = 5,
    initial_backoff: float = 1.0
) -> List[Dict[str, Any]]:
    """
    Fetch usage from Amber API with retry logic.
    
    Args:
        client: AmberClient instance
        site_id: Site ID
        window_start: Start date (inclusive)
        window_end: End date (inclusive)
        resolution: Optional resolution parameter
        max_retries: Maximum number of retry attempts
        initial_backoff: Initial backoff time in seconds
        
    Returns:
        List of raw usage dictionaries from Amber API
        
    Raises:
        AmberAPIError: If all retries fail
    """
    backoff = initial_backoff
    
    for attempt in range(max_retries):
        try:
            return client.get_usage_range(site_id, window_start, window_end, resolution=resolution)
        except (AmberAPIError, Exception) as e:
            # Check if it's a retryable error
            is_retryable = False
            if isinstance(e, AmberAPIError):
                # Retry on 5xx, 429, or network errors
                if e.status_code in (429, 500, 502, 503, 504):
                    is_retryable = True
            elif isinstance(e, (ConnectionError, TimeoutError)):
                is_retryable = True
            
            if is_retryable and attempt < max_retries - 1:
                logger.warning(
                    f"Attempt {attempt + 1}/{max_retries} failed for {window_start} to {window_end}: {e}. "
                    f"Retrying in {backoff:.1f}s..."
                )
                time.sleep(backoff)
                backoff *= 2  # Exponential backoff
            else:
                # Not retryable or last attempt
                logger.error(f"Failed to fetch usage after {attempt + 1} attempts: {e}")
                raise
    
    # Should never reach here, but just in case
    raise AmberAPIError(f"Failed to fetch usage after {max_retries} attempts")


def fetch_usage_adaptive(
    client: AmberClient,
    site_id: str,
    window_start: date,
    window_end: date,
    initial_chunk_days: int,
    min_chunk_days: int,
    resolution: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Fetch usage with adaptive chunking: recursively split window if too large.
    
    If the initial window is too large, this function will recursively split it
    into smaller chunks until all data is fetched.
    
    Args:
        client: AmberClient instance
        site_id: Site ID
        window_start: Start date (inclusive)
        window_end: End date (inclusive)
        initial_chunk_days: Initial chunk size in days
        min_chunk_days: Minimum chunk size in days
        resolution: Optional resolution parameter
        
    Returns:
        List of raw usage dictionaries from Amber API (combined from all sub-chunks)
        
    Raises:
        AmberAPIError: If fetch fails even at minimum chunk size
    """
    # Calculate window size
    window_days = (window_end - window_start).days + 1
    
    # If window fits in initial chunk, try direct fetch
    if window_days <= initial_chunk_days:
        try:
            return fetch_usage_with_retry(client, site_id, window_start, window_end, resolution)
        except AmberAPIError as e:
            if is_chunk_too_large_error(e) and window_days > min_chunk_days:
                # Window is too large, need to split
                pass
            else:
                # Not a size issue, re-raise
                raise
    
    # Window is too large or fetch failed due to size, split it
    if window_days <= min_chunk_days:
        # Already at minimum, try one more time
        return fetch_usage_with_retry(client, site_id, window_start, window_end, resolution)
    
    # Split window in half and recursively fetch both halves
    mid_date = window_start + timedelta(days=window_days // 2)
    logger.info(
        f"Splitting window {window_start} to {window_end} ({window_days} days) "
        f"into two chunks"
    )
    
    results = []
    
    # Fetch first half
    try:
        first_half = fetch_usage_adaptive(
            client, site_id, window_start, mid_date - timedelta(days=1),
            initial_chunk_days, min_chunk_days, resolution
        )
        results.extend(first_half)
    except Exception as e:
        logger.error(f"Failed to fetch first half ({window_start} to {mid_date - timedelta(days=1)}): {e}")
        raise
    
    # Fetch second half
    try:
        second_half = fetch_usage_adaptive(
            client, site_id, mid_date, window_end,
            initial_chunk_days, min_chunk_days, resolution
        )
        results.extend(second_half)
    except Exception as e:
        logger.error(f"Failed to fetch second half ({mid_date} to {window_end}): {e}")
        raise
    
    return results


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Backfill Amber usage data into Supabase with adaptive chunking"
    )
    parser.add_argument(
        "--start",
        type=_parse_date,
        default=date(2024, 6, 16),
        help="Start date (YYYY-MM-DD, default: 2024-06-16)"
    )
    parser.add_argument(
        "--end",
        type=_parse_date,
        default=date.today(),
        help="End date (YYYY-MM-DD, default: today)"
    )
    parser.add_argument(
        "--chunk-days",
        type=int,
        default=7,
        help="Initial chunk size in days (default: 7)"
    )
    parser.add_argument(
        "--min-chunk-days",
        type=int,
        default=1,
        help="Minimum chunk size in days (default: 1)"
    )
    parser.add_argument(
        "--resume",
        type=_parse_bool,
        default=True,
        help="Resume from latest interval in database (default: true)"
    )
    parser.add_argument(
        "--source",
        default="amber",
        help="Data source (default: amber)"
    )
    parser.add_argument(
        "--channel-type",
        default="general",
        help="Channel type (default: general)"
    )
    
    args = parser.parse_args()
    
    if args.start > args.end:
        logger.error("--start must be on or before --end")
        return 1
    
    if args.chunk_days < args.min_chunk_days:
        logger.error("--chunk-days must be >= --min-chunk-days")
        return 1
    
    # Load environment variables in specified order
    load_dotenv("config/.env", override=False)
    load_dotenv(".env.local", override=True)
    
    # Check required environment variables
    amber_token = os.getenv("AMBER_TOKEN")
    site_id = os.getenv("AMBER_SITE_ID")
    supabase_url = os.getenv("SUPABASE_DB_URL")
    
    if not amber_token:
        logger.error("AMBER_TOKEN not found in config/.env")
        return 1
    if not site_id:
        logger.error("AMBER_SITE_ID not found in config/.env")
        return 1
    if not supabase_url:
        logger.error("SUPABASE_DB_URL not found in .env.local")
        return 1
    
    # Initialize clients
    try:
        client = AmberClient(token=amber_token)
        conn = supabase_db.get_conn()
    except Exception as e:
        logger.error(f"Failed to initialize clients: {e}")
        return 1
    
    try:
        # Determine start date (resume logic)
        actual_start = args.start
        if args.resume:
            max_interval = get_max_interval_start(conn, site_id, args.source, args.channel_type)
            if max_interval:
                # Start from the next interval after the latest one
                max_date = max_interval.date()
                actual_start = max_date + timedelta(days=1)
                logger.info(f"Resuming from {actual_start} (latest in DB: {max_interval})")
            else:
                logger.info(f"No existing data found, starting from {actual_start}")
        else:
            logger.info(f"Starting from {actual_start} (resume disabled)")
        
        if actual_start > args.end:
            logger.info(f"Already up to date (start {actual_start} > end {args.end})")
            return 0
        
        # Process in chunks
        current_start = actual_start
        total_rows = 0
        total_upserted = 0
        skipped_windows = 0
        
        while current_start <= args.end:
            # Calculate chunk end (exclusive, so we use < for comparison)
            chunk_end_date = min(current_start + timedelta(days=args.chunk_days), args.end + timedelta(days=1))
            chunk_end_exclusive = chunk_end_date - timedelta(days=1)  # Make inclusive
            
            chunk_start_dt = datetime.combine(current_start, datetime.min.time()).replace(tzinfo=timezone.utc)
            chunk_end_dt = datetime.combine(chunk_end_exclusive, datetime.max.time()).replace(tzinfo=timezone.utc)
            
            logger.info(f"Processing chunk: {current_start} to {chunk_end_exclusive} (inclusive)")
            
            chunk_start_time = time.time()
            
            try:
                # Fetch usage with adaptive chunking
                raw_usage = fetch_usage_adaptive(
                    client,
                    site_id,
                    current_start,
                    chunk_end_exclusive,
                    args.chunk_days,
                    args.min_chunk_days
                )
                
                if not raw_usage:
                    logger.warning(f"No usage returned for {current_start} to {chunk_end_exclusive}")
                    current_start = chunk_end_date
                    continue
                
                # Normalize rows
                rows = []
                for raw_item in raw_usage:
                    try:
                        norm_row = normalize_usage_row(
                            raw_item, site_id, args.source, args.channel_type, ""
                        )
                        # Only include rows with valid timestamps and kwh
                        if (norm_row.get("interval_start") and 
                            norm_row.get("interval_end") and 
                            norm_row.get("kwh") is not None):
                            rows.append(norm_row)
                    except Exception as e:
                        logger.warning(f"Failed to normalize usage row: {e}")
                        continue
                
                if not rows:
                    logger.warning(f"No valid rows after normalization for {current_start} to {chunk_end_exclusive}")
                    current_start = chunk_end_date
                    continue
                
                # Create ingest event
                payload_dict = {
                    "window": f"{current_start.isoformat()}_{chunk_end_exclusive.isoformat()}",
                    "count": len(rows),
                    "file": "amber_api",
                }
                
                raw_event_id = supabase_db.insert_ingest_event(
                    conn,
                    args.source,
                    "usage",
                    payload_dict,
                    window_start=chunk_start_dt,
                    window_end=chunk_end_dt,
                )
                
                # Update rows with event ID
                for row in rows:
                    row["raw_event_id"] = raw_event_id
                
                # Upsert rows
                upserted_count = supabase_db.upsert_usage_intervals(conn, rows)
                
                chunk_duration = time.time() - chunk_start_time
                total_rows += len(rows)
                total_upserted += upserted_count
                
                logger.info(
                    f"✓ Chunk complete: fetched {len(raw_usage)} rows, "
                    f"normalized {len(rows)} rows, upserted {upserted_count} rows "
                    f"in {chunk_duration:.1f}s"
                )
                
            except Exception as e:
                logger.error(f"Error processing chunk {current_start} to {chunk_end_exclusive}: {e}")
                import traceback
                traceback.print_exc()
                # Skip this window and continue
                skipped_windows += 1
                if skipped_windows >= 5:
                    logger.error("Too many skipped windows, aborting")
                    return 1
                pass
            
            # Move to next chunk
            current_start = chunk_end_date
        
        logger.info(
            f"Backfill complete: {total_rows} rows fetched, {total_upserted} rows upserted, "
            f"{skipped_windows} windows skipped"
        )
        return 0
        
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

