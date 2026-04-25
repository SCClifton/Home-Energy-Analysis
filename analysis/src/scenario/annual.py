"""Annual solar, battery, and efficiency decision analysis."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, time, timezone
from typing import Any, Dict, Iterable, List, Sequence
from zoneinfo import ZoneInfo

import pandas as pd

from .config import BatteryConfig, DispatchConfig, PVConfig, ScenarioConfig
from .engine import run_simulation

TZ = ZoneInfo("Australia/Sydney")
ANALYSIS_ID = "solar_battery_efficiency"

DEFAULT_SOLAR_SIZES_KW = (0.0, 6.6, 8.0, 10.0, 12.0, 15.0)
DEFAULT_BATTERY_SIZES_KWH = (0.0, 5.0, 10.0, 13.5, 20.0, 30.0)

INSTALL_COST_LOOKUP: dict[tuple[float, float], float] = {
    (6.6, 5.0): 13937,
    (6.6, 10.0): 17595,
    (6.6, 13.5): 21311,
    (6.6, 20.0): 24431,
    (6.6, 30.0): 34113,
    (8.0, 5.0): 14097,
    (8.0, 10.0): 17755,
    (8.0, 13.5): 21471,
    (8.0, 20.0): 24591,
    (8.0, 30.0): 34273,
    (10.0, 5.0): 15882,
    (10.0, 10.0): 19540,
    (10.0, 13.5): 23256,
    (10.0, 20.0): 26376,
    (10.0, 30.0): 36058,
    (12.0, 5.0): 17667,
    (12.0, 10.0): 21325,
    (12.0, 13.5): 25041,
    (12.0, 20.0): 28161,
    (12.0, 30.0): 37843,
    (15.0, 5.0): 20344,
    (15.0, 10.0): 24002,
    (15.0, 13.5): 27718,
    (15.0, 20.0): 30838,
    (15.0, 30.0): 40520,
}


@dataclass(frozen=True)
class FinancialConfig:
    """Conservative financial assumptions for decision modelling."""

    system_life_years: int = 15
    discount_rate: float = 0.07
    electricity_escalation: float = 0.028
    cpi_escalation: float = 0.028
    annual_opex_aud: float = 200.0
    solar_degradation: float = 0.01
    battery_degradation: float = 0.02
    export_value_aud_per_kwh: float = 0.02
    export_cap_kw: float = 5.0


def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def local_year_window(year: int) -> tuple[datetime, datetime]:
    """Return Sydney-local calendar year as UTC [start, end)."""
    start_local = datetime.combine(datetime(year, 1, 1).date(), time.min, tzinfo=TZ)
    end_local = datetime.combine(datetime(year + 1, 1, 1).date(), time.min, tzinfo=TZ)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def expected_5min_intervals(start_utc: datetime, end_utc: datetime) -> int:
    return int((end_utc - start_utc).total_seconds() // 300)


def installed_cost_after_rebates(solar_kw: float, battery_kwh: float) -> float:
    """Estimate installed cost after rebates, seeded from the ClearPower workbook grid."""
    key = (round(float(solar_kw), 1), round(float(battery_kwh), 1))
    if key in INSTALL_COST_LOOKUP:
        return float(INSTALL_COST_LOOKUP[key])

    solar_cost = 0.0
    if solar_kw > 0:
        solar_cost = max(0.0, 1800.0 + solar_kw * 1200.0 - 2100.0)

    battery_cost = 0.0
    if battery_kwh > 0:
        battery_cost = max(0.0, battery_kwh * 950.0 - 3488.0)

    return round(solar_cost + battery_cost, 2)


def _scenario_id(solar_kw: float, battery_kwh: float, dispatch_mode: str) -> str:
    solar = str(solar_kw).replace(".", "p")
    battery = str(battery_kwh).replace(".", "p")
    return f"analysis_pv_{solar}kw_battery_{battery}kwh_{dispatch_mode}"


def _build_config(solar_kw: float, battery_kwh: float, dispatch_mode: str, financial: FinancialConfig) -> tuple[ScenarioConfig, str]:
    battery = BatteryConfig(
        capacity_kwh=float(battery_kwh),
        min_soc_kwh=max(float(battery_kwh) * 0.10, 0.0),
        initial_soc_kwh=max(float(battery_kwh) * 0.50, 0.0),
        max_charge_kw=min(max(float(battery_kwh) * 0.5, 0.0), 5.0),
        max_discharge_kw=min(max(float(battery_kwh) * 0.5, 0.0), 5.0),
        max_export_kw=financial.export_cap_kw,
        round_trip_efficiency=0.90,
        degradation_cost_aud_per_kwh=0.02,
        allow_grid_charge=dispatch_mode == "optimizer",
    )

    if dispatch_mode == "base":
        dispatch = DispatchConfig(
            rule_discharge_price_aud_per_kwh=0.0,
            rule_charge_price_aud_per_kwh=-999.0,
            export_arbitrage_price_aud_per_kwh=999.0,
        )
        controller_mode = "rule"
    else:
        dispatch = DispatchConfig(
            rule_discharge_price_aud_per_kwh=0.20,
            rule_charge_price_aud_per_kwh=0.08,
            optimizer_spread_trigger_aud_per_kwh=0.08,
            optimizer_lookahead_intervals=288,
            export_arbitrage_price_aud_per_kwh=0.28,
        )
        controller_mode = "optimizer"

    return ScenarioConfig(
        scenario_id=_scenario_id(solar_kw, battery_kwh, dispatch_mode),
        timezone_display="Australia/Sydney",
        pv=PVConfig(capacity_kw=float(solar_kw)),
        battery=battery,
        dispatch=dispatch,
    ), controller_mode


def _irr(cashflows: Sequence[float]) -> float | None:
    if not cashflows or all(abs(cf) < 1e-9 for cf in cashflows):
        return None

    def npv(rate: float) -> float:
        return sum(cf / ((1.0 + rate) ** idx) for idx, cf in enumerate(cashflows))

    low, high = -0.95, 1.0
    low_npv, high_npv = npv(low), npv(high)
    if low_npv == 0:
        return low
    if high_npv == 0:
        return high
    if (low_npv > 0 and high_npv > 0) or (low_npv < 0 and high_npv < 0):
        return None

    for _ in range(80):
        mid = (low + high) / 2.0
        mid_npv = npv(mid)
        if abs(mid_npv) < 1e-7:
            return mid
        if (low_npv < 0 and mid_npv < 0) or (low_npv > 0 and mid_npv > 0):
            low, low_npv = mid, mid_npv
        else:
            high = mid
    return (low + high) / 2.0


def _cashflow(year1_saving: float, install_cost: float, financial: FinancialConfig) -> tuple[list[dict[str, Any]], float | None, float, float]:
    cumulative = -install_cost
    payback: float | None = None
    cashflows = [-install_cost]
    rows: list[dict[str, Any]] = []

    for year in range(1, financial.system_life_years + 1):
        degradation_factor = (1.0 - financial.solar_degradation) ** (year - 1)
        escalation_factor = (1.0 + financial.electricity_escalation) ** (year - 1)
        opex = financial.annual_opex_aud * ((1.0 + financial.cpi_escalation) ** (year - 1))
        gross_saving = max(year1_saving, 0.0) * degradation_factor * escalation_factor
        net_cashflow = gross_saving - opex if install_cost > 0 else gross_saving
        previous_cumulative = cumulative
        cumulative += net_cashflow
        cashflows.append(net_cashflow)

        if payback is None and previous_cumulative < 0 <= cumulative and net_cashflow > 0:
            payback = (year - 1) + abs(previous_cumulative) / net_cashflow

        rows.append(
            {
                "year": year,
                "gross_saving_aud": round(gross_saving, 2),
                "opex_aud": round(opex if install_cost > 0 else 0.0, 2),
                "net_cashflow_aud": round(net_cashflow, 2),
                "cumulative_cashflow_aud": round(cumulative, 2),
            }
        )

    return rows, _irr(cashflows), payback, cumulative


def _discounted_total(values: Iterable[float], discount_rate: float) -> float:
    return sum(value / ((1.0 + discount_rate) ** idx) for idx, value in enumerate(values, start=1))


def _safe_corr(a: pd.Series, b: pd.Series) -> float | None:
    if len(a.dropna()) < 3 or len(b.dropna()) < 3:
        return None
    corr = a.corr(b)
    if pd.isna(corr):
        return None
    return float(corr)


def data_quality_report(
    usage_df: pd.DataFrame,
    price_df: pd.DataFrame,
    weather_df: pd.DataFrame,
    start_utc: datetime,
    end_utc: datetime,
) -> dict[str, Any]:
    expected = expected_5min_intervals(start_utc, end_utc)

    def coverage(df: pd.DataFrame, label: str) -> dict[str, Any]:
        if df.empty or "interval_start" not in df:
            return {
                "label": label,
                "intervals": 0,
                "expected_intervals": expected,
                "coverage_pct": 0.0,
                "first_interval": None,
                "last_interval": None,
            }
        ts = pd.to_datetime(df["interval_start"], utc=True).dropna()
        count = int(ts.nunique())
        return {
            "label": label,
            "intervals": count,
            "expected_intervals": expected,
            "coverage_pct": round((count / expected) * 100.0, 2) if expected else 0.0,
            "first_interval": ts.min().isoformat().replace("+00:00", "Z") if not ts.empty else None,
            "last_interval": ts.max().isoformat().replace("+00:00", "Z") if not ts.empty else None,
        }

    usage_source_counts: dict[str, int] = {}
    if not usage_df.empty and "usage_source" in usage_df:
        usage_source_counts = {str(k): int(v) for k, v in usage_df["usage_source"].fillna("unknown").value_counts().items()}

    checks = {
        "usage": coverage(usage_df, "usage"),
        "prices": coverage(price_df, "prices"),
        "irradiance": coverage(weather_df, "irradiance"),
    }
    ready = checks["usage"]["coverage_pct"] >= 90 and checks["prices"]["coverage_pct"] >= 90 and checks["irradiance"]["coverage_pct"] >= 80
    model_ready = (
        ready
        or (
            checks["usage"]["coverage_pct"] >= 60
            and checks["prices"]["coverage_pct"] >= 90
            and checks["irradiance"]["coverage_pct"] >= 80
        )
    )

    return {
        "ready": ready,
        "model_ready": model_ready,
        "window_start": iso_z(start_utc),
        "window_end": iso_z(end_utc),
        "expected_5min_intervals": expected,
        "checks": checks,
        "usage_source_counts": usage_source_counts,
        "warnings": [
            warning
            for warning in [
                "Usage coverage is below 90%" if checks["usage"]["coverage_pct"] < 90 else None,
                "Usage gaps are filled from the observed daily profile for scenario modelling." if not ready and model_ready else None,
                "Price coverage is below 90%" if checks["prices"]["coverage_pct"] < 90 else None,
                "Irradiance coverage is below 80%" if checks["irradiance"]["coverage_pct"] < 80 else None,
                "Powerpal is treated as import/consumption only; it is not an export meter.",
            ]
            if warning
        ],
    }


def load_shift_analysis(usage_df: pd.DataFrame, price_df: pd.DataFrame, weather_df: pd.DataFrame) -> dict[str, Any]:
    if usage_df.empty:
        return {"status": "missing", "opportunities": [], "metrics": {}, "worst_days": []}

    usage = usage_df.copy()
    usage["interval_start"] = pd.to_datetime(usage["interval_start"], utc=True)
    usage["usage_kwh"] = pd.to_numeric(usage["usage_kwh"], errors="coerce").fillna(0.0).clip(lower=0.0)
    usage = usage.sort_values("interval_start").drop_duplicates(subset=["interval_start"], keep="last")

    prices = price_df.copy()
    if not prices.empty:
        prices["interval_start"] = pd.to_datetime(prices["interval_start"], utc=True)
        prices["price_cents_per_kwh"] = pd.to_numeric(prices["price_cents_per_kwh"], errors="coerce")
        prices = prices.sort_values("interval_start").drop_duplicates(subset=["interval_start"], keep="last")
        usage = usage.merge(prices[["interval_start", "price_cents_per_kwh"]], on="interval_start", how="left")
    else:
        usage["price_cents_per_kwh"] = 0.0

    usage["price_aud_per_kwh"] = usage["price_cents_per_kwh"].ffill().bfill().fillna(0.0) / 100.0
    usage["local_time"] = usage["interval_start"].dt.tz_convert(TZ)
    usage["local_date"] = usage["local_time"].dt.date
    usage["hour"] = usage["local_time"].dt.hour
    usage["weekday"] = usage["local_time"].dt.weekday
    usage["kw"] = usage["usage_kwh"] * 12.0
    usage["cost_aud"] = usage["usage_kwh"] * usage["price_aud_per_kwh"]

    overnight = usage[(usage["hour"] >= 0) & (usage["hour"] < 5)]
    baseload_kw = float(overnight["kw"].median()) if not overnight.empty else 0.0
    baseload_annual_kwh = baseload_kw * 24.0 * 365.0
    avg_price = float(usage["price_aud_per_kwh"].mean()) if not usage.empty else 0.0

    evening = usage[(usage["hour"] >= 17) & (usage["hour"] < 22)]
    midday = usage[(usage["hour"] >= 10) & (usage["hour"] < 15)]
    morning = usage[(usage["hour"] >= 6) & (usage["hour"] < 9)]
    flexible_evening_kwh = float((evening["usage_kwh"] - baseload_kw / 12.0).clip(lower=0.0).sum()) if not evening.empty else 0.0
    shiftable_kwh = flexible_evening_kwh * 0.25
    evening_price = float(evening["price_aud_per_kwh"].mean()) if not evening.empty else avg_price
    midday_price = float(midday["price_aud_per_kwh"].mean()) if not midday.empty else avg_price
    shift_saving = shiftable_kwh * max(evening_price - midday_price, 0.0)

    daily = usage.groupby("local_date", as_index=False).agg(
        usage_kwh=("usage_kwh", "sum"),
        cost_aud=("cost_aud", "sum"),
        avg_price_aud_per_kwh=("price_aud_per_kwh", "mean"),
        peak_kw=("kw", "max"),
    )
    daily["weekday"] = pd.to_datetime(daily["local_date"]).dt.weekday
    weekday_kwh = float(daily[daily["weekday"] < 5]["usage_kwh"].mean()) if not daily.empty else 0.0
    weekend_kwh = float(daily[daily["weekday"] >= 5]["usage_kwh"].mean()) if not daily.empty else 0.0

    weather_corr = None
    if not weather_df.empty:
        weather = weather_df.copy()
        weather["interval_start"] = pd.to_datetime(weather["interval_start"], utc=True)
        weather["local_date"] = weather["interval_start"].dt.tz_convert(TZ).dt.date
        weather_daily = weather.groupby("local_date", as_index=False).agg(avg_temperature_c=("temperature_c", "mean"))
        daily_weather = daily.merge(weather_daily, on="local_date", how="inner")
        weather_corr = _safe_corr(daily_weather["usage_kwh"], daily_weather["avg_temperature_c"])

    p95_kw = float(usage["kw"].quantile(0.95)) if not usage.empty else 0.0
    spike_intervals = usage[usage["kw"] >= p95_kw]
    spike_kwh = float(spike_intervals["usage_kwh"].sum())

    opportunities = [
        {
            "title": "Shift evening flexible load into midday",
            "type": "load_shift",
            "evidence": f"Evening flexible-load estimate is {flexible_evening_kwh:.0f} kWh/year above overnight baseload.",
            "estimated_annual_saving_aud": round(shift_saving, 2),
            "confidence": "medium" if shiftable_kwh > 100 else "low",
        },
        {
            "title": "Reduce standby baseload",
            "type": "efficiency",
            "evidence": f"Overnight median demand is {baseload_kw:.2f} kW.",
            "estimated_annual_saving_aud": round(baseload_annual_kwh * 0.20 * avg_price, 2),
            "confidence": "medium" if baseload_kw > 0.25 else "low",
        },
        {
            "title": "Investigate high-power spikes",
            "type": "candidate_experiment",
            "evidence": f"Top 5% intervals reach at least {p95_kw:.1f} kW and total {spike_kwh:.0f} kWh.",
            "estimated_annual_saving_aud": round(spike_kwh * 0.10 * avg_price, 2),
            "confidence": "low",
        },
    ]

    if weather_corr is not None and abs(weather_corr) >= 0.35:
        opportunities.append(
            {
                "title": "Weather-sensitive load is visible",
                "type": "efficiency",
                "evidence": f"Daily usage/temperature correlation is {weather_corr:.2f}.",
                "estimated_annual_saving_aud": None,
                "confidence": "medium",
            }
        )

    worst_days = (
        daily.sort_values("cost_aud", ascending=False)
        .head(20)
        .assign(local_date=lambda df: df["local_date"].astype(str))
        .round({"usage_kwh": 2, "cost_aud": 2, "avg_price_aud_per_kwh": 4, "peak_kw": 2})
        .to_dict(orient="records")
    )

    return {
        "status": "ok",
        "metrics": {
            "overnight_baseload_kw": round(baseload_kw, 3),
            "baseload_annual_kwh": round(baseload_annual_kwh, 1),
            "morning_usage_kwh": round(float(morning["usage_kwh"].sum()), 2),
            "evening_usage_kwh": round(float(evening["usage_kwh"].sum()), 2),
            "midday_usage_kwh": round(float(midday["usage_kwh"].sum()), 2),
            "shiftable_kwh_estimate": round(shiftable_kwh, 2),
            "weekday_avg_kwh": round(weekday_kwh, 2),
            "weekend_avg_kwh": round(weekend_kwh, 2),
            "temperature_usage_correlation": round(weather_corr, 3) if weather_corr is not None else None,
        },
        "opportunities": opportunities,
        "worst_days": worst_days,
    }


def _monthly_energy_mix(results: pd.DataFrame) -> list[dict[str, Any]]:
    if results.empty:
        return []
    df = results.copy()
    df["interval_start"] = pd.to_datetime(df["interval_start"], utc=True)
    df["month"] = df["interval_start"].dt.tz_convert(TZ).dt.strftime("%b")
    load = df["baseline_import_kwh"].clip(lower=0.0)
    pv = df["pv_generation_kwh"].clip(lower=0.0)
    df["solar_direct_kwh"] = pd.concat([load, pv], axis=1).min(axis=1)
    df["battery_kwh"] = df["battery_discharge_kwh"].clip(lower=0.0)
    df["grid_kwh"] = df["scenario_import_kwh"].clip(lower=0.0)
    grouped = df.groupby("month", sort=False).agg(
        solar_direct_kwh=("solar_direct_kwh", "sum"),
        battery_kwh=("battery_kwh", "sum"),
        grid_kwh=("grid_kwh", "sum"),
    )
    return grouped.round(2).reset_index().to_dict(orient="records")


def _aggregate_scenario(
    results: pd.DataFrame,
    solar_kw: float,
    battery_kwh: float,
    dispatch_mode: str,
    financial: FinancialConfig,
) -> dict[str, Any]:
    df = results.copy()
    if df.empty:
        install_cost = installed_cost_after_rebates(solar_kw, battery_kwh)
        cashflow, irr, payback, net_benefit = _cashflow(0.0, install_cost, financial)
        return {
            "scenario_id": _scenario_id(solar_kw, battery_kwh, dispatch_mode),
            "dispatch_mode": dispatch_mode,
            "solar_kw": solar_kw,
            "battery_kwh": battery_kwh,
            "installed_cost_after_rebates_aud": install_cost,
            "year1_saving_aud": 0.0,
            "payback_years": payback,
            "irr_pct": round(irr * 100.0, 2) if irr is not None else None,
            "lifetime_net_benefit_aud": round(net_benefit, 2),
            "cashflow": cashflow,
        }

    price = pd.to_numeric(df["price_aud_per_kwh"], errors="coerce").fillna(0.0)
    baseline_import = pd.to_numeric(df["baseline_import_kwh"], errors="coerce").fillna(0.0).clip(lower=0.0)
    scenario_import = pd.to_numeric(df["scenario_import_kwh"], errors="coerce").fillna(0.0).clip(lower=0.0)
    export_kwh = pd.to_numeric(df["export_kwh"], errors="coerce").fillna(0.0).clip(lower=0.0)
    battery_discharge = pd.to_numeric(df["battery_discharge_kwh"], errors="coerce").fillna(0.0).clip(lower=0.0)

    baseline_cost = float((baseline_import * price).sum())
    degradation_cost = float((battery_discharge * 0.02).sum())
    scenario_cost = float((scenario_import * price).sum() - (export_kwh * financial.export_value_aud_per_kwh).sum() + degradation_cost)
    year1_saving = baseline_cost - scenario_cost
    install_cost = installed_cost_after_rebates(solar_kw, battery_kwh)
    cashflow, irr, payback, net_benefit = _cashflow(year1_saving, install_cost, financial)

    usage_kwh = float(baseline_import.sum())
    solar_generation = float(pd.to_numeric(df["pv_generation_kwh"], errors="coerce").fillna(0.0).clip(lower=0.0).sum())
    grid_reduction = ((usage_kwh - float(scenario_import.sum())) / usage_kwh * 100.0) if usage_kwh > 0 else 0.0
    self_supply = max(min(grid_reduction, 100.0), 0.0)
    gross_saving_15y = sum(row["gross_saving_aud"] for row in cashflow)
    total_15y_cost = _discounted_total([max(scenario_cost, 0.0) * ((1.0 + financial.electricity_escalation) ** i) for i in range(financial.system_life_years)], financial.discount_rate)
    total_15y_opex = _discounted_total([financial.annual_opex_aud * ((1.0 + financial.cpi_escalation) ** i) for i in range(financial.system_life_years)], financial.discount_rate)
    effective_rate = ((total_15y_cost + install_cost + total_15y_opex) / max(usage_kwh * financial.system_life_years, 1e-9)) * 100.0

    return {
        "scenario_id": _scenario_id(solar_kw, battery_kwh, dispatch_mode),
        "dispatch_mode": dispatch_mode,
        "solar_kw": float(solar_kw),
        "battery_kwh": float(battery_kwh),
        "installed_cost_after_rebates_aud": round(install_cost, 2),
        "year1_saving_aud": round(year1_saving, 2),
        "annual_solar_generation_kwh": round(solar_generation, 2),
        "grid_import_reduction_pct": round(grid_reduction, 2),
        "self_supply_pct": round(self_supply, 2),
        "export_kwh": round(float(export_kwh.sum()), 2),
        "export_revenue_aud": round(float((export_kwh * financial.export_value_aud_per_kwh).sum()), 2),
        "gross_15yr_saving_aud": round(gross_saving_15y, 2),
        "lifetime_net_benefit_aud": round(net_benefit, 2),
        "irr_pct": round(irr * 100.0, 2) if irr is not None else None,
        "payback_years": round(payback, 2) if payback is not None else None,
        "effective_rate_c_per_kwh": round(effective_rate, 2),
        "baseline_cost_aud": round(baseline_cost, 2),
        "scenario_cost_aud": round(scenario_cost, 2),
        "annual_usage_kwh": round(usage_kwh, 2),
        "cashflow": cashflow,
        "monthly_energy_mix": _monthly_energy_mix(df),
    }


def _recommendations(scenarios: list[dict[str, Any]]) -> dict[str, Any]:
    base = [s for s in scenarios if s.get("dispatch_mode") == "base" and s.get("solar_kw", 0) > 0]
    if not base:
        base = scenarios

    def valid_payback(s: dict[str, Any]) -> bool:
        return s.get("payback_years") is not None and s.get("year1_saving_aud", 0) > 0

    lowest_cost = min(base, key=lambda s: (s.get("effective_rate_c_per_kwh", 999999), -s.get("lifetime_net_benefit_aud", -999999))) if base else None
    fastest = min([s for s in base if valid_payback(s)] or base, key=lambda s: s.get("payback_years") if s.get("payback_years") is not None else 999999) if base else None
    self_sufficiency = max(base, key=lambda s: (s.get("self_supply_pct", 0), s.get("lifetime_net_benefit_aud", -999999))) if base else None

    out = {
        "lowest_cost": lowest_cost,
        "fastest_payback": fastest,
        "self_sufficiency": self_sufficiency,
    }

    if lowest_cost:
        base_benefit = lowest_cost.get("lifetime_net_benefit_aud", 0.0)
        cost = lowest_cost.get("installed_cost_after_rebates_aud", 0.0)
        out["sensitivity"] = [
            {"scenario": "Base case", "lifetime_benefit_aud": round(base_benefit, 2), "payback_years": lowest_cost.get("payback_years"), "irr_pct": lowest_cost.get("irr_pct")},
            {"scenario": "Install cost (+10%)", "lifetime_benefit_aud": round(base_benefit - cost * 0.10, 2), "payback_years": None, "irr_pct": None},
            {"scenario": "Install cost (-10%)", "lifetime_benefit_aud": round(base_benefit + cost * 0.10, 2), "payback_years": None, "irr_pct": None},
            {"scenario": "Electricity rate (+10%)", "lifetime_benefit_aud": round(base_benefit + max(lowest_cost.get("gross_15yr_saving_aud", 0.0), 0.0) * 0.10, 2), "payback_years": None, "irr_pct": None},
            {"scenario": "Electricity rate (-10%)", "lifetime_benefit_aud": round(base_benefit - max(lowest_cost.get("gross_15yr_saving_aud", 0.0), 0.0) * 0.10, 2), "payback_years": None, "irr_pct": None},
        ]

    return out


def run_annual_analysis(
    usage_df: pd.DataFrame,
    price_df: pd.DataFrame,
    weather_df: pd.DataFrame,
    year: int,
    solar_sizes_kw: Sequence[float] = DEFAULT_SOLAR_SIZES_KW,
    battery_sizes_kwh: Sequence[float] = DEFAULT_BATTERY_SIZES_KWH,
    financial: FinancialConfig | None = None,
) -> dict[str, Any]:
    financial = financial or FinancialConfig()
    start_utc, end_utc = local_year_window(year)
    quality = data_quality_report(usage_df, price_df, weather_df, start_utc, end_utc)

    scenarios: list[dict[str, Any]] = []
    for dispatch_mode in ("base", "optimizer"):
        for solar_kw in solar_sizes_kw:
            for battery_kwh in battery_sizes_kwh:
                config, controller_mode = _build_config(float(solar_kw), float(battery_kwh), dispatch_mode, financial)
                results = run_simulation(
                    usage_df=usage_df,
                    price_df=price_df,
                    weather_df=weather_df,
                    start_utc=start_utc,
                    end_utc=end_utc,
                    as_of_utc=end_utc,
                    controller_mode=controller_mode,
                    config=config,
                )
                scenarios.append(_aggregate_scenario(results, float(solar_kw), float(battery_kwh), dispatch_mode, financial))

    generated_at = datetime.now(timezone.utc)
    return {
        "analysis_id": ANALYSIS_ID,
        "year": int(year),
        "generated_at": iso_z(generated_at),
        "window_start": iso_z(start_utc),
        "window_end": iso_z(end_utc),
        "data_quality": quality,
        "scenarios": scenarios,
        "recommendations": _recommendations(scenarios),
        "load_shift": load_shift_analysis(usage_df, price_df, weather_df),
        "assumptions": {
            "financial": asdict(financial),
            "solar_sizes_kw": list(solar_sizes_kw),
            "battery_sizes_kwh": list(battery_sizes_kwh),
            "irradiance_source": "Open-Meteo modelled historical irradiance near Vaucluse NSW; not measured rooftop output.",
            "powerpal_policy": "Powerpal CSV export-link workflow only; Powerpal is treated as import/consumption and not export metering.",
            "cost_source": "Installed cost curve seeded from attached ClearPower-style workbook and editable in code/config.",
        },
    }
