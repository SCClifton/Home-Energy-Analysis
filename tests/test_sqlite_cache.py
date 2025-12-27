"""
Tests for SQLite cache module.
"""
import os
import tempfile
import pytest
from datetime import datetime, timedelta, timezone
from src.storage import sqlite_cache


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

