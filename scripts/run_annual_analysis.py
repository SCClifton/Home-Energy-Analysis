#!/usr/bin/env python3
"""Generate cache-backed annual solar, battery, and efficiency analysis."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import timedelta
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from analysis.src.scenario.annual import ANALYSIS_ID, TZ, data_quality_report, local_year_window, run_annual_analysis
from analysis.src.scenario.data_sources import (
    load_sqlite_irradiance,
    load_sqlite_usage_prices,
    load_supabase_usage_prices,
    merge_with_precedence,
)
from analysis.src.scenario.weather import fetch_open_meteo_hourly, hourly_to_five_minute_intervals
from home_energy_analysis.ingestion import AmberAPIError, AmberClient
from home_energy_analysis.storage import sqlite_cache
from home_energy_analysis.storage.factory import get_sqlite_cache
from scripts import load_powerpal_minute_to_supabase as powerpal_loader

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


def _load_powerpal_manifest_usage_prices(
    manifest_path: Path,
    site_id: str,
    channel_type: str,
    start_utc,
    end_utc,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load Powerpal minute CSV manifest into 5-minute usage and tariff intervals."""
    if not manifest_path.exists():
        raise FileNotFoundError(f"Powerpal manifest not found: {manifest_path}")

    frames: list[pd.DataFrame] = []
    for csv_path in powerpal_loader.manifest_csv_paths(manifest_path):
        if not csv_path.exists():
            LOGGER.warning("Skipping missing Powerpal CSV from manifest: %s", csv_path)
            continue
        df = powerpal_loader.read_powerpal_csv(csv_path)
        if df.empty:
            continue
        timestamp_col = powerpal_loader.detect_timestamp_column(df)
        kwh_col = powerpal_loader.detect_kwh_column(df)
        if not timestamp_col or not kwh_col:
            LOGGER.warning("Skipping Powerpal CSV with unsupported columns: %s", csv_path)
            continue

        timestamps_utc, _parse_mode = powerpal_loader.parse_timestamp_local_to_utc(df[timestamp_col], timestamp_col, powerpal_loader.TZ)
        energy = pd.to_numeric(df[kwh_col], errors="coerce")
        energy = energy.apply(lambda value: powerpal_loader.normalize_energy_to_kwh(value, kwh_col) if pd.notna(value) else value)
        cost = pd.to_numeric(df["cost_dollars"], errors="coerce") if "cost_dollars" in df.columns else None
        frame = pd.DataFrame(
            {
                "interval_start": timestamps_utc,
                "usage_kwh": energy,
                "cost_aud": cost,
            }
        )
        frames.append(frame)

    empty_usage = pd.DataFrame(columns=["interval_start", "interval_end", "usage_kwh", "cost_aud", "usage_source"])
    empty_prices = pd.DataFrame(columns=["interval_start", "interval_end", "price_cents_per_kwh", "descriptor", "renewables", "price_source"])
    if not frames:
        return empty_usage, empty_prices

    usage = pd.concat(frames, ignore_index=True).dropna(subset=["interval_start", "usage_kwh"])
    usage["interval_start"] = pd.to_datetime(usage["interval_start"], utc=True)
    usage = usage[(usage["interval_start"] >= pd.Timestamp(start_utc)) & (usage["interval_start"] < pd.Timestamp(end_utc))]
    if usage.empty:
        return empty_usage, empty_prices

    usage["interval_start"] = usage["interval_start"].dt.floor("5min")
    grouped = usage.groupby("interval_start", as_index=False).agg(
        usage_kwh=("usage_kwh", "sum"),
        cost_aud=("cost_aud", "sum"),
    )
    grouped["interval_end"] = grouped["interval_start"] + pd.Timedelta(minutes=5)
    grouped["usage_source"] = "powerpal"
    grouped["derived_price_cents_per_kwh"] = (grouped["cost_aud"] / grouped["usage_kwh"].where(grouped["usage_kwh"] > 0)) * 100.0
    price_df = grouped.dropna(subset=["derived_price_cents_per_kwh"])[
        ["interval_start", "interval_end", "derived_price_cents_per_kwh"]
    ].rename(columns={"derived_price_cents_per_kwh": "price_cents_per_kwh"})
    price_df["descriptor"] = "powerpal_cost"
    price_df["renewables"] = None
    price_df["price_source"] = "powerpal_cost"
    return grouped[["interval_start", "interval_end", "usage_kwh", "cost_aud", "usage_source"]], price_df


def _refresh_amber_prices_to_sqlite(cache_path: str, site_id: str, start_utc, end_utc) -> int:
    """Fetch historical Amber prices and cache them in SQLite for annual analysis."""
    token = os.getenv("AMBER_TOKEN")
    if not token:
        raise RuntimeError("AMBER_TOKEN is required for --refresh-amber-prices")

    start_date = start_utc.astimezone(TZ).date()
    end_date = (end_utc - timedelta(seconds=1)).astimezone(TZ).date()
    client = AmberClient(token=token)
    total = 0

    for chunk_start, chunk_end in client._chunk_date_ranges(start_date, end_date):
        attempts = 0
        while True:
            attempts += 1
            try:
                prices = client.get_prices_range(site_id, chunk_start, chunk_end)
                break
            except AmberAPIError as exc:
                retry_after = None
                if exc.response_headers:
                    retry_after = exc.response_headers.get("Retry-After") or exc.response_headers.get("retry-after")
                if exc.status_code == 429 and attempts <= 5:
                    delay = float(retry_after) if retry_after and str(retry_after).isdigit() else min(60.0, 5.0 * attempts)
                    LOGGER.warning("Amber price rate limited for %s to %s; sleeping %.1fs", chunk_start, chunk_end, delay)
                    time.sleep(delay)
                    continue
                raise

        rows = []
        for price in prices:
            if price.get("channelType") and price.get("channelType") != "general":
                continue
            interval_start = price.get("startTime") or price.get("nemTime")
            interval_end = price.get("endTime")
            if not interval_start or not interval_end or price.get("perKwh") is None:
                continue
            rows.append(
                {
                    "site_id": site_id,
                    "interval_start": pd.Timestamp(interval_start).tz_convert("UTC").isoformat().replace("+00:00", "Z"),
                    "interval_end": pd.Timestamp(interval_end).tz_convert("UTC").isoformat().replace("+00:00", "Z"),
                    "channel_type": "general",
                    "per_kwh": float(price.get("perKwh")),
                    "renewables": price.get("renewables"),
                    "descriptor": price.get("descriptor"),
                }
            )

        if rows:
            sqlite_cache.upsert_prices(cache_path, rows)
            total += len(rows)
        time.sleep(1.5)

    return total


def load_inputs(cache_path: str, site_id: str, start_utc, end_utc, powerpal_manifest: Path | None = None):
    sqlite_usage, sqlite_prices = load_sqlite_usage_prices(cache_path, site_id, start_utc, end_utc)
    manifest_usage = pd.DataFrame()
    manifest_prices = pd.DataFrame()
    if powerpal_manifest:
        manifest_usage, manifest_prices = _load_powerpal_manifest_usage_prices(powerpal_manifest, site_id, "general", start_utc, end_utc)
        LOGGER.info(
            "Loaded %s Powerpal 5-minute usage intervals and %s derived cost intervals from %s",
            len(manifest_usage),
            len(manifest_prices),
            powerpal_manifest,
        )

    supabase_usage = pd.DataFrame()
    supabase_prices = pd.DataFrame()
    if os.getenv("SUPABASE_DB_URL"):
        try:
            supabase_usage, supabase_prices = load_supabase_usage_prices(site_id, start_utc, end_utc)
        except Exception as exc:
            LOGGER.warning("Supabase read unavailable; using SQLite-only inputs: %s", exc)
    else:
        LOGGER.info("SUPABASE_DB_URL not set; using SQLite-only inputs")

    usage_df = merge_with_precedence(manifest_usage, merge_with_precedence(supabase_usage, sqlite_usage))
    price_df = merge_with_precedence(merge_with_precedence(supabase_prices, sqlite_prices), manifest_prices)
    if not price_df.empty:
        price_df = price_df.copy()
        price_df["interval_start"] = pd.to_datetime(price_df["interval_start"], utc=True).dt.floor("5min")
        price_df["interval_end"] = price_df["interval_start"] + pd.Timedelta(minutes=5)
        price_df = price_df.sort_values("interval_start").drop_duplicates(subset=["interval_start"], keep="last")
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
    parser.add_argument("--powerpal-manifest", type=Path, default=None, help="Load real usage from a Powerpal CSV manifest")
    parser.add_argument("--refresh-amber-prices", action="store_true", help="Fetch historical Amber prices into SQLite before analysis")
    parser.add_argument("--refresh-weather", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Run analysis but do not write SQLite cache")
    parser.add_argument("--preflight-only", action="store_true", help="Only print data coverage checks")
    parser.add_argument("--out-json", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    load_dotenv(PROJECT_ROOT / ".env.local", override=False)
    load_dotenv(PROJECT_ROOT / "config" / ".env", override=False)

    args = parse_args()
    cache_path = get_sqlite_cache()
    start_utc, end_utc = local_year_window(args.year)

    if args.refresh_amber_prices:
        price_count = _refresh_amber_prices_to_sqlite(cache_path, args.site_id, start_utc, end_utc)
        LOGGER.info("Cached %s Amber price intervals in SQLite", price_count)

    usage_df, price_df = load_inputs(cache_path, args.site_id, start_utc, end_utc, args.powerpal_manifest)
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
