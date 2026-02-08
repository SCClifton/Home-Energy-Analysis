"""Core scenario simulation engine for PV + battery digital twin."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .config import ScenarioConfig


@dataclass
class SimulationSummary:
    as_of: str
    stale: bool
    stale_reason: str | None
    today_savings_aud: float
    mtd_savings_aud: float
    next_24h_projected_savings_aud: float
    current_battery_soc_kwh: float
    today_solar_generation_kwh: float
    today_export_revenue_aud: float
    today_export_kwh: float
    intervals_count: int
    estimated_usage_intervals: int

    def to_dict(self) -> Dict[str, object]:
        return {
            "as_of": self.as_of,
            "stale": self.stale,
            "stale_reason": self.stale_reason,
            "today_savings_aud": round(self.today_savings_aud, 4),
            "mtd_savings_aud": round(self.mtd_savings_aud, 4),
            "next_24h_projected_savings_aud": round(self.next_24h_projected_savings_aud, 4),
            "current_battery_soc_kwh": round(self.current_battery_soc_kwh, 4),
            "today_solar_generation_kwh": round(self.today_solar_generation_kwh, 4),
            "today_export_revenue_aud": round(self.today_export_revenue_aud, 4),
            "today_export_kwh": round(self.today_export_kwh, 4),
            "intervals_count": int(self.intervals_count),
            "estimated_usage_intervals": int(self.estimated_usage_intervals),
        }


def _build_usage_profile(usage_df: pd.DataFrame) -> Dict[int, float]:
    if usage_df.empty:
        return {}

    work = usage_df.copy()
    work["interval_start"] = pd.to_datetime(work["interval_start"], utc=True)
    work["usage_kwh"] = pd.to_numeric(work["usage_kwh"], errors="coerce")
    work = work.dropna(subset=["interval_start", "usage_kwh"])
    if work.empty:
        return {}

    slots = (work["interval_start"].dt.hour * 60 + work["interval_start"].dt.minute) // 5
    work = work.assign(slot=slots)
    grouped = work.groupby("slot")["usage_kwh"].median()
    return {int(slot): float(value) for slot, value in grouped.items()}


def _estimate_usage_for_row(ts: pd.Timestamp, profile: Dict[int, float], fallback: float) -> float:
    slot = int((ts.hour * 60 + ts.minute) // 5)
    value = profile.get(slot)
    if value is None:
        return fallback
    return value


def _prepare_interval_frame(
    usage_df: pd.DataFrame,
    price_df: pd.DataFrame,
    weather_df: pd.DataFrame,
    start_utc: datetime,
    end_utc: datetime,
    as_of_utc: datetime,
) -> pd.DataFrame:
    index = pd.date_range(start=start_utc, end=end_utc, freq="5min", inclusive="left", tz="UTC")
    frame = pd.DataFrame(index=index)
    frame["interval_start"] = frame.index
    frame["interval_end"] = frame["interval_start"] + pd.Timedelta(minutes=5)

    usage = usage_df.copy()
    if not usage.empty:
        usage["interval_start"] = pd.to_datetime(usage["interval_start"], utc=True)
        usage["usage_kwh"] = pd.to_numeric(usage["usage_kwh"], errors="coerce")
        usage = usage.sort_values("interval_start").drop_duplicates(subset=["interval_start"], keep="last")
        frame = frame.merge(usage[["interval_start", "usage_kwh"]], on="interval_start", how="left")
    else:
        frame["usage_kwh"] = np.nan

    prices = price_df.copy()
    if not prices.empty:
        prices["interval_start"] = pd.to_datetime(prices["interval_start"], utc=True)
        prices["price_cents_per_kwh"] = pd.to_numeric(prices["price_cents_per_kwh"], errors="coerce")
        prices = prices.sort_values("interval_start").drop_duplicates(subset=["interval_start"], keep="last")
        frame = frame.merge(prices[["interval_start", "price_cents_per_kwh"]], on="interval_start", how="left")
    else:
        frame["price_cents_per_kwh"] = np.nan

    weather = weather_df.copy()
    if not weather.empty:
        weather["interval_start"] = pd.to_datetime(weather["interval_start"], utc=True)
        weather = weather.sort_values("interval_start").drop_duplicates(subset=["interval_start"], keep="last")
        frame = frame.merge(
            weather[["interval_start", "ghi_wm2", "temperature_c", "cloud_cover_pct"]],
            on="interval_start",
            how="left",
        )
    else:
        frame["ghi_wm2"] = np.nan
        frame["temperature_c"] = np.nan
        frame["cloud_cover_pct"] = np.nan

    frame["price_aud_per_kwh"] = frame["price_cents_per_kwh"] / 100.0
    frame["price_aud_per_kwh"] = frame["price_aud_per_kwh"].ffill().bfill().fillna(0.0)

    usage_profile = _build_usage_profile(usage_df)
    usage_fallback = float(pd.to_numeric(usage_df.get("usage_kwh"), errors="coerce").median()) if not usage_df.empty else 0.3
    if np.isnan(usage_fallback):
        usage_fallback = 0.3

    estimated_flags: List[bool] = []
    usage_values: List[float] = []
    for row in frame.itertuples(index=False):
        raw_usage = row.usage_kwh
        if raw_usage is None or pd.isna(raw_usage):
            usage_values.append(_estimate_usage_for_row(row.interval_start, usage_profile, usage_fallback))
            estimated_flags.append(True)
        else:
            usage_values.append(max(float(raw_usage), 0.0))
            estimated_flags.append(False)

    frame["usage_kwh"] = usage_values
    frame["is_estimated_usage"] = estimated_flags

    frame["ghi_wm2"] = pd.to_numeric(frame["ghi_wm2"], errors="coerce").fillna(0.0).clip(lower=0.0)
    frame["temperature_c"] = pd.to_numeric(frame["temperature_c"], errors="coerce").fillna(20.0)
    frame["cloud_cover_pct"] = pd.to_numeric(frame["cloud_cover_pct"], errors="coerce").fillna(0.0).clip(lower=0.0, upper=100.0)

    frame["is_future"] = frame["interval_start"] > pd.Timestamp(as_of_utc)
    return frame


def _add_price_lookahead_features(frame: pd.DataFrame, lookahead_intervals: int) -> pd.DataFrame:
    prices = frame["price_aud_per_kwh"].astype(float)
    reverse = prices.iloc[::-1]

    frame["future_max_price"] = reverse.rolling(lookahead_intervals, min_periods=1).max().iloc[::-1].values
    frame["future_min_price"] = reverse.rolling(lookahead_intervals, min_periods=1).min().iloc[::-1].values
    frame["future_q25_price"] = reverse.rolling(lookahead_intervals, min_periods=1).quantile(0.25).iloc[::-1].values
    frame["future_q75_price"] = reverse.rolling(lookahead_intervals, min_periods=1).quantile(0.75).iloc[::-1].values
    return frame


def _pv_output_kwh(ghi_wm2: float, temperature_c: float, interval_hours: float, config: ScenarioConfig) -> float:
    if ghi_wm2 <= 0 or interval_hours <= 0:
        return 0.0

    pv = config.pv
    irradiance_ratio = max(ghi_wm2, 0.0) / 1000.0
    temp_factor = 1.0 + pv.temperature_coefficient_per_c * (temperature_c - pv.reference_temperature_c)
    temp_factor = max(temp_factor, 0.0)

    raw_output = pv.capacity_kw * irradiance_ratio * interval_hours
    output = raw_output * pv.performance_ratio * temp_factor

    # Physical cap to avoid numerical overshoot under interpolation artifacts.
    cap = pv.capacity_kw * interval_hours
    return float(max(min(output, cap), 0.0))


def run_simulation(
    usage_df: pd.DataFrame,
    price_df: pd.DataFrame,
    weather_df: pd.DataFrame,
    start_utc: datetime,
    end_utc: datetime,
    as_of_utc: datetime,
    controller_mode: str,
    config: ScenarioConfig,
) -> pd.DataFrame:
    """Run interval simulation and return per-interval outputs."""
    frame = _prepare_interval_frame(usage_df, price_df, weather_df, start_utc, end_utc, as_of_utc)
    frame = _add_price_lookahead_features(frame, config.dispatch.optimizer_lookahead_intervals)

    batt = config.battery
    dispatch = config.dispatch

    soc = min(max(batt.initial_soc_kwh, batt.min_soc_kwh), batt.capacity_kwh)
    rows: List[Dict[str, float | bool | pd.Timestamp]] = []

    charge_eff = batt.charge_efficiency
    discharge_eff = batt.discharge_efficiency

    for row in frame.itertuples(index=False):
        interval_hours = (row.interval_end - row.interval_start).total_seconds() / 3600.0
        load_kwh = max(float(row.usage_kwh), 0.0)
        price = float(row.price_aud_per_kwh)

        pv_kwh = _pv_output_kwh(float(row.ghi_wm2), float(row.temperature_c), interval_hours, config)

        baseline_import_kwh = load_kwh
        baseline_cost_aud = baseline_import_kwh * price

        pv_to_load = min(load_kwh, pv_kwh)
        remaining_load = load_kwh - pv_to_load
        pv_surplus = pv_kwh - pv_to_load

        battery_charge_kwh = 0.0
        battery_discharge_kwh = 0.0
        grid_charge_kwh = 0.0
        export_kwh = 0.0

        max_charge_input_kwh = min(
            batt.max_charge_kw * interval_hours,
            max((batt.capacity_kwh - soc) / charge_eff, 0.0),
        )

        charge_from_pv = min(pv_surplus, max_charge_input_kwh)
        if charge_from_pv > 0:
            soc += charge_from_pv * charge_eff
            battery_charge_kwh += charge_from_pv
            pv_surplus -= charge_from_pv
            max_charge_input_kwh -= charge_from_pv

        max_discharge_output_kwh = min(
            batt.max_discharge_kw * interval_hours,
            max((soc - batt.min_soc_kwh) * discharge_eff, 0.0),
        )

        if controller_mode == "rule":
            should_discharge = price >= dispatch.rule_discharge_price_aud_per_kwh
            should_grid_charge = (
                batt.allow_grid_charge
                and price <= dispatch.rule_charge_price_aud_per_kwh
                and soc < batt.capacity_kwh * 0.8
            )
            should_export = price >= dispatch.export_arbitrage_price_aud_per_kwh and soc > batt.min_soc_kwh + 0.5
        else:
            should_discharge = price >= float(row.future_q75_price)
            should_grid_charge = (
                batt.allow_grid_charge
                and price <= float(row.future_q25_price)
                and (float(row.future_max_price) - price) >= dispatch.optimizer_spread_trigger_aud_per_kwh
            )
            should_export = price >= max(dispatch.export_arbitrage_price_aud_per_kwh, float(row.future_q75_price))

        if should_discharge and remaining_load > 0 and max_discharge_output_kwh > 0:
            discharge_to_load = min(remaining_load, max_discharge_output_kwh)
            soc -= discharge_to_load / discharge_eff
            battery_discharge_kwh += discharge_to_load
            remaining_load -= discharge_to_load
            max_discharge_output_kwh -= discharge_to_load

        if should_grid_charge and max_charge_input_kwh > 0:
            if controller_mode == "rule":
                grid_charge_kwh = min(max_charge_input_kwh, batt.max_charge_kw * interval_hours * 0.6)
            else:
                grid_charge_kwh = max_charge_input_kwh
            soc += grid_charge_kwh * charge_eff
            battery_charge_kwh += grid_charge_kwh
            max_charge_input_kwh -= grid_charge_kwh

        export_cap_kwh = batt.max_export_kw * interval_hours
        if should_export and max_discharge_output_kwh > 0 and export_cap_kwh > 0:
            discharge_to_export = min(max_discharge_output_kwh, export_cap_kwh)
            soc -= discharge_to_export / discharge_eff
            battery_discharge_kwh += discharge_to_export
            export_kwh += discharge_to_export
            export_cap_kwh -= discharge_to_export

        pv_export = min(pv_surplus, max(export_cap_kwh, 0.0))
        export_kwh += pv_export

        soc = min(max(soc, batt.min_soc_kwh), batt.capacity_kwh)

        scenario_import_kwh = max(remaining_load, 0.0) + grid_charge_kwh
        degradation_cost_aud = batt.degradation_cost_aud_per_kwh * battery_discharge_kwh
        scenario_cost_aud = scenario_import_kwh * price - export_kwh * price + degradation_cost_aud
        savings_aud = baseline_cost_aud - scenario_cost_aud

        rows.append(
            {
                "interval_start": row.interval_start,
                "interval_end": row.interval_end,
                "baseline_import_kwh": baseline_import_kwh,
                "scenario_import_kwh": scenario_import_kwh,
                "battery_charge_kwh": battery_charge_kwh,
                "battery_discharge_kwh": battery_discharge_kwh,
                "battery_soc_kwh": soc,
                "export_kwh": export_kwh,
                "pv_generation_kwh": pv_kwh,
                "baseline_cost_aud": baseline_cost_aud,
                "scenario_cost_aud": scenario_cost_aud,
                "savings_aud": savings_aud,
                "price_aud_per_kwh": price,
                "is_estimated_usage": bool(row.is_estimated_usage),
                "is_future": bool(row.is_future),
            }
        )

    out = pd.DataFrame(rows)
    out["interval_start"] = pd.to_datetime(out["interval_start"], utc=True)
    out["interval_end"] = pd.to_datetime(out["interval_end"], utc=True)
    return out


def summarise_results(results_df: pd.DataFrame, as_of_utc: datetime, config: ScenarioConfig) -> SimulationSummary:
    """Compute dashboard-friendly summary values from interval simulation outputs."""
    if results_df.empty:
        return SimulationSummary(
            as_of=as_of_utc.isoformat().replace("+00:00", "Z"),
            stale=True,
            stale_reason="no_simulation_intervals",
            today_savings_aud=0.0,
            mtd_savings_aud=0.0,
            next_24h_projected_savings_aud=0.0,
            current_battery_soc_kwh=0.0,
            today_solar_generation_kwh=0.0,
            today_export_revenue_aud=0.0,
            today_export_kwh=0.0,
            intervals_count=0,
            estimated_usage_intervals=0,
        )

    sydney = ZoneInfo(config.timezone_display)
    now_sydney = as_of_utc.astimezone(sydney)

    day_start_sydney = now_sydney.replace(hour=0, minute=0, second=0, microsecond=0)
    next_day_start_sydney = day_start_sydney + timedelta(days=1)

    month_start_sydney = now_sydney.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    day_start_utc = day_start_sydney.astimezone(timezone.utc)
    next_day_start_utc = next_day_start_sydney.astimezone(timezone.utc)
    month_start_utc = month_start_sydney.astimezone(timezone.utc)
    next_24h_utc = as_of_utc + timedelta(hours=24)

    df = results_df.copy()
    df["interval_start"] = pd.to_datetime(df["interval_start"], utc=True)

    realised = df[df["interval_start"] <= pd.Timestamp(as_of_utc)]
    today_realised = realised[
        (realised["interval_start"] >= pd.Timestamp(day_start_utc))
        & (realised["interval_start"] < pd.Timestamp(next_day_start_utc))
    ]
    mtd_realised = realised[realised["interval_start"] >= pd.Timestamp(month_start_utc)]

    projected = df[
        (df["interval_start"] > pd.Timestamp(as_of_utc))
        & (df["interval_start"] <= pd.Timestamp(next_24h_utc))
    ]

    latest_row = realised.sort_values("interval_start").tail(1)
    current_soc = float(latest_row["battery_soc_kwh"].iloc[0]) if not latest_row.empty else 0.0

    price_export_today = (today_realised["export_kwh"] * today_realised["price_aud_per_kwh"]).sum()

    lag_seconds = max(int((datetime.now(timezone.utc) - as_of_utc).total_seconds()), 0)
    stale = lag_seconds > 900

    stale_reason = None
    if stale:
        stale_reason = f"as_of_lag_seconds={lag_seconds}"
    elif len(realised) == 0:
        stale_reason = "no_realised_intervals"

    return SimulationSummary(
        as_of=as_of_utc.isoformat().replace("+00:00", "Z"),
        stale=stale,
        stale_reason=stale_reason,
        today_savings_aud=float(today_realised["savings_aud"].sum()),
        mtd_savings_aud=float(mtd_realised["savings_aud"].sum()),
        next_24h_projected_savings_aud=float(projected["savings_aud"].sum()),
        current_battery_soc_kwh=current_soc,
        today_solar_generation_kwh=float(today_realised["pv_generation_kwh"].sum()),
        today_export_revenue_aud=float(price_export_today),
        today_export_kwh=float(today_realised["export_kwh"].sum()),
        intervals_count=len(df),
        estimated_usage_intervals=int(realised["is_estimated_usage"].sum()),
    )
