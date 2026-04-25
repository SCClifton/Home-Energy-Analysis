"""Tests for annual solar, battery, and efficiency analysis."""

from datetime import timedelta

import pandas as pd

from analysis.src.scenario.annual import (
    FinancialConfig,
    _cashflow,
    installed_cost_after_rebates,
    load_shift_analysis,
    local_year_window,
    run_annual_analysis,
)


def _fixture_inputs(year: int):
    start, _ = local_year_window(year)
    rows_usage = []
    rows_price = []
    rows_weather = []
    ts = start
    for idx in range(288):
        end = ts + timedelta(minutes=5)
        hour = ts.hour
        usage = 0.05
        if 7 <= hour < 9:
            usage = 0.18
        if 18 <= hour < 21:
            usage = 0.26
        price = 12.0 if 10 <= hour < 15 else 35.0
        ghi = 750.0 if 10 <= hour < 15 else 0.0
        rows_usage.append({"interval_start": ts, "interval_end": end, "usage_kwh": usage, "usage_source": "powerpal"})
        rows_price.append({"interval_start": ts, "interval_end": end, "price_cents_per_kwh": price})
        rows_weather.append({"interval_start": ts, "interval_end": end, "ghi_wm2": ghi, "temperature_c": 24.0, "cloud_cover_pct": 10.0})
        ts = end
    return pd.DataFrame(rows_usage), pd.DataFrame(rows_price), pd.DataFrame(rows_weather)


def test_installed_cost_uses_workbook_seed_values():
    assert installed_cost_after_rebates(8.0, 10.0) == 17755
    assert installed_cost_after_rebates(10.0, 20.0) == 26376
    assert installed_cost_after_rebates(8.0, 0.0) > 0


def test_cashflow_payback_and_irr_fixture():
    cashflow, irr, payback, net_benefit = _cashflow(2000.0, 10000.0, FinancialConfig(annual_opex_aud=0.0))
    assert len(cashflow) == 15
    assert payback is not None
    assert 4.0 < payback < 6.5
    assert irr is not None
    assert irr > 0
    assert net_benefit > 0


def test_annual_analysis_runs_requested_sweep_and_outputs_recommendations():
    usage_df, price_df, weather_df = _fixture_inputs(2025)
    payload = run_annual_analysis(
        usage_df,
        price_df,
        weather_df,
        2025,
        solar_sizes_kw=(6.6,),
        battery_sizes_kwh=(0.0,),
    )

    assert payload["year"] == 2025
    assert len(payload["scenarios"]) == 2
    assert payload["recommendations"]["lowest_cost"] is not None
    solar_rows = [row for row in payload["scenarios"] if row["solar_kw"] == 6.6]
    assert max(row["annual_solar_generation_kwh"] for row in solar_rows) > 0
    assert payload["data_quality"]["checks"]["usage"]["intervals"] == 288


def test_load_shift_analysis_is_deterministic_from_interval_patterns():
    usage_df, price_df, weather_df = _fixture_inputs(2025)
    payload = load_shift_analysis(usage_df, price_df, weather_df)

    assert payload["status"] == "ok"
    assert payload["metrics"]["shiftable_kwh_estimate"] > 0
    assert payload["opportunities"]
    assert payload["worst_days"]
