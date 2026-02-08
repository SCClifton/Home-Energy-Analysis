#!/usr/bin/env python3
"""Run digital twin simulation in backtest or live mode."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from analysis.src.scenario.config import default_config
from analysis.src.scenario.data_sources import (
    load_sqlite_irradiance,
    load_sqlite_usage_prices,
    load_supabase_usage_prices,
    merge_with_precedence,
    newest_interval_timestamp,
)
from analysis.src.scenario.engine import run_simulation, summarise_results
from analysis.src.scenario.weather import fetch_open_meteo_hourly, hourly_to_five_minute_intervals
from home_energy_analysis.storage import sqlite_cache
from home_energy_analysis.storage.factory import get_sqlite_cache

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
LOGGER = logging.getLogger(__name__)

LOCATION_ID = "vaucluse_nsw"


def parse_iso_utc(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def floor_to_5min(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    floored = (dt.minute // 5) * 5
    return dt.replace(minute=floored, second=0, microsecond=0)


def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _rows_from_weather(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return []
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


def _rows_from_simulation(df: pd.DataFrame, scenario_id: str, controller_mode: str, as_of_utc: datetime) -> list[dict]:
    rows = []
    for row in df.itertuples(index=False):
        rows.append(
            {
                "scenario_id": scenario_id,
                "controller_mode": controller_mode,
                "interval_start": iso_z(row.interval_start.to_pydatetime()),
                "interval_end": iso_z(row.interval_end.to_pydatetime()),
                "baseline_import_kwh": float(row.baseline_import_kwh),
                "scenario_import_kwh": float(row.scenario_import_kwh),
                "battery_charge_kwh": float(row.battery_charge_kwh),
                "battery_discharge_kwh": float(row.battery_discharge_kwh),
                "battery_soc_kwh": float(row.battery_soc_kwh),
                "pv_generation_kwh": float(row.pv_generation_kwh),
                "export_kwh": float(row.export_kwh),
                "baseline_cost_aud": float(row.baseline_cost_aud),
                "scenario_cost_aud": float(row.scenario_cost_aud),
                "savings_aud": float(row.savings_aud),
                "forecast": row.interval_start.to_pydatetime().astimezone(timezone.utc) > as_of_utc,
            }
        )
    return rows


def _load_weather(cache_path: str, start_utc: datetime, end_utc: datetime, refresh_weather: bool) -> pd.DataFrame:
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
    except Exception as exc:  # pragma: no cover - exercised in live environment
        LOGGER.warning("Weather fetch failed; using cached irradiance only: %s", exc)
        return cached


def _load_inputs(mode: str, cache_path: str, site_id: str, start_utc: datetime, end_utc: datetime) -> tuple[pd.DataFrame, pd.DataFrame]:
    sqlite_usage, sqlite_prices = load_sqlite_usage_prices(cache_path, site_id, start_utc, end_utc)

    supabase_usage = pd.DataFrame()
    supabase_prices = pd.DataFrame()

    if os.getenv("SUPABASE_DB_URL"):
        try:
            supabase_usage, supabase_prices = load_supabase_usage_prices(site_id, start_utc, end_utc)
        except Exception as exc:  # pragma: no cover - depends on remote runtime
            LOGGER.warning("Supabase read unavailable, continuing with SQLite cache data: %s", exc)
    else:
        # TODO(data-source): Backtest mode should require SUPABASE_DB_URL when strict historical parity is mandatory.
        LOGGER.info("SUPABASE_DB_URL not set; proceeding with SQLite-only data")

    if mode == "backtest":
        usage_df = merge_with_precedence(supabase_usage, sqlite_usage)
        price_df = merge_with_precedence(supabase_prices, sqlite_prices)
    else:
        usage_df = merge_with_precedence(sqlite_usage, supabase_usage)
        price_df = merge_with_precedence(sqlite_prices, supabase_prices)

    return usage_df, price_df


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run digital twin scenario simulation")
    parser.add_argument("--mode", choices=["backtest", "live"], default="live")
    parser.add_argument("--controller", choices=["rule", "optimizer"], default="optimizer")
    parser.add_argument("--scenario-id", default="house_twin_10kw_10kwh")
    parser.add_argument("--site-id", default=os.getenv("AMBER_SITE_ID", "test_site"))
    parser.add_argument("--start", help="Backtest start UTC ISO timestamp")
    parser.add_argument("--end", help="Backtest end UTC ISO timestamp")
    parser.add_argument("--history-hours", type=int, default=48, help="Live mode lookback window")
    parser.add_argument("--forecast-hours", type=int, default=24, help="Live mode forecast horizon")
    parser.add_argument("--refresh-weather", action="store_true", default=False)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    load_dotenv(PROJECT_ROOT / ".env.local", override=False)
    cache_path = get_sqlite_cache()

    now_utc = floor_to_5min(datetime.now(timezone.utc))
    if args.mode == "backtest":
        if not args.start or not args.end:
            raise SystemExit("--start and --end are required for backtest mode")
        start_utc = parse_iso_utc(args.start)
        end_utc = parse_iso_utc(args.end)
    else:
        end_utc = now_utc + timedelta(hours=max(args.forecast_hours, 1))
        start_utc = now_utc - timedelta(hours=max(args.history_hours, 1))

    if end_utc <= start_utc:
        raise SystemExit("Invalid window: end must be greater than start")

    config = default_config()
    if args.scenario_id != config.scenario_id:
        config = config.__class__(
            scenario_id=args.scenario_id,
            timezone_display=config.timezone_display,
            pv=config.pv,
            battery=config.battery,
            dispatch=config.dispatch,
        )

    LOGGER.info(
        "Running simulation mode=%s controller=%s window=%s -> %s",
        args.mode,
        args.controller,
        iso_z(start_utc),
        iso_z(end_utc),
    )

    usage_df, price_df = _load_inputs(args.mode, cache_path, args.site_id, start_utc, end_utc)
    weather_df = _load_weather(cache_path, start_utc, end_utc, refresh_weather=args.refresh_weather)

    newest_usage = newest_interval_timestamp(usage_df)
    if newest_usage is None:
        as_of_utc = now_utc
    else:
        as_of_utc = floor_to_5min(min(newest_usage, now_utc))

    results = run_simulation(
        usage_df=usage_df,
        price_df=price_df,
        weather_df=weather_df,
        start_utc=start_utc,
        end_utc=end_utc,
        as_of_utc=as_of_utc,
        controller_mode=args.controller,
        config=config,
    )

    summary = summarise_results(results, as_of_utc, config)

    if not args.dry_run:
        interval_rows = _rows_from_simulation(results, config.scenario_id, args.controller, as_of_utc)
        sqlite_cache.upsert_simulation_intervals(cache_path, interval_rows)

        sqlite_cache.upsert_simulation_run(
            cache_path,
            {
                "scenario_id": config.scenario_id,
                "controller_mode": args.controller,
                "run_mode": args.mode,
                "as_of": summary.as_of,
                "window_start": iso_z(start_utc),
                "window_end": iso_z(end_utc),
                "today_savings_aud": summary.today_savings_aud,
                "mtd_savings_aud": summary.mtd_savings_aud,
                "next_24h_projected_savings_aud": summary.next_24h_projected_savings_aud,
                "current_battery_soc_kwh": summary.current_battery_soc_kwh,
                "today_solar_generation_kwh": summary.today_solar_generation_kwh,
                "today_export_revenue_aud": summary.today_export_revenue_aud,
                "stale": summary.stale,
                "stale_reason": summary.stale_reason,
                "assumptions_json": config.to_dict(),
            },
        )

    payload = summary.to_dict()
    payload.update(
        {
            "scenario_id": config.scenario_id,
            "controller_mode": args.controller,
            "mode": args.mode,
            "window_start": iso_z(start_utc),
            "window_end": iso_z(end_utc),
            "intervals_simulated": int(len(results)),
            "site_id": args.site_id,
            "sqlite_path": cache_path,
        }
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
