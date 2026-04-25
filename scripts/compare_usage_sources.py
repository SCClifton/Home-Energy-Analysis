#!/usr/bin/env python3
"""Compare daily usage totals between two Supabase usage sources."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Sequence

import pandas as pd
from dotenv import load_dotenv
from zoneinfo import ZoneInfo

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from home_energy_analysis.storage import supabase_db

TZ = ZoneInfo("Australia/Sydney")


def parse_yyyy_mm_dd(value: str) -> date:
    """Parse a YYYY-MM-DD local date."""
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid date '{value}', expected YYYY-MM-DD") from exc


def local_date_window(start_date: date, end_date: date) -> tuple[datetime, datetime]:
    """Convert inclusive Sydney-local date range to UTC [start, end) datetimes."""
    if start_date > end_date:
        raise ValueError("--start must be on or before --end")
    start_local = datetime.combine(start_date, time.min, tzinfo=TZ)
    end_local_exclusive = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=TZ)
    return start_local.astimezone(timezone.utc), end_local_exclusive.astimezone(timezone.utc)


def expected_minutes_for_local_day(local_day: date) -> int:
    """Return actual minutes in a Sydney-local day, including DST transition days."""
    start_local = datetime.combine(local_day, time.min, tzinfo=TZ)
    end_local = datetime.combine(local_day + timedelta(days=1), time.min, tzinfo=TZ)
    return int((end_local.astimezone(timezone.utc) - start_local.astimezone(timezone.utc)).total_seconds() // 60)


def _date_range(start_date: date, end_date: date) -> list[date]:
    current = start_date
    days: list[date] = []
    while current <= end_date:
        days.append(current)
        current += timedelta(days=1)
    return days


def load_usage_rows(
    site_id: str,
    channel_type: str,
    sources: Sequence[str],
    start_utc: datetime,
    end_utc: datetime,
) -> list[Dict[str, Any]]:
    """Load usage rows from Supabase for the requested sources and UTC window."""
    with supabase_db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT source, interval_start, interval_end, kwh
                FROM usage_intervals
                WHERE site_id = %s
                  AND channel_type = %s
                  AND source = ANY(%s)
                  AND interval_start >= %s
                  AND interval_start < %s
                ORDER BY source, interval_start
                """,
                (site_id, channel_type, list(sources), start_utc, end_utc),
            )
            rows = cur.fetchall()

    return [
        {
            "source": row[0],
            "interval_start": row[1],
            "interval_end": row[2],
            "kwh": float(row[3]) if row[3] is not None else None,
        }
        for row in rows
    ]


def aggregate_daily(
    rows: Iterable[Dict[str, Any]],
    start_date: date,
    end_date: date,
    sources: Sequence[str],
) -> pd.DataFrame:
    """Aggregate usage rows by Sydney-local day and source."""
    days = _date_range(start_date, end_date)
    grid = pd.MultiIndex.from_product([sources, days], names=["source", "local_date"]).to_frame(index=False)
    grid["expected_minutes"] = grid["local_date"].apply(expected_minutes_for_local_day)

    df = pd.DataFrame(list(rows))
    if df.empty:
        grouped = pd.DataFrame(columns=[
            "source",
            "local_date",
            "kwh_total",
            "covered_minutes",
            "interval_count",
            "first_interval_start",
            "last_interval_end",
        ])
    else:
        df["interval_start"] = pd.to_datetime(df["interval_start"], utc=True)
        df["interval_end"] = pd.to_datetime(df["interval_end"], utc=True)
        df["kwh"] = pd.to_numeric(df["kwh"], errors="coerce")
        df["local_date"] = df["interval_start"].dt.tz_convert(TZ).dt.date
        df["duration_minutes"] = (
            (df["interval_end"] - df["interval_start"]).dt.total_seconds() / 60.0
        ).clip(lower=0)

        grouped = (
            df.groupby(["source", "local_date"], as_index=False)
            .agg(
                kwh_total=("kwh", "sum"),
                covered_minutes=("duration_minutes", "sum"),
                interval_count=("kwh", "count"),
                first_interval_start=("interval_start", "min"),
                last_interval_end=("interval_end", "max"),
            )
        )

    daily = grid.merge(grouped, on=["source", "local_date"], how="left")
    daily["covered_minutes"] = daily["covered_minutes"].fillna(0.0)
    daily["interval_count"] = daily["interval_count"].fillna(0).astype(int)
    daily["missing_coverage_minutes"] = (
        daily["expected_minutes"] - daily["covered_minutes"]
    ).clip(lower=0)

    present_mask = daily["interval_count"] > 0
    daily.loc[~present_mask, "kwh_total"] = pd.NA
    daily["covered_minutes"] = daily["covered_minutes"].round(3)
    daily["missing_coverage_minutes"] = daily["missing_coverage_minutes"].round(3)
    return daily.sort_values(["local_date", "source"]).reset_index(drop=True)


def build_reconciliation(daily: pd.DataFrame, source_a: str, source_b: str) -> pd.DataFrame:
    """Build daily source-vs-source reconciliation table."""
    a = daily[daily["source"] == source_a].copy()
    b = daily[daily["source"] == source_b].copy()

    a = a.rename(columns={
        "kwh_total": f"{source_a}_kwh",
        "covered_minutes": f"{source_a}_covered_minutes",
        "missing_coverage_minutes": f"{source_a}_missing_minutes",
        "interval_count": f"{source_a}_interval_count",
    })
    b = b.rename(columns={
        "kwh_total": f"{source_b}_kwh",
        "covered_minutes": f"{source_b}_covered_minutes",
        "missing_coverage_minutes": f"{source_b}_missing_minutes",
        "interval_count": f"{source_b}_interval_count",
    })

    keep_a = [
        "local_date",
        "expected_minutes",
        f"{source_a}_kwh",
        f"{source_a}_covered_minutes",
        f"{source_a}_missing_minutes",
        f"{source_a}_interval_count",
    ]
    keep_b = [
        "local_date",
        f"{source_b}_kwh",
        f"{source_b}_covered_minutes",
        f"{source_b}_missing_minutes",
        f"{source_b}_interval_count",
    ]

    reconciliation = a[keep_a].merge(b[keep_b], on="local_date", how="outer")
    reconciliation["diff_kwh"] = reconciliation[f"{source_a}_kwh"] - reconciliation[f"{source_b}_kwh"]
    denominator = reconciliation[f"{source_a}_kwh"].replace({0: pd.NA})
    reconciliation[f"diff_pct_vs_{source_a}"] = (reconciliation["diff_kwh"] / denominator) * 100.0
    return reconciliation.sort_values("local_date").reset_index(drop=True)


def reconciliation_stats(reconciliation: pd.DataFrame, source_a: str, source_b: str) -> Dict[str, Any]:
    """Compute summary stats for a reconciliation table."""
    a_col = f"{source_a}_kwh"
    b_col = f"{source_b}_kwh"
    overlap = reconciliation.dropna(subset=[a_col, b_col]).copy()
    missing_a = reconciliation[reconciliation[a_col].isna()]
    missing_b = reconciliation[reconciliation[b_col].isna()]

    stats: Dict[str, Any] = {
        "overlap_days": int(len(overlap)),
        f"days_missing_{source_a}": int(len(missing_a)),
        f"days_missing_{source_b}": int(len(missing_b)),
        "mean_abs_diff_kwh": None,
        "median_abs_diff_kwh": None,
        "max_abs_diff_kwh": None,
        "correlation": None,
    }

    if not overlap.empty:
        abs_diff = overlap["diff_kwh"].abs()
        stats["mean_abs_diff_kwh"] = float(abs_diff.mean())
        stats["median_abs_diff_kwh"] = float(abs_diff.median())
        stats["max_abs_diff_kwh"] = float(abs_diff.max())
        if len(overlap) >= 2:
            stats["correlation"] = float(overlap[[a_col, b_col]].corr().iloc[0, 1])
    return stats


def print_report(reconciliation: pd.DataFrame, stats: Dict[str, Any], source_a: str, source_b: str) -> None:
    """Print concise reconciliation summary."""
    print("=== Usage source reconciliation ===")
    print(f"Source A: {source_a}")
    print(f"Source B: {source_b}")
    print(f"Days in report: {len(reconciliation)}")
    for key, value in stats.items():
        print(f"{key}: {value}")

    print()
    print("First 10 daily rows:")
    display_cols = [
        "local_date",
        f"{source_a}_kwh",
        f"{source_b}_kwh",
        "diff_kwh",
        f"diff_pct_vs_{source_a}",
        f"{source_a}_missing_minutes",
        f"{source_b}_missing_minutes",
    ]
    print(reconciliation[display_cols].head(10).to_string(index=False))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Compare usage totals between two Supabase sources")
    parser.add_argument("--start", required=True, type=parse_yyyy_mm_dd,
                        help="Start date YYYY-MM-DD in Australia/Sydney")
    parser.add_argument("--end", required=True, type=parse_yyyy_mm_dd,
                        help="End date YYYY-MM-DD in Australia/Sydney, inclusive")
    parser.add_argument("--site-id", default=None,
                        help="Site ID (default: AMBER_SITE_ID env var)")
    parser.add_argument("--channel-type", default="general",
                        help="Channel type (default: general)")
    parser.add_argument("--source-a", default="powerpal",
                        help="First source, used as percentage denominator (default: powerpal)")
    parser.add_argument("--source-b", default="amber",
                        help="Second source to compare against source-a (default: amber)")
    parser.add_argument("--out-csv", type=Path, default=None,
                        help="Optional output CSV path")

    args = parser.parse_args(argv)

    load_dotenv(project_root / ".env.local", override=False)

    site_id = args.site_id or os.getenv("AMBER_SITE_ID")
    if not site_id:
        print("ERROR: --site-id required or AMBER_SITE_ID must be set", file=sys.stderr)
        return 1
    if not os.getenv("SUPABASE_DB_URL"):
        print("ERROR: SUPABASE_DB_URL environment variable is required", file=sys.stderr)
        return 1

    try:
        start_utc, end_utc = local_date_window(args.start, args.end)
        print(f"Local window: {args.start} to {args.end} Australia/Sydney")
        print(f"UTC query window: {start_utc.isoformat()} to {end_utc.isoformat()} [exclusive]")

        rows = load_usage_rows(
            site_id,
            args.channel_type,
            [args.source_a, args.source_b],
            start_utc,
            end_utc,
        )
        daily = aggregate_daily(rows, args.start, args.end, [args.source_a, args.source_b])
        reconciliation = build_reconciliation(daily, args.source_a, args.source_b)
        stats = reconciliation_stats(reconciliation, args.source_a, args.source_b)
        print_report(reconciliation, stats, args.source_a, args.source_b)

        if args.out_csv:
            args.out_csv.parent.mkdir(parents=True, exist_ok=True)
            reconciliation.to_csv(args.out_csv, index=False)
            print(f"Saved daily reconciliation CSV: {args.out_csv}")
    except Exception as e:
        print(f"ERROR: Failed to compare usage sources: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
