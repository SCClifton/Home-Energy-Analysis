"""
Tests for /api/price endpoint (live-first with fallback).
"""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

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


def test_price_fallback_to_cache_on_live_failure(test_app, temp_db, monkeypatch):
    """Test that price falls back to cache when live API fails."""
    site_id = "test_site"
    channel_type = "general"
    
    # Set up credentials
    monkeypatch.setenv("AMBER_TOKEN", "test_token")
    
    # Create cached price
    now_utc = datetime.now(timezone.utc)
    current_interval_start = now_utc.replace(second=0, microsecond=0)
    # Floor to 5-minute boundary
    floored_minute = (current_interval_start.minute // 5) * 5
    current_interval_start = current_interval_start.replace(minute=floored_minute)
    current_interval_start_str = current_interval_start.isoformat().replace("+00:00", "Z")
    current_interval_end = (current_interval_start + timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    
    cached_price = {
        "site_id": site_id,
        "interval_start": current_interval_start_str,
        "interval_end": current_interval_end,
        "channel_type": channel_type,
        "per_kwh": 25.0,
        "renewables": 50.0
    }
    sqlite_cache.upsert_prices(temp_db, [cached_price])
    
    # Mock AmberClient to raise an exception
    with patch('dashboard_app.app.main.AmberClient') as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.get_prices_current.side_effect = Exception("API Error")
        
        # Call API
        response = test_app.get("/api/price")
        assert response.status_code == 200
        
        data = response.get_json()
        assert data["per_kwh"] == 25.0
        assert response.headers["X-Data-Source"] == "cache"


def test_price_uses_cache_when_no_credentials(test_app, temp_db):
    """Test that price uses cache when no credentials are available."""
    site_id = "test_site"
    channel_type = "general"
    
    # Create cached price
    now_utc = datetime.now(timezone.utc)
    current_interval_start = now_utc.replace(second=0, microsecond=0)
    floored_minute = (current_interval_start.minute // 5) * 5
    current_interval_start = current_interval_start.replace(minute=floored_minute)
    current_interval_start_str = current_interval_start.isoformat().replace("+00:00", "Z")
    current_interval_end = (current_interval_start + timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    
    cached_price = {
        "site_id": site_id,
        "interval_start": current_interval_start_str,
        "interval_end": current_interval_end,
        "channel_type": channel_type,
        "per_kwh": 30.0,
        "renewables": 60.0
    }
    sqlite_cache.upsert_prices(temp_db, [cached_price])
    
    # Call API without credentials
    response = test_app.get("/api/price")
    assert response.status_code == 200
    
    data = response.get_json()
    assert data["per_kwh"] == 30.0
    assert response.headers["X-Data-Source"] == "cache"

