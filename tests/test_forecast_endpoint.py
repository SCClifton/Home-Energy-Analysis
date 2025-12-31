"""
Tests for /api/forecast endpoint.
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Add repo root to sys.path so we can import dashboard_app
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from home_energy_analysis.storage import sqlite_cache


def parse_iso_z(ts: str) -> datetime:
    """Parse ISO8601 timestamp with trailing 'Z' to datetime."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


@pytest.fixture
def temp_db():
    """Create a temporary SQLite database for testing."""
    fd, db_path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    
    # Initialize the database
    sqlite_cache.init_db(db_path)
    
    yield db_path
    
    # Cleanup
    if os.path.exists(db_path):
        os.remove(db_path)


@pytest.fixture
def test_app(temp_db, monkeypatch):
    """Create a Flask test app with temporary database."""
    # Set environment variables
    monkeypatch.setenv("AMBER_SITE_ID", "test_site")
    monkeypatch.setenv("SQLITE_PATH", temp_db)
    
    # Reset cache path to ensure we use the test database
    from dashboard_app.app.main import create_app, _reset_cache_path
    import home_energy_analysis.storage.factory as factory_module
    
    # Reset both caches
    _reset_cache_path()
    factory_module._db_path = None
    factory_module._initialized = False
    
    app = create_app()
    app.config['TESTING'] = True
    return app.test_client()


def test_forecast_returns_cached_data(test_app, temp_db):
    """Test that forecast returns cached data even without credentials."""
    site_id = "test_site"
    channel_type = "general"
    
    # Create future intervals
    now_utc = datetime.now(timezone.utc)
    future_intervals = []
    for i in range(1, 5):
        interval_start = (now_utc + timedelta(minutes=5 * i)).isoformat().replace("+00:00", "Z")
        interval_end = (now_utc + timedelta(minutes=5 * (i + 1))).isoformat().replace("+00:00", "Z")
        future_intervals.append({
            "site_id": site_id,
            "interval_start": interval_start,
            "interval_end": interval_end,
            "channel_type": channel_type,
            "per_kwh": 20.0 + i * 5,
            "renewables": 50.0,
            "descriptor": "forecast"
        })
    
    sqlite_cache.upsert_prices(temp_db, future_intervals)
    
    # Call API without credentials
    response = test_app.get("/api/forecast")
    assert response.status_code == 200
    
    data = response.get_json()
    assert "intervals" in data
    assert len(data["intervals"]) > 0
    assert data["intervals"][0]["per_kwh"] == 25.0  # First future interval


def test_forecast_returns_empty_when_no_data(test_app, temp_db):
    """Test that forecast returns empty list when no data exists."""
    response = test_app.get("/api/forecast")
    assert response.status_code == 200
    
    data = response.get_json()
    assert "intervals" in data
    assert len(data["intervals"]) == 0
    assert "message" in data


def test_forecast_filters_future_intervals(test_app, temp_db):
    """Test that forecast only returns future intervals."""
    site_id = "test_site"
    channel_type = "general"
    
    now_utc = datetime.now(timezone.utc)
    
    # Mix of past and future intervals
    intervals = [
        {
            "site_id": site_id,
            "interval_start": (now_utc - timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
            "interval_end": (now_utc - timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
            "channel_type": channel_type,
            "per_kwh": 15.0
        },
        {
            "site_id": site_id,
            "interval_start": (now_utc + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
            "interval_end": (now_utc + timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
            "channel_type": channel_type,
            "per_kwh": 25.0
        }
    ]
    
    sqlite_cache.upsert_prices(temp_db, intervals)
    
    response = test_app.get("/api/forecast")
    assert response.status_code == 200
    
    data = response.get_json()
    assert len(data["intervals"]) == 1
    assert data["intervals"][0]["per_kwh"] == 25.0


def test_forecast_respects_hours_parameter(test_app, temp_db):
    """Test that forecast respects the hours parameter."""
    site_id = "test_site"
    channel_type = "general"
    
    # Create many future intervals
    now_utc = datetime.now(timezone.utc)
    intervals = []
    for i in range(1, 50):  # More than 2 hours worth
        interval_start = (now_utc + timedelta(minutes=5 * i)).isoformat().replace("+00:00", "Z")
        interval_end = (now_utc + timedelta(minutes=5 * (i + 1))).isoformat().replace("+00:00", "Z")
        intervals.append({
            "site_id": site_id,
            "interval_start": interval_start,
            "interval_end": interval_end,
            "channel_type": channel_type,
            "per_kwh": 20.0
        })
    
    sqlite_cache.upsert_prices(temp_db, intervals)
    
    # Request 1 hour (12 intervals)
    response = test_app.get("/api/forecast?hours=1")
    assert response.status_code == 200
    
    data = response.get_json()
    # Should return up to 12 intervals
    assert len(data["intervals"]) <= 12

