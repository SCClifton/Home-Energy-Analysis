"""
Baseline modelling utilities for Amber interval data.

These functions are pure / data-in data-out to stay testable.
"""

from __future__ import annotations

import pandas as pd


def _interval_length_minutes(series: pd.Series) -> float | None:
    """Detect the most common interval length in minutes."""
    valid = series.dropna()
    if valid.empty:
        return None
    mode = valid.mode()
    if mode.empty:
        return None
    return float(mode.iloc[0])


def normalise_usage(df_usage: pd.DataFrame) -> pd.DataFrame:
    """
    Standardise usage data to a consistent schema.
    Returns columns:
        - interval_start (datetime64[ns, UTC])
        - interval_end   (datetime64[ns, UTC])
        - duration_minutes (float)
        - usage_kwh (float)
    """
    df = df_usage.copy()
    before = len(df)

    df["interval_start"] = pd.to_datetime(df.get("startTime"), utc=True, errors="coerce")
    df["interval_end"] = pd.to_datetime(df.get("endTime"), utc=True, errors="coerce")

    if "duration" in df.columns:
        df["duration_minutes"] = pd.to_numeric(df["duration"], errors="coerce")
    else:
        df["duration_minutes"] = (df["interval_end"] - df["interval_start"]).dt.total_seconds() / 60.0

    df["usage_kwh"] = pd.to_numeric(df.get("kwh"), errors="coerce")

    df = df.dropna(subset=["interval_start", "interval_end", "usage_kwh"])
    df = df.drop_duplicates(subset=["interval_start"])

    df = df.sort_values("interval_start")
    df["interval_length_detected_minutes"] = _interval_length_minutes(
        df["duration_minutes"].round(3)
    )

    df.attrs["duplicates_removed_usage"] = before - len(df)
    return df[["interval_start", "interval_end", "duration_minutes", "usage_kwh", "interval_length_detected_minutes"]]


def normalise_prices(df_prices: pd.DataFrame) -> pd.DataFrame:
    """
    Standardise price data to a consistent schema.
    Returns columns:
        - interval_start (datetime64[ns, UTC])
        - interval_end   (datetime64[ns, UTC])
        - price_c_per_kwh (float)
    """
    df = df_prices.copy()
    before = len(df)

    df["interval_start"] = pd.to_datetime(df.get("startTime"), utc=True, errors="coerce")
    df["interval_start"] = df["interval_start"].dt.floor("5min")
    df["interval_end"] = df["interval_start"] + pd.Timedelta(minutes=5)
    df["price_c_per_kwh"] = pd.to_numeric(df.get("perKwh"), errors="coerce")

    df = df.dropna(subset=["interval_start", "interval_end", "price_c_per_kwh"])
    df = df.drop_duplicates(subset=["interval_start"])
    df = df.sort_values("interval_start")

    df.attrs["duplicates_removed_prices"] = before - len(df)
    return df[["interval_start", "interval_end", "price_c_per_kwh"]]


def align_intervals(df_usage: pd.DataFrame, df_prices: pd.DataFrame) -> pd.DataFrame:
    """
    Outer-join usage and prices on interval_start.
    Reports missing intervals via boolean columns.
    """
    attrs = {}
    if "duplicates_removed_usage" in df_usage.attrs:
        attrs["duplicates_removed_usage"] = df_usage.attrs["duplicates_removed_usage"]
    if "duplicates_removed_prices" in df_prices.attrs:
        attrs["duplicates_removed_prices"] = df_prices.attrs["duplicates_removed_prices"]

    merged = df_usage.merge(
        df_prices,
        on="interval_start",
        how="outer",
        suffixes=("_usage", "_price"),
    ).sort_values("interval_start")

    merged["missing_usage"] = merged["usage_kwh"].isna()
    merged["missing_price"] = merged["price_c_per_kwh"].isna()

    merged.attrs.update(attrs)
    return merged


def compute_energy_only_cost(df_joined: pd.DataFrame) -> pd.DataFrame:
    """
    Add interval cost columns (cents and dollars).
    """
    df = df_joined.copy()
    df["interval_cost_cents"] = df["usage_kwh"] * df["price_c_per_kwh"]
    df["interval_cost_dollars"] = df["interval_cost_cents"] / 100.0
    return df


def summarise(df: pd.DataFrame) -> dict:
    """
    Summarise totals and coverage.
    """
    total_kwh = df["usage_kwh"].fillna(0).sum()
    total_cost_cents = df["interval_cost_cents"].fillna(0).sum()
    total_cost_dollars = total_cost_cents / 100.0

    delivered_kwh = df["usage_kwh"].dropna().sum()
    avg_c_per_kwh = (total_cost_cents / delivered_kwh) if delivered_kwh else None

    missing_usage = int(df["missing_usage"].sum()) if "missing_usage" in df else 0
    missing_price = int(df["missing_price"].sum()) if "missing_price" in df else 0
    count_intervals = len(df)

    duplicates_removed_usage = df.attrs.get("duplicates_removed_usage", None)
    duplicates_removed_prices = df.attrs.get("duplicates_removed_prices", None)

    return {
        "total_kwh": float(total_kwh),
        "total_cost_dollars": float(total_cost_dollars),
        "avg_c_per_kwh": float(avg_c_per_kwh) if avg_c_per_kwh is not None else None,
        "count_intervals": int(count_intervals),
        "missing_usage_intervals": missing_usage,
        "missing_price_intervals": missing_price,
        "duplicates_removed_usage": duplicates_removed_usage,
        "duplicates_removed_prices": duplicates_removed_prices,
    }

