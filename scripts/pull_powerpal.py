#!/usr/bin/env python3
"""
Pull Powerpal usage CSV exports for a date range, then resample to 5-minute kWh.

Powerpal constraints:
- Link/token is typically valid ~24 hours
- Max ~90 days per CSV export
- History available ~12 months (you mentioned this)

Usage:
  set -a; source config/.env; set +a
  python scripts/pull_powerpal.py --start 2025-06-24 --end 2025-09-22

Env vars (recommended, stored in config/.env which is gitignored):
  POWERPAL_DEVICE_ID=0005191c
  POWERPAL_TOKEN=... (the long token from the CSV URL)
  POWERPAL_SAMPLE=1  (1 = minutes, per app UI)
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Optional, Tuple, List

import pandas as pd
import requests
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Australia/Sydney")
BASE_URL = "https://readings.powerpal.net/csv/v1"


@dataclass(frozen=True)
class Range:
    start: date
    end: date  # inclusive end date for user semantics


def parse_yyyy_mm_dd(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def clamp_to_last_12_months(start: date, end: date) -> Tuple[date, date]:
    today = date.today()
    earliest = today - timedelta(days=365)  # approx 12 months
    if end < earliest:
        raise ValueError(
            f"End date {end} is older than 12 months (earliest allowed approx {earliest})."
        )
    if start < earliest:
        start = earliest
    if end > today:
        end = today
    if start > end:
        raise ValueError("Start date is after end date after clamping.")
    return start, end


def epoch_start(d: date) -> int:
    dt = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=TZ)
    return int(dt.timestamp())


def epoch_end(d: date) -> int:
    dt = datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=TZ)
    return int(dt.timestamp())


def chunk_ranges(start: date, end: date, max_days: int = 90) -> List[Range]:
    chunks: List[Range] = []
    cur = start
    while cur <= end:
        chunk_end = min(cur + timedelta(days=max_days - 1), end)
        chunks.append(Range(cur, chunk_end))
        cur = chunk_end + timedelta(days=1)
    return chunks


def build_url(device_id: str, token: str, r: Range, sample: int) -> str:
    return (
        f"{BASE_URL}/{device_id}"
        f"?token={token}"
        f"&start={epoch_start(r.start)}"
        f"&end={epoch_end(r.end)}"
        f"&sample={sample}"
    )


def download_csv(url: str, out_path: Path, timeout: int = 60) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=timeout) as resp:
        resp.raise_for_status()
        out_path.write_bytes(resp.content)


def detect_time_column(df: pd.DataFrame) -> Optional[str]:
    # Powerpal exports commonly include datetime_utc / datetime_local
    candidates = [
        "datetime_utc",
        "datetime_local",
        "timestamp",
        "time",
        "datetime",
        "dateTime",
        "ts",
        "epoch",
        "unix",
    ]
    for c in candidates:
        if c in df.columns:
            return c
    return None


def detect_power_column(df: pd.DataFrame) -> Optional[str]:
    candidates = ["watts", "power", "w", "avg_watts", "avgWatts"]
    for c in candidates:
        if c in df.columns:
            return c
    return None


def detect_energy_column(df: pd.DataFrame) -> Optional[str]:
    # Your export uses watt_hours
    candidates = [
        "watt_hours",
        "wattHours",
        "wh",
        "kwh",
        "energy_kwh",
        "energy",
        "kWh",
        "kwh_used",
    ]
    for c in candidates:
        if c in df.columns:
            return c
    return None


def parse_powerpal_csv(path: Path, sample_minutes: int) -> pd.DataFrame:
    """
    Returns a DataFrame with:
      interval_start (UTC, tz-aware)
      usage_kwh (per raw sample interval)
    Then caller will resample to 5-minute.
    """
    df = pd.read_csv(path)
    df.columns = [c.strip() for c in df.columns]

    time_col = detect_time_column(df)
    if time_col is None:
        raise ValueError(
            f"Could not find a timestamp column in {path.name}. Columns: {list(df.columns)}"
        )

    s = df[time_col]

    # If it's numeric, treat as epoch seconds
    if pd.api.types.is_numeric_dtype(s):
        ts = pd.to_datetime(s, unit="s", utc=True)
    else:
        # datetime_utc is typically ISO-like; parse as UTC
        ts = pd.to_datetime(s, utc=True, errors="coerce")
        if ts.isna().all():
            raise ValueError(
                f"Could not parse timestamps in {path.name} from column {time_col}"
            )

    df["_ts"] = ts

    energy_col = detect_energy_column(df)
    power_col = detect_power_column(df)

    if energy_col:
        vals = pd.to_numeric(df[energy_col], errors="coerce")
        # Powerpal export uses watt_hours (Wh)
        if energy_col in {"watt_hours", "wattHours", "wh"}:
            usage_kwh = vals / 1000.0
        else:
            # Assume already kWh
            usage_kwh = vals
    elif power_col:
        watts = pd.to_numeric(df[power_col], errors="coerce")
        usage_kwh = watts * (sample_minutes / 60.0) / 1000.0
    else:
        raise ValueError(
            f"Could not find energy (kWh/Wh) or power (watts) column in {path.name}. Columns: {list(df.columns)}"
        )

    out = pd.DataFrame({"interval_start": df["_ts"], "usage_kwh": usage_kwh})
    out = out.dropna(subset=["interval_start", "usage_kwh"]).sort_values("interval_start")
    return out


def resample_to_5min(df_samples: pd.DataFrame) -> pd.DataFrame:
    df = df_samples.copy()
    df = df.set_index("interval_start")
    df_5 = df.resample("5min").sum(numeric_only=True)
    df_5 = df_5.reset_index()
    df_5["interval_end"] = df_5["interval_start"] + pd.Timedelta(minutes=5)
    df_5["duration_minutes"] = 5
    return df_5[["interval_start", "interval_end", "duration_minutes", "usage_kwh"]]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download Powerpal CSV in chunks and produce 5-min parquet usage."
    )
    parser.add_argument("--start", required=True, help="YYYY-MM-DD (clamped to last 12 months)")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD (inclusive, clamped to today)")
    parser.add_argument("--out-raw", default="data_raw/powerpal", help="Folder for raw CSV downloads (gitignored)")
    parser.add_argument("--out-processed", default="data_processed/powerpal", help="Folder for parquet output (gitignored)")
    parser.add_argument("--max-days-per-export", type=int, default=90, help="Powerpal max days per CSV export")
    parser.add_argument("--sample-minutes", type=int, default=None, help="Sample interval minutes (default from env POWERPAL_SAMPLE)")
    args = parser.parse_args()

    device_id = os.getenv("POWERPAL_DEVICE_ID")
    token = os.getenv("POWERPAL_TOKEN")
    if not device_id or not token:
        raise SystemExit("ERROR: Set POWERPAL_DEVICE_ID and POWERPAL_TOKEN in config/.env (do not commit them).")

    sample_env = os.getenv("POWERPAL_SAMPLE", "1")
    sample_minutes = args.sample_minutes if args.sample_minutes is not None else int(sample_env)

    start = parse_yyyy_mm_dd(args.start)
    end = parse_yyyy_mm_dd(args.end)
    start, end = clamp_to_last_12_months(start, end)

    raw_dir = Path(args.out_raw)
    processed_dir = Path(args.out_processed)
    processed_dir.mkdir(parents=True, exist_ok=True)

    ranges = chunk_ranges(start, end, max_days=args.max_days_per_export)

    all_samples: List[pd.DataFrame] = []
    for r in ranges:
        url = build_url(device_id, token, r, sample=sample_minutes)
        out_csv = raw_dir / f"powerpal_{device_id}_{r.start.isoformat()}_{r.end.isoformat()}_sample{sample_minutes}.csv"

        print(f"Downloading {r.start} to {r.end} -> {out_csv}")
        download_csv(url, out_csv)

        df_samples = parse_powerpal_csv(out_csv, sample_minutes=sample_minutes)
        all_samples.append(df_samples)

    df_all = pd.concat(all_samples, ignore_index=True).sort_values("interval_start")
    df_5 = resample_to_5min(df_all)

    out_parquet = processed_dir / f"powerpal_usage_5min_{start.isoformat()}_{end.isoformat()}.parquet"
    df_5.to_parquet(out_parquet, index=False)

    print("\n=== Done ===")
    print(f"Device: {device_id}")
    print(f"Range: {start} to {end} (clamped to last 12 months if needed)")
    print(f"Raw CSVs: {raw_dir}")
    print(f"Output parquet: {out_parquet}")
    print(f"Rows (5-min): {len(df_5)} | min {df_5['interval_start'].min()} | max {df_5['interval_start'].max()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())