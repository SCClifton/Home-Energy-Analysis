"""
Tests for /api/health endpoint (negative price_age_seconds fix).
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


def test_health_chooses_past_interval_over_future(test_app, temp_db):
    """Test that /api/health chooses past interval and price_age_seconds >= 0."""
    site_id = "test_site"
    channel_type = "general"
    
    now_utc = datetime.now(timezone.utc)
    
    # Create a past price interval (10 minutes ago)
    past_interval_start = (now_utc - timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
    past_interval_end = (now_utc - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    
    # Create a future price interval (10 minutes in the future) - like forecast data
    future_interval_start = (now_utc + timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
    future_interval_end = (now_utc + timedelta(minutes=15)).isoformat().replace("+00:00", "Z")
    
    price_rows = [
        {
            "site_id": site_id,
            "interval_start": past_interval_start,
            "interval_end": past_interval_end,
            "channel_type": channel_type,
            "per_kwh": 25.0,
            "renewables": 50.0
        },
        {
            "site_id": site_id,
            "interval_start": future_interval_start,
            "interval_end": future_interval_end,
            "channel_type": channel_type,
            "per_kwh": 30.0,
            "renewables": 60.0
        }
    ]
    
    sqlite_cache.upsert_prices(temp_db, price_rows)
    
    # Call /api/health
    response = test_app.get("/api/health")
    assert response.status_code == 200
    
    data = response.get_json()
    
    # Should choose the past interval
    assert data["latest_price_interval_start"] == past_interval_start
    assert data["price_age_seconds"] is not None
    assert data["price_age_seconds"] >= 0  # Should not be negative
    assert data["price_age_seconds"] >= 300  # At least 5 minutes old (10 min ago - 5 min end = 5 min)
    
    # Should not choose the future interval
    assert data["latest_price_interval_start"] != future_interval_start


def test_health_returns_null_when_only_future_intervals(test_app, temp_db):
    """Test that /api/health returns null when only future intervals exist."""
    site_id = "test_site"
    channel_type = "general"
    
    now_utc = datetime.now(timezone.utc)
    
    # Create only future intervals
    future_interval_start = (now_utc + timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
    future_interval_end = (now_utc + timedelta(minutes=15)).isoformat().replace("+00:00", "Z")
    
    price_rows = [
        {
            "site_id": site_id,
            "interval_start": future_interval_start,
            "interval_end": future_interval_end,
            "channel_type": channel_type,
            "per_kwh": 30.0,
            "renewables": 60.0
        }
    ]
    
    sqlite_cache.upsert_prices(temp_db, price_rows)
    
    # Call /api/health
    response = test_app.get("/api/health")
    assert response.status_code == 200
    
    data = response.get_json()
    
    # Should return null for price data since no past intervals exist
    assert data["latest_price_interval_start"] is None
    assert data["price_age_seconds"] is None

