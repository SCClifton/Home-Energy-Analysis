"""Tests for Powerpal CSV download helpers."""

from datetime import date

from scripts import pull_powerpal_minute_csv as puller


def test_parse_export_url_extracts_credentials_and_dates():
    url = (
        "https://readings.powerpal.net/csv/v1/0005191c"
        "?token=secret-token&start=1735909200&end=1735995599&sample=1"
    )

    parsed = puller.parse_export_url(url)

    assert parsed["device_id"] == "0005191c"
    assert parsed["token"] == "secret-token"
    assert parsed["sample"] == 1
    assert parsed["start"] == date(2025, 1, 4)
    assert parsed["end"] == date(2025, 1, 4)


def test_parse_export_url_rejects_non_powerpal_csv_path():
    try:
        puller.parse_export_url("https://example.com/nope?token=x")
    except ValueError as exc:
        assert "/csv/v1/<device_id>" in str(exc)
    else:
        raise AssertionError("Expected ValueError")
