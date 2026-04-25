"""Integration tests for cache-backed annual analysis API endpoints."""

import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from home_energy_analysis.storage import sqlite_cache


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


def test_analysis_endpoints_return_cached_payload(test_app, temp_db):
    now = datetime.now(timezone.utc)
    scenario = {
        "scenario_id": "analysis_pv_8p0kw_battery_10p0kwh_base",
        "dispatch_mode": "base",
        "solar_kw": 8.0,
        "battery_kwh": 10.0,
        "year1_saving_aud": 1914.0,
        "installed_cost_after_rebates_aud": 17755.0,
        "payback_years": 9.6,
        "grid_import_reduction_pct": 70.0,
        "lifetime_net_benefit_aud": 10500.0,
        "effective_rate_c_per_kwh": 31.2,
        "cashflow": [],
        "monthly_energy_mix": [],
    }
    sqlite_cache.upsert_analysis_run(
        temp_db,
        {
            "analysis_id": "solar_battery_efficiency",
            "year": 2025,
            "generated_at": iso_z(now),
            "window_start": "2024-12-31T13:00:00Z",
            "window_end": "2025-12-31T13:00:00Z",
            "data_quality": {"ready": True, "checks": {"usage": {"coverage_pct": 99.0}}, "warnings": []},
            "scenarios": [scenario],
            "recommendations": {"lowest_cost": scenario, "fastest_payback": scenario, "self_sufficiency": scenario, "sensitivity": []},
            "load_shift": {"status": "ok", "opportunities": [{"title": "Shift load"}], "metrics": {}, "worst_days": []},
            "assumptions": {"irradiance_source": "Open-Meteo modelled historical irradiance"},
        },
    )

    scenarios_response = test_app.get("/api/analysis/scenarios?year=2025")
    assert scenarios_response.status_code == 200
    scenarios_data = scenarios_response.get_json()
    assert scenarios_data["status"] == "ok"
    assert scenarios_data["scenarios"][0]["solar_kw"] == 8.0

    rec_response = test_app.get("/api/analysis/recommendation?year=2025&goal=lowest_cost")
    assert rec_response.status_code == 200
    rec_data = rec_response.get_json()
    assert rec_data["recommendation"]["battery_kwh"] == 10.0

    load_response = test_app.get("/api/analysis/load-shift?year=2025")
    assert load_response.status_code == 200
    assert load_response.get_json()["load_shift"]["opportunities"][0]["title"] == "Shift load"

    quality_response = test_app.get("/api/analysis/data-quality?year=2025")
    assert quality_response.status_code == 200
    assert quality_response.get_json()["data_quality"]["ready"] is True


def test_analysis_endpoints_missing_payload_is_stable(test_app):
    response = test_app.get("/api/analysis/recommendation?year=2025")
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "missing"
    assert data["recommendation"] is None
