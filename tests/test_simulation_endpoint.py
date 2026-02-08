"""Integration tests for simulation API endpoints."""

import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from home_energy_analysis.storage import sqlite_cache


def floor_to_5min(dt: datetime) -> datetime:
    floored_minute = (dt.minute // 5) * 5
    return dt.replace(minute=floored_minute, second=0, microsecond=0)


def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@pytest.fixture
def temp_db():
    fd, db_path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    sqlite_cache.init_db(db_path)
    yield db_path
    if os.path.exists(db_path):
        os.remove(db_path)


@pytest.fixture
def test_app(temp_db, monkeypatch):
    monkeypatch.setenv("AMBER_SITE_ID", "test_site")
    monkeypatch.setenv("SQLITE_PATH", temp_db)

    from dashboard_app.app.main import create_app, _reset_cache_path
    import home_energy_analysis.storage.factory as factory_module

    _reset_cache_path()
    factory_module._db_path = None
    factory_module._initialized = False

    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_simulation_status_and_intervals_endpoints(test_app, temp_db):
    scenario_id = "house_twin_10kw_10kwh"
    controller = "optimizer"
    now_utc = floor_to_5min(datetime.now(timezone.utc))

    sqlite_cache.upsert_simulation_run(
        temp_db,
        {
            "scenario_id": scenario_id,
            "controller_mode": controller,
            "run_mode": "live",
            "as_of": iso_z(now_utc),
            "window_start": iso_z(now_utc - timedelta(hours=1)),
            "window_end": iso_z(now_utc + timedelta(hours=24)),
            "today_savings_aud": 3.21,
            "mtd_savings_aud": 18.4,
            "next_24h_projected_savings_aud": 4.5,
            "current_battery_soc_kwh": 6.3,
            "today_solar_generation_kwh": 12.7,
            "today_export_revenue_aud": 1.15,
            "stale": False,
            "stale_reason": None,
            "assumptions_json": {"battery_kwh": 10, "pv_kw": 10},
        },
    )

    rows = []
    for idx in range(-6, 6):
        interval_start = now_utc + timedelta(minutes=5 * idx)
        interval_end = interval_start + timedelta(minutes=5)
        rows.append(
            {
                "scenario_id": scenario_id,
                "controller_mode": controller,
                "interval_start": iso_z(interval_start),
                "interval_end": iso_z(interval_end),
                "baseline_import_kwh": 0.5,
                "scenario_import_kwh": 0.3,
                "battery_charge_kwh": 0.1,
                "battery_discharge_kwh": 0.2,
                "battery_soc_kwh": 6.0,
                "pv_generation_kwh": 0.15,
                "export_kwh": 0.05,
                "baseline_cost_aud": 0.18,
                "scenario_cost_aud": 0.10,
                "savings_aud": 0.08,
                "forecast": interval_start > now_utc,
            }
        )
    sqlite_cache.upsert_simulation_intervals(temp_db, rows)

    status_response = test_app.get("/api/simulation/status")
    assert status_response.status_code == 200

    status_data = status_response.get_json()
    assert status_data["status"] == "ok"
    assert status_data["today_savings_aud"] == 3.21
    assert status_data["month_to_date_savings_aud"] == 18.4
    assert status_data["current_battery_soc_kwh"] == 6.3
    assert status_data["as_of"] == iso_z(now_utc)

    intervals_response = test_app.get("/api/simulation/intervals?window=today")
    assert intervals_response.status_code == 200

    intervals_data = intervals_response.get_json()
    assert intervals_data["scenario_id"] == scenario_id
    assert intervals_data["controller_mode"] == controller
    assert isinstance(intervals_data["intervals"], list)
    assert len(intervals_data["intervals"]) >= 1
