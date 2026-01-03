#!/usr/bin/env python3
"""
Backfill Amber price data into Supabase in chunks with resume support.

Usage:
    python scripts/backfill_amber_prices_to_supabase.py --start 2024-06-16 --end 2025-01-01 --chunk-days 7
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
    is_forecast: bool
) -> Optional[datetime]:
    """
    Query Supabase for the latest interval_start for the given site_id/source/is_forecast.
    
    Returns:
        Latest interval_start as timezone-aware datetime, or None if no data exists.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT MAX(interval_start) as max_start
            FROM price_intervals
            WHERE site_id = %s AND source = %s AND is_forecast = %s
        """, (site_id, source, is_forecast))
        
        row = cur.fetchone()
        if row and row[0]:
            return row[0] if row[0].tzinfo else row[0].replace(tzinfo=timezone.utc)
        return None


def normalize_price_row(
    raw_price: Dict[str, Any],
    site_id: str,
    source: str,
    is_forecast: bool,
    raw_event_id: str
) -> Dict[str, Any]:
    """
    Normalize a raw Amber price API response to database format.
    
    Args:
        raw_price: Raw price dict from Amber API (with keys like startTime, endTime, perKwh, etc.)
        site_id: Site ID
        source: Data source (default 'amber')
        is_forecast: Whether this is forecast data
        raw_event_id: UUID string of the ingest event
        
    Returns:
        Normalized dict with keys matching upsert_price_intervals requirements
    """
    # Parse timestamps
    interval_start = None
    interval_end = None
    
    if "startTime" in raw_price:
        interval_start = datetime.fromisoformat(raw_price["startTime"].replace("Z", "+00:00"))
    elif "nemTime" in raw_price:
        # Fallback to nemTime if startTime not available
        interval_start = datetime.fromisoformat(raw_price["nemTime"].replace("Z", "+00:00"))
    
    if "endTime" in raw_price:
        interval_end = datetime.fromisoformat(raw_price["endTime"].replace("Z", "+00:00"))
    elif interval_start and "duration" in raw_price:
        # Calculate end from start + duration (duration in minutes)
        duration_minutes = raw_price.get("duration", 30)
        interval_end = interval_start + timedelta(minutes=duration_minutes)
    
    # Ensure timezone-aware
    if interval_start and interval_start.tzinfo is None:
        interval_start = interval_start.replace(tzinfo=timezone.utc)
    if interval_end and interval_end.tzinfo is None:
        interval_end = interval_end.replace(tzinfo=timezone.utc)
    
    # Handle price: perKwh is in cents, convert to cents if needed
    price_cents_per_kwh = None
    if "perKwh" in raw_price and raw_price["perKwh"] is not None:
        price_cents_per_kwh = float(raw_price["perKwh"])
    
    # Optional fields
    spot_per_kwh = None
    if "spotPerKwh" in raw_price and raw_price["spotPerKwh"] is not None:
        spot_per_kwh = float(raw_price["spotPerKwh"])
    
    descriptor = raw_price.get("descriptor")
    spike_status = raw_price.get("spikeStatus")
    
    renewables_percent = None
    if "renewables" in raw_price and raw_price["renewables"] is not None:
        renewables_percent = float(raw_price["renewables"])
    
    return {
        "site_id": site_id,
        "interval_start": interval_start,
        "interval_end": interval_end,
        "is_forecast": is_forecast,
        "price_cents_per_kwh": price_cents_per_kwh,
        "spot_per_kwh": spot_per_kwh,
        "descriptor": descriptor,
        "spike_status": spike_status,
        "renewables_percent": renewables_percent,
        "source": source,
        "raw_event_id": raw_event_id,
    }


def fetch_prices_with_retry(
    client: AmberClient,
    site_id: str,
    window_start: date,
    window_end: date,
    max_retries: int = 5,
    initial_backoff: float = 1.0
) -> List[Dict[str, Any]]:
    """
    Fetch prices from Amber API with retry logic.
    
    Args:
        client: AmberClient instance
        site_id: Site ID
        window_start: Start date (inclusive)
        window_end: End date (inclusive)
        max_retries: Maximum number of retry attempts
        initial_backoff: Initial backoff time in seconds
        
    Returns:
        List of raw price dictionaries from Amber API
        
    Raises:
        AmberAPIError: If all retries fail
    """
    backoff = initial_backoff
    
    for attempt in range(max_retries):
        try:
            return client.get_prices_range(site_id, window_start, window_end)
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
                logger.error(f"Failed to fetch prices after {attempt + 1} attempts: {e}")
                raise
    
    # Should never reach here, but just in case
    raise AmberAPIError(f"Failed to fetch prices after {max_retries} attempts")


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Backfill Amber price data into Supabase"
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
        help="End date (YYYY-MM-DD, default: today in UTC)"
    )
    parser.add_argument(
        "--chunk-days",
        type=int,
        default=7,
        help="Number of days per chunk (default: 7)"
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
        "--is-forecast",
        type=_parse_bool,
        default=False,
        help="Whether prices are forecasts (default: false)"
    )
    
    args = parser.parse_args()
    
    if args.start > args.end:
        logger.error("--start must be on or before --end")
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
            max_interval = get_max_interval_start(conn, site_id, args.source, args.is_forecast)
            if max_interval:
                # Start from the next interval after the latest one
                # Convert to date and add 1 day to start from next day
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
        
        while current_start <= args.end:
            # Calculate chunk end (exclusive, so we use < for comparison)
            chunk_end_date = min(current_start + timedelta(days=args.chunk_days), args.end + timedelta(days=1))
            chunk_end_exclusive = chunk_end_date - timedelta(days=1)  # Make inclusive
            
            chunk_start_dt = datetime.combine(current_start, datetime.min.time()).replace(tzinfo=timezone.utc)
            chunk_end_dt = datetime.combine(chunk_end_exclusive, datetime.max.time()).replace(tzinfo=timezone.utc)
            
            logger.info(f"Processing chunk: {current_start} to {chunk_end_exclusive} (inclusive)")
            
            chunk_start_time = time.time()
            
            try:
                # Fetch prices with retry
                raw_prices = fetch_prices_with_retry(
                    client, site_id, current_start, chunk_end_exclusive
                )
                
                if not raw_prices:
                    logger.warning(f"No prices returned for {current_start} to {chunk_end_exclusive}")
                    current_start = chunk_end_date
                    continue
                
                # Normalize rows
                rows = []
                for raw_price in raw_prices:
                    try:
                        norm_row = normalize_price_row(
                            raw_price, site_id, args.source, args.is_forecast, ""
                        )
                        # Only include rows with valid timestamps
                        if norm_row.get("interval_start") and norm_row.get("interval_end"):
                            rows.append(norm_row)
                    except Exception as e:
                        logger.warning(f"Failed to normalize price row: {e}")
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
                    "prices",
                    payload_dict,
                    window_start=chunk_start_dt,
                    window_end=chunk_end_dt,
                )
                
                # Update rows with event ID
                for row in rows:
                    row["raw_event_id"] = raw_event_id
                
                # Upsert rows
                upserted_count = supabase_db.upsert_price_intervals(conn, rows)
                
                chunk_duration = time.time() - chunk_start_time
                total_rows += len(rows)
                total_upserted += upserted_count
                
                logger.info(
                    f"✓ Chunk complete: fetched {len(raw_prices)} rows, "
                    f"normalized {len(rows)} rows, upserted {upserted_count} rows "
                    f"in {chunk_duration:.1f}s"
                )
                
            except Exception as e:
                logger.error(f"Error processing chunk {current_start} to {chunk_end_exclusive}: {e}")
                import traceback
                traceback.print_exc()
                # Continue to next chunk
                pass
            
            # Move to next chunk
            current_start = chunk_end_date
        
        logger.info(f"Backfill complete: {total_rows} rows fetched, {total_upserted} rows upserted")
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

