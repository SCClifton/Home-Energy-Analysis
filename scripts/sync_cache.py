#!/usr/bin/env python3
"""
Sync SQLite cache with latest data from Amber API.

Fetches current price and latest usage data and updates the cache.
"""
import os
import sys
from pathlib import Path

# Add project root to path to import amber_client
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from ingestion.amber_client import AmberClient, AmberAPIError
from home_energy_analysis.storage.factory import get_sqlite_cache
from home_energy_analysis.storage import sqlite_cache


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
                price_row = {
                    "site_id": site_id,
                    "interval_start": price.get("startTime"),
                    "interval_end": price.get("endTime"),
                    "channel_type": channel_type,
                    "per_kwh": price.get("perKwh"),
                    "renewables": price.get("renewables"),
                    "descriptor": price.get("descriptor")
                }
                price_rows.append(price_row)
            
            # Get latest price timestamp (first one is most recent)
            latest_price_ts = prices[0].get("startTime")
        
        # Fetch latest usage (same as dashboard uses)
        usage_data = client.get_usage_recent(site_id, intervals=1)
        
        usage_rows = []
        latest_usage_ts = None
        
        if usage_data and len(usage_data) > 0:
            # Transform usage data to cache row format
            for usage in usage_data:
                usage_row = {
                    "site_id": site_id,
                    "interval_start": usage.get("startTime"),
                    "interval_end": usage.get("endTime"),
                    "channel_type": channel_type,
                    "kwh": usage.get("kwh")
                }
                usage_rows.append(usage_row)
            
            # Get latest usage timestamp
            latest_usage_ts = usage_data[0].get("startTime")
        
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

