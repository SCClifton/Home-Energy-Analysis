"""Tests for SQLite-to-Supabase sync helpers."""

from datetime import datetime, timezone

from home_energy_analysis.storage import sqlite_cache
from scripts import sync_sqlite_to_supabase as syncer


def test_load_sqlite_rows_maps_to_supabase_shape(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    site_id = "site"
    sqlite_cache.init_db(str(db_path))
    sqlite_cache.upsert_prices(
        str(db_path),
        [
            {
                "site_id": site_id,
                "interval_start": "2026-04-24T00:00:00Z",
                "interval_end": "2026-04-24T00:05:00Z",
                "channel_type": "general",
                "per_kwh": 31.2,
                "renewables": 78.0,
                "descriptor": "neutral",
            }
        ],
    )
    sqlite_cache.upsert_usage(
        str(db_path),
        [
            {
                "site_id": site_id,
                "interval_start": "2026-04-24T00:00:00Z",
                "interval_end": "2026-04-24T00:05:00Z",
                "channel_type": "general",
                "kwh": 0.12,
                "cost_aud": 0.03,
                "quality": "billable",
                "channel_identifier": "E1",
            }
        ],
    )

    start = datetime(2026, 4, 24, tzinfo=timezone.utc)
    end = datetime(2026, 4, 25, tzinfo=timezone.utc)
    prices = syncer.load_sqlite_price_rows(db_path, site_id, start, end, "sqlite-cache")
    usage = syncer.load_sqlite_usage_rows(db_path, site_id, start, end, "sqlite-cache", "general")

    assert prices[0]["price_cents_per_kwh"] == 31.2
    assert prices[0]["renewables_percent"] == 78.0
    assert prices[0]["source"] == "sqlite-cache"
    assert usage[0]["kwh"] == 0.12
    assert usage[0]["meter_identifier"] == "E1"
    assert usage[0]["source"] == "sqlite-cache"
