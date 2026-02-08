"""Data loaders for scenario simulation from SQLite cache and Supabase."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Tuple

import pandas as pd

from home_energy_analysis.storage import supabase_db


def _as_float(value):
    if isinstance(value, Decimal):
        return float(value)
    return value


def _to_utc_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def _coerce_interval_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    df["interval_start"] = pd.to_datetime(df["interval_start"], utc=True)
    df["interval_end"] = pd.to_datetime(df["interval_end"], utc=True)
    return df.sort_values("interval_start").drop_duplicates(subset=["interval_start"], keep="last")


def load_sqlite_usage_prices(
    cache_path: str,
    site_id: str,
    start_utc: datetime,
    end_utc: datetime,
    channel_type: str = "general",
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Load usage + prices from SQLite cache."""
    start_iso = _to_utc_iso(start_utc)
    end_iso = _to_utc_iso(end_utc)

    conn = sqlite3.connect(cache_path)
    try:
        usage_df = pd.read_sql_query(
            """
            SELECT interval_start, interval_end, kwh AS usage_kwh, cost_aud
            FROM usage
            WHERE site_id = ?
              AND channel_type = ?
              AND interval_start >= ?
              AND interval_start < ?
            ORDER BY interval_start
            """,
            conn,
            params=(site_id, channel_type, start_iso, end_iso),
        )

        price_df = pd.read_sql_query(
            """
            SELECT interval_start, interval_end, per_kwh AS price_cents_per_kwh,
                   descriptor, renewables
            FROM prices
            WHERE site_id = ?
              AND channel_type = ?
              AND interval_start >= ?
              AND interval_start < ?
            ORDER BY interval_start
            """,
            conn,
            params=(site_id, channel_type, start_iso, end_iso),
        )
    finally:
        conn.close()

    return _coerce_interval_df(usage_df), _coerce_interval_df(price_df)


def load_sqlite_irradiance(
    cache_path: str,
    location_id: str,
    start_utc: datetime,
    end_utc: datetime,
) -> pd.DataFrame:
    """Load cached irradiance from SQLite."""
    start_iso = _to_utc_iso(start_utc)
    end_iso = _to_utc_iso(end_utc)

    conn = sqlite3.connect(cache_path)
    try:
        df = pd.read_sql_query(
            """
            SELECT interval_start, interval_end, ghi_wm2, temperature_c, cloud_cover_pct, source
            FROM irradiance
            WHERE location_id = ?
              AND interval_start >= ?
              AND interval_start < ?
            ORDER BY interval_start
            """,
            conn,
            params=(location_id, start_iso, end_iso),
        )
    finally:
        conn.close()

    return _coerce_interval_df(df)


def load_supabase_usage_prices(
    site_id: str,
    start_utc: datetime,
    end_utc: datetime,
    channel_type: str = "general",
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Load usage + prices from Supabase with source preference and de-duplication."""

    usage_rows = []
    price_rows = []

    with supabase_db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH ranked AS (
                    SELECT
                        interval_start,
                        interval_end,
                        kwh,
                        cost_aud,
                        source,
                        ROW_NUMBER() OVER (
                            PARTITION BY interval_start
                            ORDER BY
                                CASE
                                    WHEN source = 'powerpal' THEN 0
                                    WHEN source = 'amber' THEN 1
                                    ELSE 2
                                END,
                                ingested_at DESC
                        ) AS rn
                    FROM usage_intervals
                    WHERE site_id = %s
                      AND channel_type = %s
                      AND interval_start >= %s
                      AND interval_start < %s
                )
                SELECT interval_start, interval_end, kwh, cost_aud, source
                FROM ranked
                WHERE rn = 1
                ORDER BY interval_start
                """,
                (site_id, channel_type, start_utc, end_utc),
            )
            usage_rows = cur.fetchall()

            cur.execute(
                """
                WITH ranked AS (
                    SELECT
                        interval_start,
                        interval_end,
                        price_cents_per_kwh,
                        descriptor,
                        renewables_percent,
                        is_forecast,
                        source,
                        ROW_NUMBER() OVER (
                            PARTITION BY interval_start
                            ORDER BY
                                CASE WHEN is_forecast = FALSE THEN 0 ELSE 1 END,
                                ingested_at DESC
                        ) AS rn
                    FROM price_intervals
                    WHERE site_id = %s
                      AND interval_start >= %s
                      AND interval_start < %s
                )
                SELECT interval_start, interval_end, price_cents_per_kwh,
                       descriptor, renewables_percent, is_forecast, source
                FROM ranked
                WHERE rn = 1
                ORDER BY interval_start
                """,
                (site_id, start_utc, end_utc),
            )
            price_rows = cur.fetchall()

    usage_df = pd.DataFrame(
        [
            {
                "interval_start": row[0],
                "interval_end": row[1],
                "usage_kwh": _as_float(row[2]),
                "cost_aud": _as_float(row[3]),
                "usage_source": row[4],
            }
            for row in usage_rows
        ]
    )

    price_df = pd.DataFrame(
        [
            {
                "interval_start": row[0],
                "interval_end": row[1],
                "price_cents_per_kwh": _as_float(row[2]),
                "descriptor": row[3],
                "renewables": _as_float(row[4]),
                "is_forecast": bool(row[5]),
                "price_source": row[6],
            }
            for row in price_rows
        ]
    )

    return _coerce_interval_df(usage_df), _coerce_interval_df(price_df)


def merge_with_precedence(primary: pd.DataFrame, fallback: pd.DataFrame) -> pd.DataFrame:
    """Merge interval tables where primary rows override fallback on interval_start."""
    if primary.empty:
        return fallback.copy()
    if fallback.empty:
        return primary.copy()

    key = "interval_start"
    combined = pd.concat([fallback, primary], ignore_index=True)
    combined = combined.sort_values(key).drop_duplicates(subset=[key], keep="last")
    return combined.reset_index(drop=True)


def newest_interval_timestamp(usage_df: pd.DataFrame) -> Optional[datetime]:
    """Return latest interval_start from usage dataframe."""
    if usage_df.empty:
        return None
    ts = pd.to_datetime(usage_df["interval_start"], utc=True).max()
    if pd.isna(ts):
        return None
    return ts.to_pydatetime()
