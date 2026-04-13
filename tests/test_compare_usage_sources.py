"""Tests for usage source reconciliation helpers."""

from datetime import date, datetime, timezone

import pandas as pd
import pytest

from scripts import compare_usage_sources as compare


def test_local_date_window_uses_sydney_boundaries():
    start_utc, end_utc = compare.local_date_window(date(2025, 1, 4), date(2025, 1, 5))

    assert start_utc == datetime(2025, 1, 3, 13, 0, tzinfo=timezone.utc)
    assert end_utc == datetime(2025, 1, 5, 13, 0, tzinfo=timezone.utc)


def test_aggregate_daily_handles_mixed_interval_lengths():
    rows = [
        {
            "source": "powerpal",
            "interval_start": datetime(2025, 1, 3, 13, 0, tzinfo=timezone.utc),
            "interval_end": datetime(2025, 1, 3, 13, 1, tzinfo=timezone.utc),
            "kwh": 0.1,
        },
        {
            "source": "powerpal",
            "interval_start": datetime(2025, 1, 3, 13, 1, tzinfo=timezone.utc),
            "interval_end": datetime(2025, 1, 3, 13, 2, tzinfo=timezone.utc),
            "kwh": 0.2,
        },
        {
            "source": "amber",
            "interval_start": datetime(2025, 1, 3, 13, 0, tzinfo=timezone.utc),
            "interval_end": datetime(2025, 1, 3, 13, 30, tzinfo=timezone.utc),
            "kwh": 3.0,
        },
    ]

    daily = compare.aggregate_daily(rows, date(2025, 1, 4), date(2025, 1, 4), ["powerpal", "amber"])

    powerpal = daily[daily["source"] == "powerpal"].iloc[0]
    amber = daily[daily["source"] == "amber"].iloc[0]
    assert powerpal["kwh_total"] == pytest.approx(0.3)
    assert powerpal["covered_minutes"] == 2.0
    assert powerpal["missing_coverage_minutes"] == 1438.0
    assert amber["kwh_total"] == 3.0
    assert amber["covered_minutes"] == 30.0
    assert amber["missing_coverage_minutes"] == 1410.0


def test_reconciliation_reports_missing_source_days_and_diff():
    rows = [
        {
            "source": "powerpal",
            "interval_start": datetime(2025, 1, 3, 13, 0, tzinfo=timezone.utc),
            "interval_end": datetime(2025, 1, 3, 13, 1, tzinfo=timezone.utc),
            "kwh": 1.0,
        },
        {
            "source": "amber",
            "interval_start": datetime(2025, 1, 3, 13, 0, tzinfo=timezone.utc),
            "interval_end": datetime(2025, 1, 3, 13, 30, tzinfo=timezone.utc),
            "kwh": 0.8,
        },
        {
            "source": "powerpal",
            "interval_start": datetime(2025, 1, 4, 13, 0, tzinfo=timezone.utc),
            "interval_end": datetime(2025, 1, 4, 13, 1, tzinfo=timezone.utc),
            "kwh": 2.0,
        },
    ]
    daily = compare.aggregate_daily(rows, date(2025, 1, 4), date(2025, 1, 5), ["powerpal", "amber"])

    reconciliation = compare.build_reconciliation(daily, "powerpal", "amber")
    stats = compare.reconciliation_stats(reconciliation, "powerpal", "amber")

    first_day = reconciliation[reconciliation["local_date"] == date(2025, 1, 4)].iloc[0]
    second_day = reconciliation[reconciliation["local_date"] == date(2025, 1, 5)].iloc[0]
    assert first_day["diff_kwh"] == pytest.approx(0.2)
    assert pd.isna(second_day["amber_kwh"])
    assert stats["overlap_days"] == 1
    assert stats["days_missing_amber"] == 1
    assert stats["days_missing_powerpal"] == 0
