"""Scenario simulation configuration and defaults."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from math import sqrt
from typing import Any, Dict


@dataclass(frozen=True)
class PVConfig:
    """Configuration for PV generation modelling."""

    capacity_kw: float = 10.0
    performance_ratio: float = 0.82
    temperature_coefficient_per_c: float = -0.004
    reference_temperature_c: float = 25.0


@dataclass(frozen=True)
class BatteryConfig:
    """Configuration for battery dispatch and SoC modelling."""

    capacity_kwh: float = 10.0
    min_soc_kwh: float = 1.0
    initial_soc_kwh: float = 5.0
    max_charge_kw: float = 5.0
    max_discharge_kw: float = 5.0
    max_export_kw: float = 5.0
    round_trip_efficiency: float = 0.90
    degradation_cost_aud_per_kwh: float = 0.02
    allow_grid_charge: bool = True

    @property
    def charge_efficiency(self) -> float:
        return sqrt(self.round_trip_efficiency)

    @property
    def discharge_efficiency(self) -> float:
        return sqrt(self.round_trip_efficiency)


@dataclass(frozen=True)
class DispatchConfig:
    """Controller threshold configuration."""

    rule_discharge_price_aud_per_kwh: float = 0.20
    rule_charge_price_aud_per_kwh: float = 0.08
    optimizer_spread_trigger_aud_per_kwh: float = 0.08
    optimizer_lookahead_intervals: int = 288
    export_arbitrage_price_aud_per_kwh: float = 0.28


@dataclass(frozen=True)
class ScenarioConfig:
    """Top-level scenario config."""

    scenario_id: str = "house_twin_10kw_10kwh"
    timezone_display: str = "Australia/Sydney"
    pv: PVConfig = PVConfig()
    battery: BatteryConfig = BatteryConfig()
    dispatch: DispatchConfig = DispatchConfig()

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["assumptions"] = {
            "pv_system": "10 kW rooftop system with PR=0.82 and temperature derating",
            "battery": "10 kWh battery, 5 kW charge/discharge, 10% reserve, 90% round-trip efficiency",
            "tariff": "Uses Amber interval wholesale price for both import and export valuation",
        }
        return data


def default_config() -> ScenarioConfig:
    """Build the default simulation config."""
    return ScenarioConfig()
