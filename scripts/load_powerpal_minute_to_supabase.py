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
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Sequence

import pandas as pd
from dotenv import load_dotenv
from zoneinfo import ZoneInfo

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

# Load local fallback environment variables for development.
# On Pi, services should provide env directly.
load_dotenv(project_root / ".env.local", override=False)

from home_energy_analysis.storage import supabase_db

TZ = ZoneInfo("Australia/Sydney")


@dataclass
class FileLoadSummary:
    """Summary of a parsed Powerpal CSV file."""

    path: Path
    input_rows: int
    valid_intervals: int
    dropped_invalid_rows: int
    invalid_timestamp_rows: int
    duplicate_intervals: int
    gap_count: int
    missing_minutes: int
    first_interval_start: Optional[datetime]
    last_interval_start: Optional[datetime]
    last_interval_end: Optional[datetime]
    parse_mode_msg: str
    is_empty: bool = False
    upserted_count: Optional[int] = None


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


def summarize_intervals(
    csv_path: Path,
    df_row_count: int,
    rows: List[Dict[str, Any]],
    invalid_timestamp_rows: int,
    parse_mode_msg: str,
    is_empty: bool = False,
) -> FileLoadSummary:
    """Build per-file interval coverage diagnostics."""
    starts = [row["interval_start"] for row in rows]
    unique_starts = sorted(set(starts))
    duplicate_intervals = len(starts) - len(unique_starts)
    dropped_invalid_rows = df_row_count - len(rows)

    gap_count = 0
    missing_minutes = 0
    if len(unique_starts) > 1:
        previous = unique_starts[0]
        for current in unique_starts[1:]:
            gap_minutes = int((current - previous).total_seconds() // 60)
            if gap_minutes > 1:
                gap_count += 1
                missing_minutes += gap_minutes - 1
            previous = current

    first_interval_start = unique_starts[0] if unique_starts else None
    last_interval_start = unique_starts[-1] if unique_starts else None
    last_interval_end = None
    if rows:
        last_interval_end = max(row["interval_end"] for row in rows)

    return FileLoadSummary(
        path=csv_path,
        input_rows=df_row_count,
        valid_intervals=len(rows),
        dropped_invalid_rows=dropped_invalid_rows,
        invalid_timestamp_rows=invalid_timestamp_rows,
        duplicate_intervals=duplicate_intervals,
        gap_count=gap_count,
        missing_minutes=missing_minutes,
        first_interval_start=first_interval_start,
        last_interval_start=last_interval_start,
        last_interval_end=last_interval_end,
        parse_mode_msg=parse_mode_msg,
        is_empty=is_empty,
    )


def print_file_summary(summary: FileLoadSummary) -> None:
    """Print a concise per-file load/dry-run summary."""
    print(f"Summary for {summary.path}:")
    if summary.is_empty:
        print("  Empty/header-only CSV: skipped")
        return
    print(f"  Input rows: {summary.input_rows}")
    print(f"  Valid intervals: {summary.valid_intervals}")
    print(f"  Dropped invalid rows: {summary.dropped_invalid_rows}")
    print(f"  Invalid timestamp rows: {summary.invalid_timestamp_rows}")
    print(f"  Duplicate intervals: {summary.duplicate_intervals}")
    print(f"  Gap count: {summary.gap_count}")
    print(f"  Missing minutes inside range: {summary.missing_minutes}")
    print(f"  First interval start: {summary.first_interval_start}")
    print(f"  Last interval start: {summary.last_interval_start}")
    print(f"  Last interval end: {summary.last_interval_end}")
    if summary.upserted_count is not None:
        print(f"  Upserted intervals: {summary.upserted_count}")


def summarize_aggregate(summaries: Sequence[FileLoadSummary], all_rows: List[Dict[str, Any]]) -> FileLoadSummary:
    """Build aggregate coverage diagnostics across all processed files."""
    input_rows = sum(summary.input_rows for summary in summaries)
    invalid_timestamp_rows = sum(summary.invalid_timestamp_rows for summary in summaries)
    summary = summarize_intervals(
        Path("<aggregate>"),
        input_rows,
        all_rows,
        invalid_timestamp_rows,
        "Aggregate across processed files",
        is_empty=not bool(all_rows),
    )
    return summary


def read_powerpal_csv(csv_path: Path) -> pd.DataFrame:
    """Read a Powerpal CSV file and strip column whitespace."""
    df = pd.read_csv(csv_path)
    df.columns = [c.strip() for c in df.columns]
    return df


def manifest_csv_paths(manifest_path: Path) -> List[Path]:
    """Return CSV file paths from a Powerpal manifest, preserving first-seen order."""
    manifest_df = pd.read_csv(manifest_path)
    if "file" not in manifest_df.columns:
        raise ValueError(f"Manifest missing required 'file' column: {manifest_path}")

    paths: List[Path] = []
    seen: set[str] = set()
    for raw_path in manifest_df["file"].dropna().astype(str):
        if raw_path in seen:
            continue
        seen.add(raw_path)
        path = Path(raw_path)
        if not path.is_absolute():
            path = project_root / path
        paths.append(path)
    return paths


def process_csv_file(
    csv_path: Path,
    site_id: str,
    channel_type: str,
    source: str,
    dry_run: bool,
    conn=None,
) -> tuple[FileLoadSummary, List[Dict[str, Any]]]:
    """Parse, summarize, and optionally load a single Powerpal CSV file."""
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    print(f"Reading CSV: {csv_path}")
    df = read_powerpal_csv(csv_path)
    print(f"  Loaded {len(df)} rows")
    print(f"  Columns: {list(df.columns)}")

    if len(df) == 0:
        summary = summarize_intervals(csv_path, 0, [], 0, "No data rows", is_empty=True)
        print_file_summary(summary)
        return summary, []

    timestamp_col = detect_timestamp_column(df)
    if timestamp_col is None:
        raise ValueError(f"Could not detect timestamp column. Columns: {list(df.columns)}")

    kwh_col = detect_kwh_column(df)
    if kwh_col is None:
        raise ValueError(f"Could not detect kWh column. Columns: {list(df.columns)}")

    print(f"  Using timestamp column: {timestamp_col}")
    print(f"  Using kWh column: {kwh_col}")

    raw_event_id = "dry-run"
    if not dry_run:
        payload_dict = {
            "file": str(csv_path),
            "row_count": len(df),
            "site_id": site_id,
            "source": source,
            "channel_type": channel_type,
        }
        raw_event_id = supabase_db.insert_ingest_event(
            conn, source, "usage", payload_dict,
            window_start=None, window_end=None
        )
        print(f"Created ingest event: {raw_event_id}")

    print("Building usage intervals...")
    rows, na_count, parse_mode_msg = build_usage_intervals(
        df, timestamp_col, kwh_col,
        site_id, channel_type, source, raw_event_id
    )

    print(f"  {parse_mode_msg}")
    summary = summarize_intervals(csv_path, len(df), rows, na_count, parse_mode_msg)

    if not rows:
        print_file_summary(summary)
        return summary, rows

    if not dry_run:
        print("Upserting to database...")
        summary.upserted_count = supabase_db.upsert_usage_intervals(conn, rows)

    print_file_summary(summary)
    return summary, rows


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Load Powerpal minute CSV into Supabase usage_intervals"
    )
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--csv", type=Path,
                             help="Path to one CSV file")
    input_group.add_argument("--manifest", type=Path,
                             help="Path to manifest CSV listing Powerpal files")
    parser.add_argument("--site-id", type=str, default=None,
                        help="Site ID (default: AMBER_SITE_ID env var)")
    parser.add_argument("--source", type=str, default="powerpal",
                        help="Source identifier (default: powerpal)")
    parser.add_argument("--channel-type", type=str, default="general",
                        help="Channel type (default: general)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse and summarize files without connecting to Supabase")
    
    args = parser.parse_args(argv)
    
    # Get site_id
    site_id = args.site_id or os.getenv("AMBER_SITE_ID") or ("dry-run-site" if args.dry_run else None)
    if not site_id:
        print("ERROR: --site-id required or AMBER_SITE_ID must be set", file=sys.stderr)
        return 1
    
    # Check database connection
    if not args.dry_run and not os.getenv("SUPABASE_DB_URL"):
        print("ERROR: SUPABASE_DB_URL environment variable is required", file=sys.stderr)
        return 1

    if args.csv:
        csv_paths = [args.csv]
    else:
        if not args.manifest.exists():
            print(f"ERROR: Manifest file not found: {args.manifest}", file=sys.stderr)
            return 1
        try:
            csv_paths = manifest_csv_paths(args.manifest)
        except Exception as e:
            print(f"ERROR: Failed to read manifest: {e}", file=sys.stderr)
            return 1

    if not csv_paths:
        print("ERROR: No CSV files found to process", file=sys.stderr)
        return 1

    conn = None
    if not args.dry_run:
        try:
            conn = supabase_db.get_conn()
        except Exception as e:
            print(f"ERROR: Failed to connect to database: {e}", file=sys.stderr)
            return 1

    summaries: List[FileLoadSummary] = []
    all_rows: List[Dict[str, Any]] = []

    try:
        for csv_path in csv_paths:
            summary, rows = process_csv_file(
                csv_path,
                site_id,
                args.channel_type,
                args.source,
                args.dry_run,
                conn=conn,
            )
            summaries.append(summary)
            all_rows.extend(rows)
            print()

        aggregate = summarize_aggregate(summaries, all_rows)
        print("=== Aggregate coverage ===")
        print_file_summary(aggregate)
        if args.dry_run:
            print("Dry run complete; no Supabase writes were attempted.")

        if args.csv and not all_rows:
            print("ERROR: No valid intervals found", file=sys.stderr)
            return 1

    except Exception as e:
        print(f"ERROR: Failed to process data: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        if conn:
            conn.rollback()
        return 1
    finally:
        if conn:
            conn.close()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
