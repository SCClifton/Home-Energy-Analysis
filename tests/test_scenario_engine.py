"""Unit tests for scenario simulation battery/dispatch/cost/time windows."""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

# Add repo root to sys.path for imports when running tests directly.
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from analysis.src.scenario.config import BatteryConfig, DispatchConfig, PVConfig, ScenarioConfig
from analysis.src.scenario.engine import run_simulation, summarise_results


def _build_interval_df(start: datetime, count: int, usage_kwh: float, price_cents: float) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, datetime]:
    rows_usage = []
    rows_price = []
    rows_weather = []
    ts = start
    for _ in range(count):
        end = ts + timedelta(minutes=5)
        rows_usage.append({"interval_start": ts, "interval_end": end, "usage_kwh": usage_kwh})
        rows_price.append({"interval_start": ts, "interval_end": end, "price_cents_per_kwh": price_cents})
        rows_weather.append({"interval_start": ts, "interval_end": end, "ghi_wm2": 0.0, "temperature_c": 20.0, "cloud_cover_pct": 0.0})
        ts = end
    return pd.DataFrame(rows_usage), pd.DataFrame(rows_price), pd.DataFrame(rows_weather), ts


def test_battery_soc_stays_within_constraints():
    start = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    usage_df, price_df, weather_df, end = _build_interval_df(start, 96, usage_kwh=0.35, price_cents=35.0)

    config = ScenarioConfig(
        pv=PVConfig(capacity_kw=10.0),
        battery=BatteryConfig(
            capacity_kwh=10.0,
            min_soc_kwh=1.0,
            initial_soc_kwh=5.0,
            max_charge_kw=5.0,
            max_discharge_kw=5.0,
            max_export_kw=5.0,
            round_trip_efficiency=0.9,
            allow_grid_charge=True,
        ),
        dispatch=DispatchConfig(),
    )

    results = run_simulation(
        usage_df=usage_df,
        price_df=price_df,
        weather_df=weather_df,
        start_utc=start,
        end_utc=end,
        as_of_utc=end - timedelta(minutes=5),
        controller_mode="optimizer",
        config=config,
    )

    assert not results.empty
    assert (results["battery_soc_kwh"] >= config.battery.min_soc_kwh - 1e-9).all()
    assert (results["battery_soc_kwh"] <= config.battery.capacity_kwh + 1e-9).all()


def test_dispatch_respects_power_limits_each_interval():
    start = datetime(2026, 1, 2, 0, 0, tzinfo=timezone.utc)
    usage_df, price_df, weather_df, end = _build_interval_df(start, 48, usage_kwh=0.45, price_cents=25.0)

    config = ScenarioConfig(
        battery=BatteryConfig(max_charge_kw=4.0, max_discharge_kw=4.0, max_export_kw=4.0),
    )

    results = run_simulation(
        usage_df=usage_df,
        price_df=price_df,
        weather_df=weather_df,
        start_utc=start,
        end_utc=end,
        as_of_utc=end - timedelta(minutes=5),
        controller_mode="rule",
        config=config,
    )

    max_interval_kwh = 4.0 * (5.0 / 60.0)
    assert (results["battery_charge_kwh"] <= max_interval_kwh + 1e-9).all()
    assert (results["battery_discharge_kwh"] <= max_interval_kwh + 1e-9).all()
    assert (results["export_kwh"] <= max_interval_kwh + 1e-9).all()
    assert (results["scenario_import_kwh"] >= -1e-9).all()


def test_cost_calculation_matches_energy_times_price_when_no_dispatch():
    start = datetime(2026, 1, 3, 0, 0, tzinfo=timezone.utc)
    usage_df, price_df, weather_df, end = _build_interval_df(start, 1, usage_kwh=1.2, price_cents=20.0)

    config = ScenarioConfig(
        pv=PVConfig(capacity_kw=0.0),
        battery=BatteryConfig(
            min_soc_kwh=1.0,
            initial_soc_kwh=1.0,
            allow_grid_charge=False,
            degradation_cost_aud_per_kwh=0.0,
        ),
        dispatch=DispatchConfig(
            rule_discharge_price_aud_per_kwh=0.5,
            rule_charge_price_aud_per_kwh=0.01,
            export_arbitrage_price_aud_per_kwh=0.8,
        ),
    )

    results = run_simulation(
        usage_df=usage_df,
        price_df=price_df,
        weather_df=weather_df,
        start_utc=start,
        end_utc=end,
        as_of_utc=start,
        controller_mode="rule",
        config=config,
    )

    row = results.iloc[0]
    expected_cost = 1.2 * 0.20
    assert abs(row["baseline_cost_aud"] - expected_cost) < 1e-9
    assert abs(row["scenario_cost_aud"] - expected_cost) < 1e-9
    assert abs(row["savings_aud"]) < 1e-9


def test_summary_uses_sydney_today_and_month_windows():
    as_of_utc = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
    sydney = as_of_utc.astimezone(ZoneInfo("Australia/Sydney"))
    day_start_sydney = sydney.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start_sydney = sydney.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    day_start_utc = day_start_sydney.astimezone(timezone.utc)
    month_start_utc = month_start_sydney.astimezone(timezone.utc)

    rows = [
        # same Sydney day -> included in today + MTD
        {
            "interval_start": day_start_utc + timedelta(minutes=5),
            "interval_end": day_start_utc + timedelta(minutes=10),
            "savings_aud": 1.0,
            "battery_soc_kwh": 4.0,
            "pv_generation_kwh": 0.2,
            "export_kwh": 0.1,
            "price_aud_per_kwh": 0.30,
            "is_estimated_usage": False,
        },
        # previous Sydney day but same month -> included in MTD only
        {
            "interval_start": day_start_utc - timedelta(minutes=5),
            "interval_end": day_start_utc,
            "savings_aud": 2.0,
            "battery_soc_kwh": 4.2,
            "pv_generation_kwh": 0.0,
            "export_kwh": 0.0,
            "price_aud_per_kwh": 0.20,
            "is_estimated_usage": False,
        },
        # start of month -> included in MTD only
        {
            "interval_start": month_start_utc + timedelta(hours=1),
            "interval_end": month_start_utc + timedelta(hours=1, minutes=5),
            "savings_aud": 3.0,
            "battery_soc_kwh": 4.4,
            "pv_generation_kwh": 0.0,
            "export_kwh": 0.0,
            "price_aud_per_kwh": 0.20,
            "is_estimated_usage": True,
        },
    ]
    results_df = pd.DataFrame(rows)

    summary = summarise_results(results_df, as_of_utc, ScenarioConfig())

    assert abs(summary.today_savings_aud - 1.0) < 1e-9
    assert abs(summary.mtd_savings_aud - 6.0) < 1e-9
