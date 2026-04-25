#!/usr/bin/env python3
"""
Backfill Amber usage data into Supabase in chunks with resume support and adaptive chunking.

Usage:
    python scripts/backfill_amber_usage_to_supabase.py --start 2024-06-16 --end 2025-01-01 --chunk-days 7
"""
import argparse
import os
import random
import sys
import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable, Optional, Dict, Any, List

from dotenv import load_dotenv
import psycopg

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from home_energy_analysis.ingestion import AmberClient, AmberAPIError
from home_energy_analysis.storage import supabase_db

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BackoffConfig:
    """Retry and request pacing settings for Amber usage backfill."""

    max_retries: int = 5
    base_backoff_seconds: float = 2.0
    max_backoff_seconds: float = 300.0
    jitter_seconds: float = 0.5


def _parse_date(value: str) -> date:
    """Parse YYYY-MM-DD date string."""
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid date '{value}', expected YYYY-MM-DD") from exc


def _parse_bool(value: str) -> bool:
    """Parse true/false string to boolean."""
    return value.lower() == "true"


def parse_retry_after(value: Optional[str], now: Optional[datetime] = None) -> Optional[float]:
    """
    Parse Retry-After as seconds or an HTTP date.

    Returns:
        Non-negative delay in seconds, or None when the value is absent/invalid.
    """
    if not value:
        return None

    value = value.strip()
    if not value:
        return None

    try:
        seconds = float(value)
        return max(0.0, seconds)
    except ValueError:
        pass

    try:
        retry_dt = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None

    if retry_dt.tzinfo is None:
        retry_dt = retry_dt.replace(tzinfo=timezone.utc)

    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)

    return max(0.0, (retry_dt.astimezone(timezone.utc) - now).total_seconds())


def retry_after_delay(error: AmberAPIError, now: Optional[datetime] = None) -> Optional[float]:
    """Return Retry-After delay from an Amber API error, if available."""
    headers = getattr(error, "response_headers", None) or {}
    for key, value in headers.items():
        if key.lower() == "retry-after":
            return parse_retry_after(str(value), now=now)
    return None


def backoff_delay(attempt: int, config: BackoffConfig, jitter_fn: Callable[[float, float], float] = random.uniform) -> float:
    """Return capped exponential backoff delay with optional jitter."""
    delay = min(
        config.max_backoff_seconds,
        config.base_backoff_seconds * (2 ** max(0, attempt)),
    )
    if config.jitter_seconds > 0:
        delay += jitter_fn(0.0, config.jitter_seconds)
    return delay


def reduced_chunk_days(active_chunk_days: int, min_chunk_days: int) -> int:
    """Reduce chunk size for repeated rate limits without going below the minimum."""
    return max(min_chunk_days, max(1, active_chunk_days // 2))


def restored_chunk_days(active_chunk_days: int, target_chunk_days: int) -> int:
    """Gradually restore chunk size after successful windows."""
    if active_chunk_days >= target_chunk_days:
        return target_chunk_days
    return min(target_chunk_days, max(active_chunk_days + 1, active_chunk_days * 2))


def is_rate_limit_error(error: Exception) -> bool:
    """Return True when the exception is an Amber HTTP 429."""
    return isinstance(error, AmberAPIError) and error.status_code == 429


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
    backoff_config: Optional[BackoffConfig] = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    jitter_fn: Callable[[float, float], float] = random.uniform,
) -> List[Dict[str, Any]]:
    """
    Fetch usage from Amber API with retry logic.
    
    Args:
        client: AmberClient instance
        site_id: Site ID
        window_start: Start date (inclusive)
        window_end: End date (inclusive)
        resolution: Optional resolution parameter
        backoff_config: Retry/backoff configuration
        sleep_fn: Sleep function for tests and runtime delays
        jitter_fn: Jitter function for tests and runtime delays
        
    Returns:
        List of raw usage dictionaries from Amber API
        
    Raises:
        AmberAPIError: If all retries fail
    """
    if backoff_config is None:
        backoff_config = BackoffConfig()
    
    for attempt in range(backoff_config.max_retries):
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
            
            if is_retryable and attempt < backoff_config.max_retries - 1:
                retry_after = retry_after_delay(e) if is_rate_limit_error(e) else None
                delay = retry_after if retry_after is not None else backoff_delay(attempt, backoff_config, jitter_fn)
                logger.warning(
                    f"Attempt {attempt + 1}/{backoff_config.max_retries} failed for "
                    f"{window_start} to {window_end}: {e}. Retrying in {delay:.1f}s..."
                )
                if retry_after is not None:
                    logger.warning(
                        f"Respecting Retry-After={retry_after:.1f}s for "
                        f"{window_start} to {window_end}"
                    )
                sleep_fn(delay)
            else:
                # Not retryable or last attempt
                logger.error(f"Failed to fetch usage after {attempt + 1} attempts: {e}")
                raise
    
    # Should never reach here, but just in case
    raise AmberAPIError(f"Failed to fetch usage after {backoff_config.max_retries} attempts")


def fetch_usage_adaptive(
    client: AmberClient,
    site_id: str,
    window_start: date,
    window_end: date,
    initial_chunk_days: int,
    min_chunk_days: int,
    resolution: Optional[str] = None,
    backoff_config: Optional[BackoffConfig] = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    jitter_fn: Callable[[float, float], float] = random.uniform,
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
            return fetch_usage_with_retry(
                client,
                site_id,
                window_start,
                window_end,
                resolution,
                backoff_config=backoff_config,
                sleep_fn=sleep_fn,
                jitter_fn=jitter_fn,
            )
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
        return fetch_usage_with_retry(
            client,
            site_id,
            window_start,
            window_end,
            resolution,
            backoff_config=backoff_config,
            sleep_fn=sleep_fn,
            jitter_fn=jitter_fn,
        )
    
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
            initial_chunk_days, min_chunk_days, resolution,
            backoff_config=backoff_config,
            sleep_fn=sleep_fn,
            jitter_fn=jitter_fn,
        )
        results.extend(first_half)
    except Exception as e:
        logger.error(f"Failed to fetch first half ({window_start} to {mid_date - timedelta(days=1)}): {e}")
        raise
    
    # Fetch second half
    try:
        second_half = fetch_usage_adaptive(
            client, site_id, mid_date, window_end,
            initial_chunk_days, min_chunk_days, resolution,
            backoff_config=backoff_config,
            sleep_fn=sleep_fn,
            jitter_fn=jitter_fn,
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
    parser.add_argument(
        "--request-delay-seconds",
        type=float,
        default=1.0,
        help="Delay between successful chunk requests in seconds (default: 1.0)"
    )
    parser.add_argument(
        "--base-backoff-seconds",
        type=float,
        default=2.0,
        help="Base exponential backoff delay in seconds (default: 2.0)"
    )
    parser.add_argument(
        "--max-backoff-seconds",
        type=float,
        default=300.0,
        help="Maximum backoff delay in seconds (default: 300.0)"
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=5,
        help="Maximum fetch retry attempts per window (default: 5)"
    )
    parser.add_argument(
        "--jitter-seconds",
        type=float,
        default=0.5,
        help="Random jitter added to fallback backoff delays in seconds (default: 0.5)"
    )
    
    args = parser.parse_args()
    
    if args.start > args.end:
        logger.error("--start must be on or before --end")
        return 1
    
    if args.chunk_days < args.min_chunk_days:
        logger.error("--chunk-days must be >= --min-chunk-days")
        return 1

    if args.request_delay_seconds < 0:
        logger.error("--request-delay-seconds must be >= 0")
        return 1
    if args.base_backoff_seconds < 0:
        logger.error("--base-backoff-seconds must be >= 0")
        return 1
    if args.max_backoff_seconds < args.base_backoff_seconds:
        logger.error("--max-backoff-seconds must be >= --base-backoff-seconds")
        return 1
    if args.max_retries < 1:
        logger.error("--max-retries must be >= 1")
        return 1
    if args.jitter_seconds < 0:
        logger.error("--jitter-seconds must be >= 0")
        return 1

    backoff_config = BackoffConfig(
        max_retries=args.max_retries,
        base_backoff_seconds=args.base_backoff_seconds,
        max_backoff_seconds=args.max_backoff_seconds,
        jitter_seconds=args.jitter_seconds,
    )
    
    # Load local fallback env file for development. On Pi, systemd provides env.
    load_dotenv(project_root / ".env.local", override=False)
    
    # Check required environment variables
    amber_token = os.getenv("AMBER_TOKEN")
    site_id = os.getenv("AMBER_SITE_ID")
    supabase_url = os.getenv("SUPABASE_DB_URL")
    
    if not amber_token:
        logger.error("AMBER_TOKEN environment variable is required")
        return 1
    if not site_id:
        logger.error("AMBER_SITE_ID environment variable is required")
        return 1
    if not supabase_url:
        logger.error("SUPABASE_DB_URL environment variable is required")
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
        active_chunk_days = args.chunk_days
        total_rows = 0
        total_upserted = 0
        skipped_windows = 0
        rate_limited_windows = 0
        
        while current_start <= args.end:
            # Calculate chunk end (exclusive, so we use < for comparison)
            chunk_end_date = min(current_start + timedelta(days=active_chunk_days), args.end + timedelta(days=1))
            chunk_end_exclusive = chunk_end_date - timedelta(days=1)  # Make inclusive
            
            chunk_start_dt = datetime.combine(current_start, datetime.min.time()).replace(tzinfo=timezone.utc)
            chunk_end_dt = datetime.combine(chunk_end_exclusive, datetime.max.time()).replace(tzinfo=timezone.utc)
            
            logger.info(
                f"Processing chunk: {current_start} to {chunk_end_exclusive} "
                f"(inclusive, active_chunk_days={active_chunk_days})"
            )
            
            chunk_start_time = time.time()
            
            try:
                # Fetch usage with adaptive chunking
                raw_usage = fetch_usage_adaptive(
                    client,
                    site_id,
                    current_start,
                    chunk_end_exclusive,
                    active_chunk_days,
                    args.min_chunk_days,
                    backoff_config=backoff_config,
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

                restored = restored_chunk_days(active_chunk_days, args.chunk_days)
                if restored != active_chunk_days:
                    logger.info(
                        f"Restoring active chunk size after success: "
                        f"{active_chunk_days} -> {restored} days"
                    )
                    active_chunk_days = restored
                
            except AmberAPIError as e:
                if is_rate_limit_error(e):
                    rate_limited_windows += 1
                    reduced = reduced_chunk_days(active_chunk_days, args.min_chunk_days)
                    logger.warning(
                        f"Rate limited for {current_start} to {chunk_end_exclusive} after "
                        f"{args.max_retries} attempts. active_chunk_days={active_chunk_days}, "
                        f"next_chunk_days={reduced}, retrying same window"
                    )
                    if reduced == active_chunk_days:
                        logger.error(
                            f"Still rate limited at minimum chunk size ({args.min_chunk_days} day). "
                            "Aborting without marking the window as skipped."
                        )
                        return 1
                    active_chunk_days = reduced
                    continue

                logger.error(f"Error processing chunk {current_start} to {chunk_end_exclusive}: {e}")
                import traceback
                traceback.print_exc()
                # Skip this window and continue
                skipped_windows += 1
                if skipped_windows >= 5:
                    logger.error("Too many skipped windows, aborting")
                    return 1
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
            if current_start <= args.end and args.request_delay_seconds > 0:
                logger.info(f"Sleeping {args.request_delay_seconds:.1f}s before next chunk")
                time.sleep(args.request_delay_seconds)
        
        logger.info(
            f"Backfill complete: {total_rows} rows fetched, {total_upserted} rows upserted, "
            f"{skipped_windows} windows skipped, {rate_limited_windows} rate-limited retries"
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
