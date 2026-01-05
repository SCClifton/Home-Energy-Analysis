#!/usr/bin/env python3
"""
Load Powerpal minute-resolution CSV into Supabase usage_intervals table.

Usage:
    python scripts/load_powerpal_minute_to_supabase.py --csv data_raw/powerpal_minute/<file>.csv

Environment variables (required):
    SUPABASE_DB_URL (from .env.local)
    AMBER_SITE_ID (used as site_id in usage_intervals)
    
CLI options:
    --site-id (default: AMBER_SITE_ID env var)
    --source (default: powerpal)
    --channel-type (default: general)
"""
import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional

import pandas as pd
from dotenv import load_dotenv
from zoneinfo import ZoneInfo

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

# Load environment variables
load_dotenv(project_root / "config/.env", override=False)
load_dotenv(project_root / ".env.local", override=True)

from home_energy_analysis.storage import supabase_db

TZ = ZoneInfo("Australia/Sydney")


def detect_timestamp_column(df: pd.DataFrame) -> Optional[str]:
    """Detect timestamp column name from common variants."""
    candidates = [
        "timestamp",
        "time",
        "datetime",
        "dateTime",
        "date_time",
        "reading_time",
        "datetime_utc",
        "datetime_local",
        "ts",
        "epoch",
        "unix",
    ]
    for c in candidates:
        if c in df.columns:
            return c
    return None


def detect_kwh_column(df: pd.DataFrame) -> Optional[str]:
    """Detect kWh column name from common variants."""
    candidates = [
        "kwh",
        "kWh",
        "energy_kwh",
        "usage_kwh",
        "energy",
        "kwh_used",
        "watt_hours",
        "wattHours",
        "wh",
    ]
    for c in candidates:
        if c in df.columns:
            return c
    return None


def parse_timestamp_local_to_utc(ts_series: pd.Series, column_name: str, tz: ZoneInfo) -> tuple[pd.Series, str]:
    """
    Parse timestamp series to UTC, handling UTC and local timestamps.
    
    If column name contains "utc" (case-insensitive), parse as UTC directly.
    Otherwise, parse as local timezone (Australia/Sydney) with DST handling, then convert to UTC.
    
    Returns:
        (parsed_timestamps_utc, parse_mode_message)
    """
    is_utc_column = "utc" in column_name.lower()
    
    # If numeric, assume epoch seconds (always UTC)
    if pd.api.types.is_numeric_dtype(ts_series):
        dt_utc = pd.to_datetime(ts_series, unit="s", utc=True)
        mode_msg = "Parsed timestamps as UTC directly (epoch seconds)"
        return dt_utc, mode_msg
    
    # Parse as strings/datetimes
    if is_utc_column:
        # Parse as UTC directly
        dt_utc = pd.to_datetime(ts_series, utc=True, errors="coerce")
        mode_msg = f"Parsed timestamps as UTC directly ({column_name})"
        return dt_utc, mode_msg
    else:
        # Parse as local (Australia/Sydney), then convert to UTC
        dt_parsed = pd.to_datetime(ts_series, errors="coerce")
        
        # If no timezone info, localize to local timezone with DST handling
        if dt_parsed.dt.tz is None:
            try:
                # Try with infer for ambiguous times (DST transitions)
                dt_local = dt_parsed.dt.tz_localize(tz, ambiguous="infer", nonexistent="shift_forward")
            except (pd.errors.AmbiguousTimeError, ValueError, TypeError):
                # If infer fails (e.g., non-monotonic timestamps), use NaT for ambiguous times
                dt_local = dt_parsed.dt.tz_localize(tz, ambiguous="NaT", nonexistent="shift_forward")
        else:
            # If has timezone info, convert to local first
            dt_local = dt_parsed.dt.tz_convert(tz)
        
        # Convert local to UTC
        dt_utc = dt_local.dt.tz_convert(timezone.utc)
        mode_msg = f"Parsed timestamps as Australia/Sydney local then converted to UTC ({column_name})"
        return dt_utc, mode_msg


def normalize_energy_to_kwh(value: float, column_name: str) -> float:
    """Convert energy value to kWh based on column name."""
    col_lower = column_name.lower()
    if "watt_hours" in col_lower or col_lower in {"wh", "watthours"}:
        return value / 1000.0  # Wh to kWh
    # Assume already in kWh
    return value


def build_usage_intervals(
    df: pd.DataFrame,
    timestamp_col: str,
    kwh_col: str,
    site_id: str,
    channel_type: str,
    source: str,
    raw_event_id: str,
) -> tuple[List[Dict[str, Any]], int, str]:
    """
    Build usage_intervals rows from DataFrame.
    
    Creates 1-minute intervals:
    - interval_start = parsed timestamp (UTC)
    - interval_end = interval_start + 60 seconds
    
    Returns:
        (rows, na_count, parse_mode_msg) - list of rows, count of dropped NaT rows, and parse mode message
    """
    rows: List[Dict[str, Any]] = []
    
    # Parse timestamps to UTC
    timestamps_utc, parse_mode_msg = parse_timestamp_local_to_utc(df[timestamp_col], timestamp_col, TZ)
    
    # Count NaT rows before dropping
    na_count = timestamps_utc.isna().sum()
    
    # Get kWh values
    kwh_values = pd.to_numeric(df[kwh_col], errors="coerce")
    # Normalize to kWh if needed
    kwh_values = kwh_values.apply(lambda v: normalize_energy_to_kwh(v, kwh_col) if pd.notna(v) else v)
    
    # Build intervals (skip NaT timestamps)
    for idx in range(len(df)):
        interval_start_ts = timestamps_utc.iloc[idx]
        kwh = kwh_values.iloc[idx]
        
        # Skip if timestamp or kWh is invalid
        if pd.isna(interval_start_ts) or pd.isna(kwh):
            continue
        
        # Convert to Python datetime if needed
        if isinstance(interval_start_ts, pd.Timestamp):
            interval_start = interval_start_ts.to_pydatetime()
        else:
            interval_start = interval_start_ts
        
        # Ensure timezone-aware
        if interval_start.tzinfo is None:
            interval_start = interval_start.replace(tzinfo=timezone.utc)
        
        # Calculate interval_end (60 seconds later)
        interval_end = interval_start + timedelta(seconds=60)
        
        # Build row
        row: Dict[str, Any] = {
            "site_id": site_id,
            "channel_type": channel_type,
            "interval_start": interval_start,
            "interval_end": interval_end,
            "kwh": float(kwh),
            "cost_aud": None,
            "quality": None,
            "meter_identifier": None,
            "source": source,
            "raw_event_id": raw_event_id,
        }
        rows.append(row)
    
    return rows, na_count, parse_mode_msg


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Load Powerpal minute CSV into Supabase usage_intervals"
    )
    parser.add_argument("--csv", required=True, type=Path,
                        help="Path to CSV file")
    parser.add_argument("--site-id", type=str, default=None,
                        help="Site ID (default: AMBER_SITE_ID env var)")
    parser.add_argument("--source", type=str, default="powerpal",
                        help="Source identifier (default: powerpal)")
    parser.add_argument("--channel-type", type=str, default="general",
                        help="Channel type (default: general)")
    
    args = parser.parse_args()
    
    # Validate CSV file exists
    if not args.csv.exists():
        print(f"ERROR: CSV file not found: {args.csv}", file=sys.stderr)
        return 1
    
    # Get site_id
    site_id = args.site_id or os.getenv("AMBER_SITE_ID")
    if not site_id:
        print("ERROR: --site-id required or AMBER_SITE_ID must be set", file=sys.stderr)
        return 1
    
    # Check database connection
    if not os.getenv("SUPABASE_DB_URL"):
        print("ERROR: SUPABASE_DB_URL not found in .env.local", file=sys.stderr)
        return 1
    
    # Read CSV
    print(f"Reading CSV: {args.csv}")
    try:
        df = pd.read_csv(args.csv)
        df.columns = [c.strip() for c in df.columns]  # Strip whitespace from column names
        print(f"  Loaded {len(df)} rows")
        print(f"  Columns: {list(df.columns)}")
    except Exception as e:
        print(f"ERROR: Failed to read CSV: {e}", file=sys.stderr)
        return 1
    
    if len(df) == 0:
        print("ERROR: CSV file is empty", file=sys.stderr)
        return 1
    
    # Detect columns
    timestamp_col = detect_timestamp_column(df)
    if timestamp_col is None:
        print(f"ERROR: Could not detect timestamp column. Columns: {list(df.columns)}", file=sys.stderr)
        return 1
    
    kwh_col = detect_kwh_column(df)
    if kwh_col is None:
        print(f"ERROR: Could not detect kWh column. Columns: {list(df.columns)}", file=sys.stderr)
        return 1
    
    print(f"  Using timestamp column: {timestamp_col}")
    print(f"  Using kWh column: {kwh_col}")
    
    # Connect to database
    try:
        conn = supabase_db.get_conn()
    except Exception as e:
        print(f"ERROR: Failed to connect to database: {e}", file=sys.stderr)
        return 1
    
    try:
        # Create ingest event
        payload_dict = {
            "file": str(args.csv),
            "row_count": len(df),
            "site_id": site_id,
            "source": args.source,
            "channel_type": args.channel_type,
        }
        
        # Determine time window from data (optional, will be computed from intervals)
        window_start = None
        window_end = None
        # We'll compute this after parsing timestamps, but it's optional
        
        raw_event_id = supabase_db.insert_ingest_event(
            conn, args.source, "usage", payload_dict,
            window_start=window_start, window_end=window_end
        )
        print(f"Created ingest event: {raw_event_id}")
        
        # Build usage intervals
        print("Building usage intervals...")
        rows, na_count, parse_mode_msg = build_usage_intervals(
            df, timestamp_col, kwh_col,
            site_id, args.channel_type, args.source, raw_event_id
        )
        
        # Log parse mode and NaT count
        print(f"  {parse_mode_msg}")
        if na_count > 0:
            print(f"  Warning: Dropped {na_count} rows with invalid timestamps (NaT)")
        print(f"  Built {len(rows)} intervals")
        
        if len(rows) == 0:
            print("ERROR: No valid intervals found", file=sys.stderr)
            return 1
        
        # Upsert to database
        print("Upserting to database...")
        count = supabase_db.upsert_usage_intervals(conn, rows)
        print(f"✓ Upserted {count} usage intervals")
        
    except Exception as e:
        print(f"ERROR: Failed to process data: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        conn.rollback()
        return 1
    finally:
        conn.close()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

