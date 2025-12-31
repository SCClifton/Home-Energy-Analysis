"""
Tests for /api/totals endpoint.
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
    from home_energy_analysis.storage.factory import get_sqlite_cache
    import home_energy_analysis.storage.factory as factory_module
    
    # Reset both caches
    _reset_cache_path()
    factory_module._db_path = None
    factory_module._initialized = False
    
    app = create_app()
    app.config['TESTING'] = True
    return app.test_client()


def test_totals_with_cost_aud(test_app, temp_db):
    """Test that totals correctly calculates month-to-date cost from usage.cost_aud."""
    site_id = "test_site"
    channel_type = "general"
    
    # Get current month start in Sydney timezone
    sydney_tz = ZoneInfo("Australia/Sydney")
    now_sydney = datetime.now(sydney_tz)
    month_start_sydney = now_sydney.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_start_utc = month_start_sydney.astimezone(timezone.utc)
    
    # Create recent test intervals (within last 10 minutes) to ensure they're not delayed
    now_utc = datetime.now(timezone.utc)
    # Ensure intervals are in current month and recent
    if now_utc - month_start_utc < timedelta(minutes=10):
        # If we're very early in the month, use month start + small offset
        interval1_start = (month_start_utc + timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
        interval1_end = (month_start_utc + timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
        interval2_start = (month_start_utc + timedelta(minutes=15)).isoformat().replace("+00:00", "Z")
        interval2_end = (month_start_utc + timedelta(minutes=20)).isoformat().replace("+00:00", "Z")
    else:
        # Use recent timestamps (within last 10 minutes)
        interval1_start = (now_utc - timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
        interval1_end = (now_utc - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
        interval2_start = (now_utc - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
        interval2_end = now_utc.isoformat().replace("+00:00", "Z")
    
    # Insert usage with cost_aud
    usage_rows = [
        {
            "site_id": site_id,
            "interval_start": interval1_start,
            "interval_end": interval1_end,
            "channel_type": channel_type,
            "kwh": 1.5,
            "cost_aud": 0.30,
            "quality": "actual",
            "channel_identifier": "E1"
        },
        {
            "site_id": site_id,
            "interval_start": interval2_start,
            "interval_end": interval2_end,
            "channel_type": channel_type,
            "kwh": 2.0,
            "cost_aud": 0.30,
            "quality": "actual",
            "channel_identifier": "E1"
        }
    ]
    sqlite_cache.upsert_usage(temp_db, usage_rows)
    
    # Call API
    response = test_app.get("/api/totals")
    assert response.status_code == 200
    
    data = response.get_json()
    assert data["month_to_date_cost_aud"] == 0.60  # 0.30 + 0.30
    assert data["intervals_count"] == 2
    assert data["as_of_interval_end"] == interval2_end
    assert data["is_delayed"] is False


def test_totals_with_missing_cost_aud(test_app, temp_db):
    """Test that totals excludes intervals where cost_aud is null."""
    site_id = "test_site"
    channel_type = "general"
    
    # Get current month start
    sydney_tz = ZoneInfo("Australia/Sydney")
    now_sydney = datetime.now(sydney_tz)
    month_start_sydney = now_sydney.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_start_utc = month_start_sydney.astimezone(timezone.utc)
    
    # Create two intervals
    interval1_start = (month_start_utc + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    interval1_end = (month_start_utc + timedelta(hours=1, minutes=5)).isoformat().replace("+00:00", "Z")
    
    interval2_start = (month_start_utc + timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    interval2_end = (month_start_utc + timedelta(hours=2, minutes=5)).isoformat().replace("+00:00", "Z")
    
    # Insert two usage rows - one with cost_aud, one without
    usage_rows = [
        {
            "site_id": site_id,
            "interval_start": interval1_start,
            "interval_end": interval1_end,
            "channel_type": channel_type,
            "kwh": 1.5,
            "cost_aud": 0.30  # Has cost
        },
        {
            "site_id": site_id,
            "interval_start": interval2_start,
            "interval_end": interval2_end,
            "channel_type": channel_type,
            "kwh": 2.0
            # cost_aud is None
        }
    ]
    sqlite_cache.upsert_usage(temp_db, usage_rows)
    
    # Call API
    response = test_app.get("/api/totals")
    assert response.status_code == 200
    
    data = response.get_json()
    assert data["month_to_date_cost_aud"] == 0.30  # Only first interval counted (has cost_aud)
    assert data["intervals_count"] == 1  # Only interval with cost_aud


def test_totals_empty_usage_returns_null(test_app, temp_db):
    """Test that totals returns null and message when no usage data exists."""
    # Call API with empty database
    response = test_app.get("/api/totals")
    assert response.status_code == 200
    
    data = response.get_json()
    assert data["month_to_date_cost_aud"] is None
    assert data["as_of_interval_end"] is None
    assert data["intervals_count"] == 0
    assert data["message"] == "Waiting for usage data"


def test_totals_delayed_flag(test_app, temp_db):
    """Test that is_delayed is set correctly based on usage age."""
    site_id = "test_site"
    channel_type = "general"
    
    # Get current month start
    sydney_tz = ZoneInfo("Australia/Sydney")
    now_sydney = datetime.now(sydney_tz)
    month_start_sydney = now_sydney.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_start_utc = month_start_sydney.astimezone(timezone.utc)
    
    # Create an old interval (more than 30 minutes ago)
    old_interval_start = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    old_interval_end = (datetime.now(timezone.utc) - timedelta(hours=2, minutes=-5)).isoformat().replace("+00:00", "Z")
    
    # Ensure it's in current month
    if parse_iso_z(old_interval_start) < month_start_utc:
        old_interval_start = (month_start_utc + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
        old_interval_end = (month_start_utc + timedelta(hours=1, minutes=5)).isoformat().replace("+00:00", "Z")
    
    # Insert usage with cost_aud
    usage_rows = [{
        "site_id": site_id,
        "interval_start": old_interval_start,
        "interval_end": old_interval_end,
        "channel_type": channel_type,
        "kwh": 1.5,
        "cost_aud": 0.30
    }]
    sqlite_cache.upsert_usage(temp_db, usage_rows)
    
    # Call API
    response = test_app.get("/api/totals")
    assert response.status_code == 200
    
    data = response.get_json()
    # Should be delayed if usage age > 1800 seconds (30 minutes)
    # Since we created it 2 hours ago, it should be delayed
    assert data["is_delayed"] is True
    assert data["usage_age_seconds"] is not None
    assert data["usage_age_seconds"] > 1800


def test_totals_filters_general_channel(test_app, temp_db):
    """Test that totals only includes general channel_type."""
    site_id = "test_site"
    
    # Get current month start
    sydney_tz = ZoneInfo("Australia/Sydney")
    now_sydney = datetime.now(sydney_tz)
    month_start_sydney = now_sydney.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_start_utc = month_start_sydney.astimezone(timezone.utc)
    
    interval1_start = (month_start_utc + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    interval1_end = (month_start_utc + timedelta(hours=1, minutes=5)).isoformat().replace("+00:00", "Z")
    
    interval2_start = (month_start_utc + timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    interval2_end = (month_start_utc + timedelta(hours=2, minutes=5)).isoformat().replace("+00:00", "Z")
    
    # Insert usage with different channel types
    usage_rows = [
        {
            "site_id": site_id,
            "interval_start": interval1_start,
            "interval_end": interval1_end,
            "channel_type": "general",
            "kwh": 1.5,
            "cost_aud": 0.30
        },
        {
            "site_id": site_id,
            "interval_start": interval2_start,
            "interval_end": interval2_end,
            "channel_type": "controlled_load",
            "kwh": 2.0,
            "cost_aud": 0.40
        }
    ]
    sqlite_cache.upsert_usage(temp_db, usage_rows)
    
    # Call API
    response = test_app.get("/api/totals")
    assert response.status_code == 200
    
    data = response.get_json()
    # Should only include general channel
    assert data["month_to_date_cost_aud"] == 0.30
    assert data["intervals_count"] == 1

