"""
Pull historical Amber usage and price data to Parquet files.

Usage:
    python scripts/pull_historical.py --start 2025-01-01 --end 2025-01-07 --outdir data_processed
"""

import argparse
import os
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd

# Allow running from repo root
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ingestion.amber_client import AmberClient


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid date '{value}', expected YYYY-MM-DD") from exc


def _deduplicate(df: pd.DataFrame, key: str) -> pd.DataFrame:
    before = len(df)
    deduped = df.drop_duplicates(subset=[key])
    removed = before - len(deduped)
    if removed:
        print(f"Removed {removed} duplicate rows on {key}")
    return deduped


def _print_stats(name: str, df: pd.DataFrame, time_col: str) -> None:
    if df.empty:
        print(f"{name}: 0 rows")
        return
    ts = pd.to_datetime(df[time_col], utc=True, errors="coerce")
    print(
        f"{name}: {len(df)} rows | "
        f"min {ts.min()} | max {ts.max()}"
    )


def pull_data(
    start: date,
    end: date,
    outdir: Path,
    resolution: Optional[str] = None,
) -> None:
    token = os.getenv("AMBER_TOKEN")
    site_id = os.getenv("AMBER_SITE_ID")

    if not token:
        raise SystemExit("AMBER_TOKEN environment variable is not set")
    if not site_id:
        raise SystemExit("AMBER_SITE_ID environment variable is not set")

    outdir.mkdir(parents=True, exist_ok=True)

    client = AmberClient(token=token)

    # Pull usage
    usage_raw = client.get_usage_range(site_id, start, end, resolution=resolution)
    usage_df = pd.DataFrame(usage_raw)
    if not usage_df.empty:
        usage_df["interval_start"] = pd.to_datetime(
            usage_df.get("startTime"), utc=True, errors="coerce"
        )
        usage_df["interval_end"] = pd.to_datetime(
            usage_df.get("endTime"), utc=True, errors="coerce"
        )
        usage_df = _deduplicate(usage_df, "interval_start")
    usage_path = outdir / f"usage_{start.isoformat()}_{end.isoformat()}.parquet"
    usage_df.to_parquet(usage_path, index=False)
    _print_stats("Usage", usage_df, "interval_start")

    # Pull prices
    prices_raw = client.get_prices_range(site_id, start, end)
    prices_df = pd.DataFrame(prices_raw)
    if not prices_df.empty:
        prices_df["interval_start"] = pd.to_datetime(
            prices_df.get("startTime"), utc=True, errors="coerce"
        )
        prices_df["interval_end"] = pd.to_datetime(
            prices_df.get("endTime"), utc=True, errors="coerce"
        )
        prices_df = _deduplicate(prices_df, "interval_start")
    prices_path = outdir / f"prices_{start.isoformat()}_{end.isoformat()}.parquet"
    prices_df.to_parquet(prices_path, index=False)
    _print_stats("Prices", prices_df, "interval_start")

    print("Done.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Pull historical Amber usage and prices to Parquet.")
    parser.add_argument("--start", required=True, type=_parse_date, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", required=True, type=_parse_date, help="End date (YYYY-MM-DD)")
    parser.add_argument(
        "--outdir",
        default="data_processed",
        help="Output directory for Parquet files (default: data_processed)",
    )
    parser.add_argument(
        "--resolution",
        default=None,
        help="Optional resolution hint (e.g., 5 or 30). If omitted, Amber auto-selects.",
    )

    args = parser.parse_args()

    if args.start > args.end:
        raise SystemExit("--start must be on or before --end")

    pull_data(
        start=args.start,
        end=args.end,
        outdir=Path(args.outdir),
        resolution=args.resolution,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

