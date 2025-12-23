"""
Find the earliest date with Amber usage data for the configured site.

The script walks backwards in chunks, then refines with a day-level binary search.
It does not write any output files; it only prints coverage stats.
"""

import argparse
import os
import sys
from pathlib import Path
from datetime import date, timedelta, datetime
from typing import Optional, Tuple

# Ensure repo root is on sys.path so imports work when running from scripts/
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from ingestion.amber_client import AmberClient


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Discover earliest Amber usage date")
    parser.add_argument("--step-days", type=int, default=7, help="Chunk size when scanning backwards (default 7)")
    parser.add_argument(
        "--max-weeks",
        type=int,
        default=260,
        help="Maximum weeks to scan backwards (default 260 ≈ 5 years)",
    )
    return parser.parse_args()


def _require_env(var: str) -> str:
    value = os.getenv(var)
    if not value:
        raise SystemExit(f"ERROR: {var} environment variable is not set")
    return value


def _infer_interval_minutes(rows: list[dict]) -> Optional[float]:
    durations = []
    for row in rows:
        dur = row.get("duration")
        if dur is not None:
            try:
                val = float(dur)
                if val > 0:
                    durations.append(val)
            except (TypeError, ValueError):
                continue
        if not durations:
            # try start/end diff if duration missing
            try:
                start = row.get("startTime")
                end = row.get("endTime")
                if start and end:
                    ds = datetime.fromisoformat(start.replace("Z", "+00:00"))
                    de = datetime.fromisoformat(end.replace("Z", "+00:00"))
                    delta_min = (de - ds).total_seconds() / 60.0
                    if delta_min > 0:
                        durations.append(delta_min)
            except Exception:
                continue
    if not durations:
        return None
    # pick the most common (or min) to reduce noise
    return min(durations)


def _fetch(client: AmberClient, site_id: str, start: date, end: date, resolution: Optional[str] = None) -> list[dict]:
    return client.get_usage_range(site_id, start, end, resolution=resolution)


def _binary_refine(
    client: AmberClient,
    site_id: str,
    no_data_end: date,
    data_start: date,
) -> Tuple[date, list[dict]]:
    """
    Binary search between (no_data_end, data_start] to find earliest date with data.
    Returns the earliest date and the rows for that date.
    """
    low = no_data_end  # known no data boundary
    high = data_start  # known data boundary

    while (high - low).days > 1:
        mid = low + timedelta(days=(high - low).days // 2)
        rows = _fetch(client, site_id, mid, high)
        if rows:
            # data exists in [mid, high]
            high = mid
        else:
            low = mid

    # high is the earliest day with data
    earliest_rows = _fetch(client, site_id, high, high + timedelta(days=1))
    return high, earliest_rows


def main() -> int:
    args = _parse_args()
    step_days = args.step_days
    max_weeks = args.max_weeks

    token = _require_env("AMBER_TOKEN")
    site_id = _require_env("AMBER_SITE_ID")

    client = AmberClient(token=token)

    today = date.today()
    current_end = today
    max_days_back = max_weeks * 7
    first_data_chunk = None
    last_no_data_chunk_end = None
    seen_data = False

    total_days_scanned = 0

    while total_days_scanned < max_days_back:
        chunk_start = current_end - timedelta(days=step_days - 1)
        if chunk_start < today - timedelta(days=max_days_back - 1):
            chunk_start = today - timedelta(days=max_days_back - 1)

        rows = _fetch(client, site_id, chunk_start, current_end + timedelta(days=1))
        count = len(rows)

        # print progress
        print(f"Checked {chunk_start} to {current_end}: {count} rows")

        if count > 0:
            seen_data = True
            first_data_chunk = (chunk_start, current_end, rows)
        elif seen_data:
            last_no_data_chunk_end = current_end
            break

        if chunk_start <= today - timedelta(days=max_days_back - 1):
            # reached limit
            if not last_no_data_chunk_end:
                last_no_data_chunk_end = chunk_start - timedelta(days=1)
            break

        current_end = chunk_start - timedelta(days=1)
        total_days_scanned += step_days

    if not seen_data or not first_data_chunk:
        raise SystemExit("No usage data found within the search window.")

    if last_no_data_chunk_end is None:
        # no missing chunk found; assume earliest within search window
        last_no_data_chunk_end = first_data_chunk[0] - timedelta(days=1)

    earliest_date, earliest_rows = _binary_refine(
        client,
        site_id,
        no_data_end=last_no_data_chunk_end,
        data_start=first_data_chunk[0],
    )

    interval_minutes = _infer_interval_minutes(earliest_rows)
    first_day_rows = len(earliest_rows)

    print("\n=== Earliest Usage Coverage ===")
    print(f"earliest_date_with_data: {earliest_date.isoformat()}")
    print(f"latest_date_checked:     {today.isoformat()}")
    print(f"interval_minutes:        {interval_minutes if interval_minutes is not None else 'unknown'}")
    print(f"rows_in_first_day:       {first_day_rows}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

