"""Tests for Powerpal minute CSV loader helpers."""

from datetime import timezone
from pathlib import Path

import pandas as pd

from scripts import load_powerpal_minute_to_supabase as loader


def test_build_usage_intervals_uses_utc_timestamp_and_watt_hours():
    df = pd.DataFrame({
        "datetime_utc": ["2025-01-04 00:00:00"],
        "datetime_local": ["2025-01-04 11:00:00"],
        "watt_hours": [6.0],
        "cost_dollars": [0.01],
    })

    rows, na_count, parse_mode = loader.build_usage_intervals(
        df,
        "datetime_utc",
        "watt_hours",
        site_id="site",
        channel_type="general",
        source="powerpal",
        raw_event_id="dry-run",
    )

    assert na_count == 0
    assert "UTC directly" in parse_mode
    assert rows[0]["interval_start"].tzinfo == timezone.utc
    assert rows[0]["interval_start"].isoformat() == "2025-01-04T00:00:00+00:00"
    assert rows[0]["kwh"] == 0.006
    assert rows[0]["cost_aud"] is None


def test_manifest_dry_run_skips_header_only_csv(tmp_path, capsys):
    csv_path = tmp_path / "empty.csv"
    csv_path.write_text("datetime_utc,datetime_local,watt_hours,cost_dollars,is_peak\n")
    manifest_path = tmp_path / "manifest.csv"
    manifest_path.write_text(
        "file,start_date,end_date,start_epoch,end_epoch,downloaded_at_utc,sha256,http_status,bytes\n"
        f"{csv_path},2024-10-01,2024-12-29,0,0,2026-01-01T00:00:00Z,abc,200,60\n"
    )

    result = loader.main(["--manifest", str(manifest_path), "--dry-run"])

    captured = capsys.readouterr()
    assert result == 0
    assert "Empty/header-only CSV: skipped" in captured.out
    assert "Dry run complete; no Supabase writes were attempted." in captured.out


def test_dry_run_does_not_call_supabase(tmp_path, monkeypatch):
    csv_path = tmp_path / "usage.csv"
    csv_path.write_text(
        "datetime_utc,datetime_local,watt_hours,cost_dollars,is_peak\n"
        "2025-01-04 00:00:00,2025-01-04 11:00:00,6.0,0.01,false\n"
    )

    def fail_if_called(*args, **kwargs):
        raise AssertionError("Supabase should not be called during dry run")

    monkeypatch.setattr(loader.supabase_db, "insert_ingest_event", fail_if_called)
    monkeypatch.setattr(loader.supabase_db, "upsert_usage_intervals", fail_if_called)

    assert loader.main(["--csv", str(csv_path), "--dry-run"]) == 0


def test_summarize_intervals_detects_duplicates_and_gaps():
    df = pd.DataFrame({
        "datetime_utc": [
            "2025-01-04 00:00:00",
            "2025-01-04 00:00:00",
            "2025-01-04 00:03:00",
        ],
        "watt_hours": [1.0, 2.0, 3.0],
    })
    rows, na_count, parse_mode = loader.build_usage_intervals(
        df, "datetime_utc", "watt_hours", "site", "general", "powerpal", "dry-run"
    )

    summary = loader.summarize_intervals(Path("x.csv"), len(df), rows, na_count, parse_mode)

    assert summary.valid_intervals == 3
    assert summary.duplicate_intervals == 1
    assert summary.gap_count == 1
    assert summary.missing_minutes == 2
