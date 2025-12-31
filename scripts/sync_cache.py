#!/usr/bin/env python3
"""
Sync SQLite cache with latest data from Amber API.

Fetches current price and latest usage data and updates the cache.
"""
import os
import sys
from pathlib import Path
from datetime import datetime, timezone

# Add project root to path to import amber_client
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from ingestion.amber_client import AmberClient, AmberAPIError
from home_energy_analysis.storage.factory import get_sqlite_cache
from home_energy_analysis.storage import sqlite_cache


def parse_iso_z(ts: str) -> datetime:
    """Parse ISO8601 timestamp with trailing 'Z' to datetime."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def floor_to_5min(dt: datetime) -> datetime:
    """
    Floor a datetime to the nearest 5-minute boundary in UTC.
    Strip seconds and microseconds.
    
    Args:
        dt: Datetime to floor (assumed to be timezone-aware, will convert to UTC)
        
    Returns:
        Datetime floored to 5-minute boundary in UTC
    """
    # Ensure UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    
    # Floor to 5-minute boundary: remove seconds/microseconds, floor minute
    floored_minute = (dt.minute // 5) * 5
    return dt.replace(minute=floored_minute, second=0, microsecond=0)


def normalize_interval_timestamp(ts: str) -> str:
    """
    Normalize an ISO8601 timestamp string to a 5-minute boundary.
    
    Args:
        ts: ISO8601 timestamp string (e.g., "2024-01-01T01:50:01Z")
        
    Returns:
        Normalized ISO8601 timestamp string (e.g., "2024-01-01T01:50:00Z")
    """
    dt = parse_iso_z(ts)
    normalized = floor_to_5min(dt)
    return normalized.isoformat().replace("+00:00", "Z")


def main():
    """Main entry point for sync_cache script."""
    # Read required environment variables
    token = os.getenv("AMBER_TOKEN")
    site_id = os.getenv("AMBER_SITE_ID")
    
    if not token:
        print("ERROR: AMBER_TOKEN environment variable is not set", file=sys.stderr)
        sys.exit(1)
    
    if not site_id:
        print("ERROR: AMBER_SITE_ID environment variable is not set", file=sys.stderr)
        sys.exit(1)
    
    # Get cache path (uses SQLITE_PATH env var or default)
    cache_path = get_sqlite_cache()
    
    # Get retention days (default 14)
    retention_days = int(os.getenv("RETENTION_DAYS", "14"))
    
    channel_type = "general"
    
    try:
        client = AmberClient(token=token)
        
        # Fetch current prices (same as dashboard uses)
        prices = client.get_prices_current(site_id)
        
        price_rows = []
        latest_price_ts = None
        
        if prices and len(prices) > 0:
            # Transform price data to cache row format
            for price in prices:
                # Normalize timestamps before caching
                interval_start_raw = price.get("startTime")
                interval_end_raw = price.get("endTime")
                interval_start = normalize_interval_timestamp(interval_start_raw)
                interval_end = normalize_interval_timestamp(interval_end_raw)
                
                price_row = {
                    "site_id": site_id,
                    "interval_start": interval_start,
                    "interval_end": interval_end,
                    "channel_type": channel_type,
                    "per_kwh": price.get("perKwh"),
                    "renewables": price.get("renewables"),
                    "descriptor": price.get("descriptor")
                }
                price_rows.append(price_row)
            
            # Get latest price timestamp (first one is most recent, normalized)
            latest_price_ts = normalize_interval_timestamp(prices[0].get("startTime"))
        
        # Fetch latest usage (same as dashboard uses)
        usage_data = client.get_usage_recent(site_id, intervals=1)
        
        usage_rows = []
        latest_usage_ts = None
        
        if usage_data and len(usage_data) > 0:
            # Transform usage data to cache row format
            for usage in usage_data:
                # Normalize timestamps before caching
                interval_start_raw = usage.get("startTime")
                interval_end_raw = usage.get("endTime")
                interval_start = normalize_interval_timestamp(interval_start_raw)
                interval_end = normalize_interval_timestamp(interval_end_raw)
                
                usage_row = {
                    "site_id": site_id,
                    "interval_start": interval_start,
                    "interval_end": interval_end,
                    "channel_type": channel_type,
                    "kwh": usage.get("kwh")
                }
                usage_rows.append(usage_row)
            
            # Get latest usage timestamp (normalized)
            latest_usage_ts = normalize_interval_timestamp(usage_data[0].get("startTime"))
        
        # Upsert prices
        if price_rows:
            sqlite_cache.upsert_prices(cache_path, price_rows)
        
        # Upsert usage
        if usage_rows:
            sqlite_cache.upsert_usage(cache_path, usage_rows)
        
        # Prune old data
        deleted_count = sqlite_cache.prune_old_data(cache_path, retention_days)
        
        # Output success message
        latest_price_str = latest_price_ts if latest_price_ts else "none"
        latest_usage_str = latest_usage_ts if latest_usage_ts else "none"
        print(f"sync_cache ok prices={len(price_rows)} usage={len(usage_rows)} latest_price={latest_price_str} latest_usage={latest_usage_str}")
        
        sys.exit(0)
        
    except AmberAPIError as e:
        print(f"ERROR: Amber API error: {str(e)}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: Unexpected error: {str(e)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

