"""Weather and irradiance retrieval utilities for scenario simulation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List

import pandas as pd
import requests

VAUCLUSE_LAT = -33.857
VAUCLUSE_LON = 151.281
OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


def _parse_hourly_payload(payload: Dict, source: str) -> pd.DataFrame:
    hourly = payload.get("hourly", {})
    times = hourly.get("time") or []
    ghi = hourly.get("shortwave_radiation") or []
    temp = hourly.get("temperature_2m") or []
    cloud = hourly.get("cloud_cover") or []

    rows: List[Dict] = []
    for idx, time_str in enumerate(times):
        dt = datetime.fromisoformat(time_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)

        rows.append(
            {
                "interval_start": dt,
                "interval_end": dt + timedelta(hours=1),
                "ghi_wm2": float(ghi[idx]) if idx < len(ghi) and ghi[idx] is not None else None,
                "temperature_c": float(temp[idx]) if idx < len(temp) and temp[idx] is not None else None,
                "cloud_cover_pct": float(cloud[idx]) if idx < len(cloud) and cloud[idx] is not None else None,
                "source": source,
            }
        )

    if not rows:
        return pd.DataFrame(
            columns=[
                "interval_start",
                "interval_end",
                "ghi_wm2",
                "temperature_c",
                "cloud_cover_pct",
                "source",
            ]
        )

    df = pd.DataFrame(rows)
    df["interval_start"] = pd.to_datetime(df["interval_start"], utc=True)
    df["interval_end"] = pd.to_datetime(df["interval_end"], utc=True)
    return df.sort_values("interval_start").drop_duplicates(subset=["interval_start"], keep="last")


def _fetch_hourly(session: requests.Session, url: str, start_utc: datetime, end_utc: datetime) -> pd.DataFrame:
    params = {
        "latitude": VAUCLUSE_LAT,
        "longitude": VAUCLUSE_LON,
        "hourly": "shortwave_radiation,temperature_2m,cloud_cover",
        "start_date": start_utc.date().isoformat(),
        "end_date": end_utc.date().isoformat(),
        "timezone": "UTC",
    }
    response = session.get(url, params=params, timeout=30)
    response.raise_for_status()
    source = "open-meteo-archive" if "archive" in url else "open-meteo-forecast"
    return _parse_hourly_payload(response.json(), source)


def fetch_open_meteo_hourly(start_utc: datetime, end_utc: datetime) -> pd.DataFrame:
    """
    Fetch real irradiance/weather data near Vaucluse NSW from Open-Meteo.

    Splits requests between archive (past) and forecast (future) APIs to support
    backtest and live windows with the same interface.
    """
    if start_utc.tzinfo is None or end_utc.tzinfo is None:
        raise ValueError("start_utc and end_utc must be timezone-aware UTC datetimes")

    now_utc = datetime.now(timezone.utc)
    frames: List[pd.DataFrame] = []

    with requests.Session() as session:
        session.headers["User-Agent"] = "home-energy-analysis-simulation/1.0"

        if start_utc < now_utc:
            archive_end = min(end_utc, now_utc)
            frames.append(_fetch_hourly(session, OPEN_METEO_ARCHIVE_URL, start_utc, archive_end))

        if end_utc > now_utc:
            forecast_start = max(start_utc, now_utc - timedelta(hours=2))
            frames.append(_fetch_hourly(session, OPEN_METEO_FORECAST_URL, forecast_start, end_utc))

    if not frames:
        return pd.DataFrame(
            columns=[
                "interval_start",
                "interval_end",
                "ghi_wm2",
                "temperature_c",
                "cloud_cover_pct",
                "source",
            ]
        )

    out = pd.concat(frames, ignore_index=True)
    out = out.sort_values("interval_start").drop_duplicates(subset=["interval_start"], keep="last")
    return out


def hourly_to_five_minute_intervals(hourly_df: pd.DataFrame, start_utc: datetime, end_utc: datetime) -> pd.DataFrame:
    """
    Convert hourly irradiance/weather to 5-minute aligned intervals.

    Values are linearly interpolated between hourly points.
    """
    if hourly_df.empty:
        return pd.DataFrame(
            columns=[
                "interval_start",
                "interval_end",
                "ghi_wm2",
                "temperature_c",
                "cloud_cover_pct",
                "source",
            ]
        )

    index = pd.date_range(start=start_utc, end=end_utc, freq="5min", inclusive="left", tz="UTC")
    aligned = hourly_df.set_index(pd.to_datetime(hourly_df["interval_start"], utc=True)).sort_index()

    reindexed = aligned.reindex(aligned.index.union(index)).sort_index()
    reindexed["ghi_wm2"] = reindexed["ghi_wm2"].interpolate(method="time").fillna(0.0).clip(lower=0.0)
    reindexed["temperature_c"] = reindexed["temperature_c"].interpolate(method="time").fillna(method="ffill").fillna(20.0)
    reindexed["cloud_cover_pct"] = (
        reindexed["cloud_cover_pct"].interpolate(method="time").fillna(method="ffill").fillna(0.0).clip(lower=0.0, upper=100.0)
    )
    reindexed["source"] = reindexed["source"].fillna(method="ffill").fillna("open-meteo")

    out = reindexed.loc[index, ["ghi_wm2", "temperature_c", "cloud_cover_pct", "source"]].reset_index()
    out = out.rename(columns={"index": "interval_start"})
    out["interval_end"] = out["interval_start"] + pd.Timedelta(minutes=5)
    out["interval_start"] = pd.to_datetime(out["interval_start"], utc=True)
    out["interval_end"] = pd.to_datetime(out["interval_end"], utc=True)
    return out


# TODO(data-source): Add BOM irradiance fallback when authenticated station access is available.
