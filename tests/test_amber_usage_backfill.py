"""Tests for Amber usage backfill retry and rate-limit helpers."""

from datetime import datetime, timezone
from email.utils import format_datetime

from home_energy_analysis.ingestion import AmberAPIError
from scripts import backfill_amber_usage_to_supabase as backfill


class FakeAmberClient:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def get_usage_range(self, site_id, window_start, window_end, resolution=None):
        self.calls.append((site_id, window_start, window_end, resolution))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _rate_limit_error(retry_after=None):
    headers = {}
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return AmberAPIError(
        "rate limited",
        status_code=429,
        response_text="Too many requests",
        response_headers=headers,
    )


def test_parse_retry_after_seconds():
    assert backfill.parse_retry_after("7") == 7.0
    assert backfill.parse_retry_after("0") == 0.0


def test_parse_retry_after_http_date():
    now = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    retry_at = datetime(2026, 1, 1, 0, 1, 30, tzinfo=timezone.utc)

    assert backfill.parse_retry_after(format_datetime(retry_at), now=now) == 90.0


def test_fetch_usage_respects_retry_after_seconds():
    sleeps = []
    client = FakeAmberClient([
        _rate_limit_error("7"),
        [{"startTime": "2026-01-01T00:00:00Z", "kwh": 1.0}],
    ])

    rows = backfill.fetch_usage_with_retry(
        client,
        "site",
        datetime(2026, 1, 1).date(),
        datetime(2026, 1, 1).date(),
        backoff_config=backfill.BackoffConfig(max_retries=2, jitter_seconds=0),
        sleep_fn=sleeps.append,
    )

    assert rows == [{"startTime": "2026-01-01T00:00:00Z", "kwh": 1.0}]
    assert sleeps == [7.0]
    assert len(client.calls) == 2


def test_fetch_usage_uses_fallback_backoff_without_retry_after():
    sleeps = []
    client = FakeAmberClient([
        AmberAPIError("temporary", status_code=500),
        [{"startTime": "2026-01-01T00:00:00Z", "kwh": 1.0}],
    ])

    rows = backfill.fetch_usage_with_retry(
        client,
        "site",
        datetime(2026, 1, 1).date(),
        datetime(2026, 1, 1).date(),
        backoff_config=backfill.BackoffConfig(
            max_retries=2,
            base_backoff_seconds=2.0,
            max_backoff_seconds=10.0,
            jitter_seconds=0,
        ),
        sleep_fn=sleeps.append,
    )

    assert rows
    assert sleeps == [2.0]


def test_chunk_size_reduces_on_rate_limit_and_restores_after_success():
    assert backfill.reduced_chunk_days(active_chunk_days=7, min_chunk_days=1) == 3
    assert backfill.reduced_chunk_days(active_chunk_days=3, min_chunk_days=1) == 1
    assert backfill.reduced_chunk_days(active_chunk_days=1, min_chunk_days=1) == 1

    assert backfill.restored_chunk_days(active_chunk_days=1, target_chunk_days=7) == 2
    assert backfill.restored_chunk_days(active_chunk_days=2, target_chunk_days=7) == 4
    assert backfill.restored_chunk_days(active_chunk_days=4, target_chunk_days=7) == 7
