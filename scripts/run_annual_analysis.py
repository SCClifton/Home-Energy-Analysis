#!/usr/bin/env python3
"""Generate cache-backed annual solar, battery, and efficiency analysis."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from analysis.src.scenario.annual import ANALYSIS_ID, data_quality_report, local_year_window, run_annual_analysis
from analysis.src.scenario.data_sources import (
    load_sqlite_irradiance,
    load_sqlite_usage_prices,
    load_supabase_usage_prices,
    merge_with_precedence,
)
from analysis.src.scenario.weather import fetch_open_meteo_hourly, hourly_to_five_minute_intervals
from home_energy_analysis.storage import sqlite_cache
from home_energy_analysis.storage.factory import get_sqlite_cache

LOGGER = logging.getLogger(__name__)
LOCATION_ID = "vaucluse_nsw"


def iso_z(dt):
    return dt.isoformat().replace("+00:00", "Z")


def _rows_from_weather(df: pd.DataFrame) -> list[dict]:
    rows = []
    for row in df.itertuples(index=False):
        rows.append(
            {
                "location_id": LOCATION_ID,
                "interval_start": iso_z(row.interval_start.to_pydatetime()),
                "interval_end": iso_z(row.interval_end.to_pydatetime()),
                "ghi_wm2": float(row.ghi_wm2),
                "temperature_c": float(row.temperature_c),
                "cloud_cover_pct": float(row.cloud_cover_pct),
                "source": getattr(row, "source", "open-meteo"),
            }
        )
    return rows


def load_inputs(cache_path: str, site_id: str, start_utc, end_utc):
    sqlite_usage, sqlite_prices = load_sqlite_usage_prices(cache_path, site_id, start_utc, end_utc)

    supabase_usage = pd.DataFrame()
    supabase_prices = pd.DataFrame()
    if os.getenv("SUPABASE_DB_URL"):
        try:
            supabase_usage, supabase_prices = load_supabase_usage_prices(site_id, start_utc, end_utc)
        except Exception as exc:
            LOGGER.warning("Supabase read unavailable; using SQLite-only inputs: %s", exc)
    else:
        LOGGER.info("SUPABASE_DB_URL not set; using SQLite-only inputs")

    usage_df = merge_with_precedence(supabase_usage, sqlite_usage)
    price_df = merge_with_precedence(supabase_prices, sqlite_prices)
    return usage_df, price_df


def load_weather(cache_path: str, start_utc, end_utc, refresh_weather: bool):
    cached = load_sqlite_irradiance(cache_path, LOCATION_ID, start_utc, end_utc)
    if not refresh_weather:
        return cached

    try:
        hourly = fetch_open_meteo_hourly(start_utc, end_utc)
        weather = hourly_to_five_minute_intervals(hourly, start_utc, end_utc)
        rows = _rows_from_weather(weather)
        if rows:
            sqlite_cache.upsert_irradiance(cache_path, rows)
        return merge_with_precedence(weather, cached)
    except Exception as exc:
        LOGGER.warning("Weather refresh failed; using cached irradiance only: %s", exc)
        return cached


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate annual solar/battery decision analysis")
    parser.add_argument("--year", type=int, default=int(os.getenv("ANALYSIS_YEAR", "2025")))
    parser.add_argument("--site-id", default=os.getenv("AMBER_SITE_ID", "test_site"))
    parser.add_argument("--refresh-weather", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Run analysis but do not write SQLite cache")
    parser.add_argument("--preflight-only", action="store_true", help="Only print data coverage checks")
    parser.add_argument("--out-json", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    load_dotenv(PROJECT_ROOT / ".env.local", override=False)

    args = parse_args()
    cache_path = get_sqlite_cache()
    start_utc, end_utc = local_year_window(args.year)

    usage_df, price_df = load_inputs(cache_path, args.site_id, start_utc, end_utc)
    weather_df = load_weather(cache_path, start_utc, end_utc, refresh_weather=args.refresh_weather)

    if args.preflight_only:
        payload = data_quality_report(usage_df, price_df, weather_df, start_utc, end_utc)
    else:
        payload = run_annual_analysis(usage_df, price_df, weather_df, args.year)

    print(json.dumps(payload if args.preflight_only else payload["data_quality"], indent=2, sort_keys=True))

    if args.out_json:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    if not args.preflight_only and not args.dry_run:
        sqlite_cache.upsert_analysis_run(cache_path, payload)
        LOGGER.info("Wrote analysis payload analysis_id=%s year=%s to %s", ANALYSIS_ID, args.year, cache_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
