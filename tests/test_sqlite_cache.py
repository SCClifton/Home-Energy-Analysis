"""
Tests for SQLite cache module.
"""
import os
import tempfile
import pytest
from datetime import datetime, timedelta, timezone

from home_energy_analysis.storage import sqlite_cache


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


def test_init_db_creates_tables(temp_db):
    """Test that init_db creates the required tables."""
    import sqlite3
    
    conn = sqlite3.connect(temp_db)
    cursor = conn.cursor()
    
    # Check that tables exist
    cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name IN ('prices', 'usage')
    """)
    tables = [row[0] for row in cursor.fetchall()]
    
    conn.close()
    
    assert "prices" in tables
    assert "usage" in tables


def test_upsert_prices_inserts_and_updates(temp_db):
    """Test that upsert_prices inserts new rows and updates existing ones."""
    # Insert initial row
    rows1 = [{
        "site_id": "test_site",
        "interval_start": "2025-01-01T00:00:00Z",
        "interval_end": "2025-01-01T00:30:00Z",
        "channel_type": "general",
        "per_kwh": 10.5,
        "renewables": 50.0,
        "descriptor": "test"
    }]
    sqlite_cache.upsert_prices(temp_db, rows1)
    
    # Verify insertion
    latest = sqlite_cache.get_latest_price(temp_db, "test_site", "general")
    assert latest is not None
    assert latest["per_kwh"] == 10.5
    assert latest["renewables"] == 50.0
    
    # Update with same primary key
    rows2 = [{
        "site_id": "test_site",
        "interval_start": "2025-01-01T00:00:00Z",
        "interval_end": "2025-01-01T00:30:00Z",
        "channel_type": "general",
        "per_kwh": 15.0,
        "renewables": 60.0,
        "descriptor": "updated"
    }]
    sqlite_cache.upsert_prices(temp_db, rows2)
    
    # Verify update
    latest = sqlite_cache.get_latest_price(temp_db, "test_site", "general")
    assert latest is not None
    assert latest["per_kwh"] == 15.0
    assert latest["renewables"] == 60.0
    assert latest["descriptor"] == "updated"


def test_upsert_usage_inserts_and_updates(temp_db):
    """Test that upsert_usage inserts new rows and updates existing ones."""
    # Insert initial row
    rows1 = [{
        "site_id": "test_site",
        "interval_start": "2025-01-01T00:00:00Z",
        "interval_end": "2025-01-01T00:30:00Z",
        "channel_type": "general",
        "kwh": 2.5
    }]
    sqlite_cache.upsert_usage(temp_db, rows1)
    
    # Verify insertion
    latest = sqlite_cache.get_latest_usage(temp_db, "test_site", "general")
    assert latest is not None
    assert latest["kwh"] == 2.5
    
    # Update with same primary key
    rows2 = [{
        "site_id": "test_site",
        "interval_start": "2025-01-01T00:00:00Z",
        "interval_end": "2025-01-01T00:30:00Z",
        "channel_type": "general",
        "kwh": 3.0
    }]
    sqlite_cache.upsert_usage(temp_db, rows2)
    
    # Verify update
    latest = sqlite_cache.get_latest_usage(temp_db, "test_site", "general")
    assert latest is not None
    assert latest["kwh"] == 3.0


def test_get_latest_price_returns_correct_row(temp_db):
    """Test that get_latest_price returns the most recent row."""
    # Insert multiple rows with different timestamps
    rows = [
        {
            "site_id": "test_site",
            "interval_start": "2025-01-01T00:00:00Z",
            "interval_end": "2025-01-01T00:30:00Z",
            "channel_type": "general",
            "per_kwh": 10.0
        },
        {
            "site_id": "test_site",
            "interval_start": "2025-01-01T00:30:00Z",
            "interval_end": "2025-01-01T01:00:00Z",
            "channel_type": "general",
            "per_kwh": 20.0
        },
        {
            "site_id": "test_site",
            "interval_start": "2025-01-01T01:00:00Z",
            "interval_end": "2025-01-01T01:30:00Z",
            "channel_type": "general",
            "per_kwh": 30.0
        }
    ]
    sqlite_cache.upsert_prices(temp_db, rows)
    
    # Get latest should return the most recent (30.0)
    latest = sqlite_cache.get_latest_price(temp_db, "test_site", "general")
    assert latest is not None
    assert latest["per_kwh"] == 30.0
    assert latest["interval_start"] == "2025-01-01T01:00:00Z"


def test_get_latest_usage_returns_correct_row(temp_db):
    """Test that get_latest_usage returns the most recent row."""
    # Insert multiple rows with different timestamps
    rows = [
        {
            "site_id": "test_site",
            "interval_start": "2025-01-01T00:00:00Z",
            "interval_end": "2025-01-01T00:30:00Z",
            "channel_type": "general",
            "kwh": 1.0
        },
        {
            "site_id": "test_site",
            "interval_start": "2025-01-01T00:30:00Z",
            "interval_end": "2025-01-01T01:00:00Z",
            "channel_type": "general",
            "kwh": 2.0
        },
        {
            "site_id": "test_site",
            "interval_start": "2025-01-01T01:00:00Z",
            "interval_end": "2025-01-01T01:30:00Z",
            "channel_type": "general",
            "kwh": 3.0
        }
    ]
    sqlite_cache.upsert_usage(temp_db, rows)
    
    # Get latest should return the most recent (3.0)
    latest = sqlite_cache.get_latest_usage(temp_db, "test_site", "general")
    assert latest is not None
    assert latest["kwh"] == 3.0
    assert latest["interval_start"] == "2025-01-01T01:00:00Z"


def test_get_latest_returns_none_when_no_data(temp_db):
    """Test that get_latest functions return None when no data exists."""
    latest_price = sqlite_cache.get_latest_price(temp_db, "nonexistent", "general")
    assert latest_price is None
    
    latest_usage = sqlite_cache.get_latest_usage(temp_db, "nonexistent", "general")
    assert latest_usage is None


def test_prune_old_data_removes_old_rows(temp_db):
    """Test that prune_old_data removes rows older than retention period."""
    now = datetime.now(timezone.utc)
    
    # Insert old data (31 days ago)
    old_dt = now - timedelta(days=31)
    old_date = old_dt.isoformat().replace("+00:00", "Z")
    old_end_dt = old_dt + timedelta(minutes=30)
    old_end_date = old_end_dt.isoformat().replace("+00:00", "Z")
    old_rows = [{
        "site_id": "test_site",
        "interval_start": old_date,
        "interval_end": old_end_date,
        "channel_type": "general",
        "per_kwh": 10.0
    }]
    sqlite_cache.upsert_prices(temp_db, old_rows)
    
    # Insert recent data (5 days ago)
    recent_dt = now - timedelta(days=5)
    recent_date = recent_dt.isoformat().replace("+00:00", "Z")
    recent_end_dt = recent_dt + timedelta(minutes=30)
    recent_end_date = recent_end_dt.isoformat().replace("+00:00", "Z")
    recent_rows = [{
        "site_id": "test_site",
        "interval_start": recent_date,
        "interval_end": recent_end_date,
        "channel_type": "general",
        "per_kwh": 20.0
    }]
    sqlite_cache.upsert_prices(temp_db, recent_rows)
    
    # Insert old usage data
    old_usage = [{
        "site_id": "test_site",
        "interval_start": old_date,
        "interval_end": old_end_date,
        "channel_type": "general",
        "kwh": 1.0
    }]
    sqlite_cache.upsert_usage(temp_db, old_usage)
    
    # Prune data older than 30 days
    deleted_count = sqlite_cache.prune_old_data(temp_db, retention_days=30)
    
    # Should have deleted old price and old usage (2 rows)
    assert deleted_count == 2
    
    # Recent data should still exist
    latest = sqlite_cache.get_latest_price(temp_db, "test_site", "general")
    assert latest is not None
    assert latest["per_kwh"] == 20.0
    
    # Old data should be gone
    old_latest = sqlite_cache.get_latest_price(temp_db, "test_site", "general")
    # The old one should be gone, only recent one remains
    assert old_latest["interval_start"] == recent_date


def test_get_price_for_interval_returns_correct_row(temp_db):
    """Test that get_price_for_interval returns the correct price for a specific interval."""
    site_id = "site123"
    channel_type = "general"
    interval_start_1 = "2025-12-28T04:50:00Z"
    interval_end_1 = "2025-12-28T04:55:00Z"
    interval_start_2 = "2025-12-28T04:55:00Z"
    interval_end_2 = "2025-12-28T05:00:00Z"
    
    # Insert two price rows with different interval_start
    rows = [
        {
            "site_id": site_id,
            "interval_start": interval_start_1,
            "interval_end": interval_end_1,
            "channel_type": channel_type,
            "per_kwh": 10.5,
            "renewables": 50.0
        },
        {
            "site_id": site_id,
            "interval_start": interval_start_2,
            "interval_end": interval_end_2,
            "channel_type": channel_type,
            "per_kwh": 15.0,
            "renewables": 60.0
        }
    ]
    sqlite_cache.upsert_prices(temp_db, rows)
    
    # Get price for first interval
    result_1 = sqlite_cache.get_price_for_interval(temp_db, site_id, interval_start_1, channel_type)
    assert result_1 is not None
    assert result_1["interval_start"] == interval_start_1
    assert result_1["per_kwh"] == 10.5
    assert result_1["renewables"] == 50.0
    
    # Get price for second interval
    result_2 = sqlite_cache.get_price_for_interval(temp_db, site_id, interval_start_2, channel_type)
    assert result_2 is not None
    assert result_2["interval_start"] == interval_start_2
    assert result_2["per_kwh"] == 15.0
    assert result_2["renewables"] == 60.0
    
    # Get price for non-existent interval
    result_none = sqlite_cache.get_price_for_interval(temp_db, site_id, "2025-12-28T05:00:00Z", channel_type)
    assert result_none is None


def test_get_usage_for_interval_returns_correct_row(temp_db):
    """Test that get_usage_for_interval returns the correct usage for a specific interval."""
    site_id = "site123"
    channel_type = "general"
    interval_start_1 = "2025-12-28T04:50:00Z"
    interval_end_1 = "2025-12-28T04:55:00Z"
    interval_start_2 = "2025-12-28T04:55:00Z"
    interval_end_2 = "2025-12-28T05:00:00Z"
    
    # Insert two usage rows with different interval_start
    rows = [
        {
            "site_id": site_id,
            "interval_start": interval_start_1,
            "interval_end": interval_end_1,
            "channel_type": channel_type,
            "kwh": 2.5
        },
        {
            "site_id": site_id,
            "interval_start": interval_start_2,
            "interval_end": interval_end_2,
            "channel_type": channel_type,
            "kwh": 3.0
        }
    ]
    sqlite_cache.upsert_usage(temp_db, rows)
    
    # Get usage for first interval
    result_1 = sqlite_cache.get_usage_for_interval(temp_db, site_id, interval_start_1, channel_type)
    assert result_1 is not None
    assert result_1["interval_start"] == interval_start_1
    assert result_1["kwh"] == 2.5
    
    # Get usage for second interval
    result_2 = sqlite_cache.get_usage_for_interval(temp_db, site_id, interval_start_2, channel_type)
    assert result_2 is not None
    assert result_2["interval_start"] == interval_start_2
    assert result_2["kwh"] == 3.0
    
    # Get usage for non-existent interval
    result_none = sqlite_cache.get_usage_for_interval(temp_db, site_id, "2025-12-28T05:00:00Z", channel_type)
    assert result_none is None


def test_get_price_for_interval_legacy_timestamp_support(temp_db):
    """Test that get_price_for_interval can read legacy :01Z timestamps when querying for :00Z."""
    site_id = "site123"
    channel_type = "general"
    
    # Insert a row with legacy :01Z timestamp (legacy pattern)
    legacy_interval_start = "2025-12-29T09:40:01Z"
    legacy_interval_end = "2025-12-29T09:45:01Z"
    
    rows = [{
        "site_id": site_id,
        "interval_start": legacy_interval_start,
        "interval_end": legacy_interval_end,
        "channel_type": channel_type,
        "per_kwh": 25.5,
        "renewables": 75.0
    }]
    sqlite_cache.upsert_prices(temp_db, rows)
    
    # Query for normalized :00Z timestamp - should find the legacy :01Z row
    normalized_interval_start = "2025-12-29T09:40:00Z"
    result = sqlite_cache.get_price_for_interval(temp_db, site_id, normalized_interval_start, channel_type)
    
    assert result is not None
    assert result["interval_start"] == legacy_interval_start  # Returns the stored :01Z value
    assert result["per_kwh"] == 25.5
    assert result["renewables"] == 75.0
    
    # Also test that exact :00Z match is preferred if both exist
    # Insert a normalized :00Z row for the same interval
    normalized_rows = [{
        "site_id": site_id,
        "interval_start": normalized_interval_start,
        "interval_end": "2025-12-29T09:45:00Z",
        "channel_type": channel_type,
        "per_kwh": 30.0,
        "renewables": 80.0
    }]
    sqlite_cache.upsert_prices(temp_db, normalized_rows)
    
    # Query should return the :00Z row (exact match preferred)
    result2 = sqlite_cache.get_price_for_interval(temp_db, site_id, normalized_interval_start, channel_type)
    assert result2 is not None
    assert result2["interval_start"] == normalized_interval_start  # Returns :00Z, not :01Z
    assert result2["per_kwh"] == 30.0

