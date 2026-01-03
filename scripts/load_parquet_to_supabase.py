#!/usr/bin/env python3
"""
Load a parquet file (prices or usage) into Supabase Postgres.
Handles column normalization, timezone conversion, and idempotent upserts.
"""
import os
import sys
import argparse
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, List
import pandas as pd
from dotenv import load_dotenv

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))


def normalize_price_row(row: Dict[str, Any], site_id: str, source: str, 
                        is_forecast: bool, raw_event_id: str) -> Dict[str, Any]:
    """
    Normalize a price row from parquet to database format.
    
    Handles column name variations:
    - interval_start, interval_end (required)
    - per_kwh or price_cents_per_kwh (if per_kwh is dollars, multiply by 100)
    - spot_per_kwh (optional)
    - descriptor (optional)
    - spike_status (optional)
    - renewables or renewables_percent (optional)
    """
    norm_row: Dict[str, Any] = {
        "site_id": site_id,
        "interval_start": row.get("interval_start"),
        "interval_end": row.get("interval_end"),
        "is_forecast": is_forecast,
        "source": source,
        "raw_event_id": raw_event_id,
        "price_cents_per_kwh": None,
        "spot_per_kwh": None,
        "descriptor": None,
        "spike_status": None,
        "renewables_percent": None,
    }
    
    # Handle price: check for per_kwh (dollars) or price_cents_per_kwh (cents)
    if "price_cents_per_kwh" in row:
        norm_row["price_cents_per_kwh"] = row["price_cents_per_kwh"]
    elif "per_kwh" in row and row["per_kwh"] is not None:
        # Assume per_kwh is in dollars, convert to cents
        norm_row["price_cents_per_kwh"] = float(row["per_kwh"]) * 100
    elif "price" in row and row["price"] is not None:
        # Try generic "price" column
        price_val = float(row["price"])
        # Heuristic: if < 1, assume dollars; otherwise assume cents
        if price_val < 1:
            norm_row["price_cents_per_kwh"] = price_val * 100
        else:
            norm_row["price_cents_per_kwh"] = price_val
    
    # Optional fields
    if "spot_per_kwh" in row:
        norm_row["spot_per_kwh"] = row["spot_per_kwh"]
    if "descriptor" in row:
        norm_row["descriptor"] = row["descriptor"]
    if "spike_status" in row:
        norm_row["spike_status"] = row["spike_status"]
    
    # Handle renewables (may be "renewables" or "renewables_percent")
    if "renewables_percent" in row:
        norm_row["renewables_percent"] = row["renewables_percent"]
    elif "renewables" in row:
        norm_row["renewables_percent"] = row["renewables"]
    
    return norm_row


def normalize_usage_row(row: Dict[str, Any], site_id: str, source: str,
                        channel_type: str, raw_event_id: str) -> Dict[str, Any]:
    """
    Normalize a usage row from parquet to database format.
    
    Handles column name variations:
    - interval_start, interval_end (required)
    - kwh (required)
    - cost_aud (optional)
    - quality (optional)
    - meter_identifier or channel_identifier (optional)
    """
    norm_row: Dict[str, Any] = {
        "site_id": site_id,
        "channel_type": channel_type,
        "interval_start": row.get("interval_start"),
        "interval_end": row.get("interval_end"),
        "kwh": row.get("kwh"),
        "source": source,
        "raw_event_id": raw_event_id,
        "cost_aud": None,
        "quality": None,
        "meter_identifier": None,
    }
    
    # Optional fields
    if "cost_aud" in row:
        norm_row["cost_aud"] = row["cost_aud"]
    if "quality" in row:
        norm_row["quality"] = row["quality"]
    if "meter_identifier" in row:
        norm_row["meter_identifier"] = row["meter_identifier"]
    elif "channel_identifier" in row:
        norm_row["meter_identifier"] = row["channel_identifier"]
    
    return norm_row


def ensure_timezone_aware(dt) -> datetime:
    """Convert datetime to timezone-aware UTC if needed."""
    if pd.isna(dt):
        return None
    if isinstance(dt, str):
        dt = pd.to_datetime(dt)
    if isinstance(dt, pd.Timestamp):
        dt = dt.to_pydatetime()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Load parquet file (prices or usage) into Supabase"
    )
    parser.add_argument("--kind", required=True, choices=["prices", "usage"],
                        help="Data kind: 'prices' or 'usage'")
    parser.add_argument("--parquet", required=True, type=Path,
                        help="Path to parquet file")
    parser.add_argument("--site-id", required=True,
                        help="Site ID (required)")
    parser.add_argument("--source", default="amber",
                        choices=["amber", "powerpal", "powerpow"],
                        help="Data source (default: amber)")
    parser.add_argument("--channel-type", default="general",
                        help="Channel type (required if kind=usage, default: general)")
    parser.add_argument("--is-forecast", type=str, default="false",
                        choices=["true", "false"],
                        help="Whether prices are forecasts (only for kind=prices, default: false)")
    
    args = parser.parse_args()
    
    # Validate parquet file exists
    if not args.parquet.exists():
        print(f"Error: Parquet file not found: {args.parquet}")
        sys.exit(1)
    
    # Load environment
    env_path = project_root / ".env.local"
    if not env_path.exists():
        print(f"Error: .env.local not found at {env_path}")
        sys.exit(1)
    
    load_dotenv(env_path)
    from home_energy_analysis.storage import supabase_db
    
    if not os.environ.get("SUPABASE_DB_URL"):
        print("Error: SUPABASE_DB_URL not found in .env.local")
        sys.exit(1)
    
    # Parse is_forecast
    is_forecast = args.is_forecast.lower() == "true"
    
    # Read parquet file
    print(f"Reading parquet file: {args.parquet}")
    try:
        df = pd.read_parquet(args.parquet)
        print(f"  Loaded {len(df)} rows")
    except Exception as e:
        print(f"Error reading parquet file: {e}")
        sys.exit(1)
    
    if len(df) == 0:
        print("Warning: Parquet file is empty")
        sys.exit(0)
    
    # Connect to database
    try:
        conn = supabase_db.get_conn()
    except Exception as e:
        print(f"Error connecting to database: {e}")
        sys.exit(1)
    
    try:
        # Create ingest event
        # Use a simple payload dict based on file metadata
        payload_dict = {
            "file": str(args.parquet),
            "kind": args.kind,
            "source": args.source,
            "site_id": args.site_id,
            "row_count": len(df),
        }
        
        # Determine time window from data
        window_start = None
        window_end = None
        if "interval_start" in df.columns:
            window_start = ensure_timezone_aware(df["interval_start"].min())
            window_end = ensure_timezone_aware(df["interval_end"].max() if "interval_end" in df.columns else df["interval_start"].max())
        
        raw_event_id = supabase_db.insert_ingest_event(
            conn, args.source, args.kind, payload_dict,
            window_start=window_start, window_end=window_end
        )
        print(f"Created ingest event: {raw_event_id}")
        
        # Normalize and upsert rows
        if args.kind == "prices":
            rows = []
            for _, row in df.iterrows():
                norm_row = normalize_price_row(
                    row.to_dict(), args.site_id, args.source,
                    is_forecast, raw_event_id
                )
                # Ensure timezone-aware datetimes
                if norm_row.get("interval_start"):
                    norm_row["interval_start"] = ensure_timezone_aware(norm_row["interval_start"])
                if norm_row.get("interval_end"):
                    norm_row["interval_end"] = ensure_timezone_aware(norm_row["interval_end"])
                rows.append(norm_row)
            
            count = supabase_db.upsert_price_intervals(conn, rows)
            print(f"✓ Upserted {count} price intervals")
        
        else:  # usage
            rows = []
            for _, row in df.iterrows():
                norm_row = normalize_usage_row(
                    row.to_dict(), args.site_id, args.source,
                    args.channel_type, raw_event_id
                )
                # Ensure timezone-aware datetimes
                if norm_row.get("interval_start"):
                    norm_row["interval_start"] = ensure_timezone_aware(norm_row["interval_start"])
                if norm_row.get("interval_end"):
                    norm_row["interval_end"] = ensure_timezone_aware(norm_row["interval_end"])
                rows.append(norm_row)
            
            count = supabase_db.upsert_usage_intervals(conn, rows)
            print(f"✓ Upserted {count} usage intervals")
        
    except Exception as e:
        print(f"Error processing data: {e}")
        import traceback
        traceback.print_exc()
        conn.rollback()
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()

