#!/usr/bin/env python3
"""Forward recent SQLite cache rows into Supabase with cache provenance."""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

from dotenv import load_dotenv

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root / "src"))
load_dotenv(project_root / ".env.local", override=False)

from home_energy_analysis.storage import supabase_db
from home_energy_analysis.storage.factory import get_sqlite_cache


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid date '{value}', expected YYYY-MM-DD") from exc


def _utc_start(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=timezone.utc)


def _utc_end_exclusive(d: date) -> datetime:
    return datetime.combine(d + timedelta(days=1), time.min, tzinfo=timezone.utc)


def _iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso_z(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def load_sqlite_price_rows(
    sqlite_path: Path,
    site_id: str,
    start_utc: datetime,
    end_utc: datetime,
    source: str,
) -> list[dict[str, Any]]:
    conn = sqlite3.connect(sqlite_path)
    try:
        rows = conn.execute(
            """
            SELECT site_id, interval_start, interval_end, per_kwh, renewables, descriptor
            FROM prices
            WHERE site_id = ?
              AND interval_start >= ?
              AND interval_start < ?
            ORDER BY interval_start
            """,
            (site_id, _iso_z(start_utc), _iso_z(end_utc)),
        ).fetchall()
    finally:
        conn.close()

    return [
        {
            "site_id": row[0],
            "interval_start": _parse_iso_z(row[1]),
            "interval_end": _parse_iso_z(row[2]),
            "is_forecast": False,
            "price_cents_per_kwh": float(row[3]) if row[3] is not None else None,
            "spot_per_kwh": None,
            "descriptor": row[5],
            "spike_status": None,
            "renewables_percent": float(row[4]) if row[4] is not None else None,
            "source": source,
            "raw_event_id": None,
        }
        for row in rows
    ]


def load_sqlite_usage_rows(
    sqlite_path: Path,
    site_id: str,
    start_utc: datetime,
    end_utc: datetime,
    source: str,
    channel_type: str,
) -> list[dict[str, Any]]:
    conn = sqlite3.connect(sqlite_path)
    try:
        rows = conn.execute(
            """
            SELECT site_id, channel_type, interval_start, interval_end, kwh,
                   cost_aud, quality, channel_identifier
            FROM usage
            WHERE site_id = ?
              AND channel_type = ?
              AND interval_start >= ?
              AND interval_start < ?
            ORDER BY interval_start
            """,
            (site_id, channel_type, _iso_z(start_utc), _iso_z(end_utc)),
        ).fetchall()
    finally:
        conn.close()

    return [
        {
            "site_id": row[0],
            "channel_type": row[1],
            "interval_start": _parse_iso_z(row[2]),
            "interval_end": _parse_iso_z(row[3]),
            "kwh": float(row[4]),
            "cost_aud": float(row[5]) if row[5] is not None else None,
            "quality": row[6],
            "meter_identifier": row[7],
            "source": source,
            "raw_event_id": None,
        }
        for row in rows
    ]


def attach_ingest_event(
    conn,
    rows: list[dict[str, Any]],
    source: str,
    kind: str,
    sqlite_path: Path,
    start_utc: datetime,
    end_utc: datetime,
) -> None:
    if not rows:
        return

    event_id = supabase_db.insert_ingest_event(
        conn,
        source,
        kind,
        {
            "sqlite_path": str(sqlite_path),
            "row_count": len(rows),
            "window_start": _iso_z(start_utc),
            "window_end": _iso_z(end_utc),
        },
        window_start=start_utc,
        window_end=end_utc,
    )
    for row in rows:
        row["raw_event_id"] = event_id


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync recent SQLite cache rows into Supabase")
    parser.add_argument("--sqlite-path", type=Path, default=None, help="SQLite cache path; defaults to SQLITE_PATH")
    parser.add_argument("--site-id", default=None, help="Site ID; defaults to AMBER_SITE_ID")
    parser.add_argument("--channel-type", default="general")
    parser.add_argument("--start", type=_parse_date, default=None, help="UTC start date YYYY-MM-DD")
    parser.add_argument("--end", type=_parse_date, default=None, help="UTC end date YYYY-MM-DD, inclusive")
    parser.add_argument("--days-back", type=int, default=7, help="Rolling window when start/end are omitted")
    parser.add_argument("--price-source", default="sqlite-cache")
    parser.add_argument("--usage-source", default="sqlite-cache")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    site_id = args.site_id or os.getenv("AMBER_SITE_ID")
    if not site_id:
        print("ERROR: --site-id or AMBER_SITE_ID is required", file=sys.stderr)
        return 1

    sqlite_path = args.sqlite_path or Path(get_sqlite_cache())
    if not sqlite_path.exists():
        print(f"ERROR: SQLite cache not found: {sqlite_path}", file=sys.stderr)
        return 1

    if args.start or args.end:
        if not args.start or not args.end:
            print("ERROR: --start and --end must be supplied together", file=sys.stderr)
            return 1
        start_utc = _utc_start(args.start)
        end_utc = _utc_end_exclusive(args.end)
    else:
        end_day = datetime.now(timezone.utc).date()
        start_utc = _utc_start(end_day - timedelta(days=args.days_back))
        end_utc = _utc_end_exclusive(end_day)

    prices = load_sqlite_price_rows(sqlite_path, site_id, start_utc, end_utc, args.price_source)
    usage = load_sqlite_usage_rows(sqlite_path, site_id, start_utc, end_utc, args.usage_source, args.channel_type)

    print(f"SQLite sync window: {_iso_z(start_utc)} to {_iso_z(end_utc)}")
    print(f"SQLite cache: {sqlite_path}")
    print(f"Price rows: {len(prices)} source={args.price_source}")
    print(f"Usage rows: {len(usage)} source={args.usage_source}")

    if args.dry_run:
        print("Dry run complete; no Supabase writes were attempted.")
        return 0

    if not os.getenv("SUPABASE_DB_URL"):
        print("ERROR: SUPABASE_DB_URL environment variable is required", file=sys.stderr)
        return 1

    with supabase_db.get_conn() as conn:
        attach_ingest_event(conn, prices, args.price_source, "prices", sqlite_path, start_utc, end_utc)
        attach_ingest_event(conn, usage, args.usage_source, "usage", sqlite_path, start_utc, end_utc)
        price_count = supabase_db.upsert_price_intervals(conn, prices)
        usage_count = supabase_db.upsert_usage_intervals(conn, usage)

    print(f"Supabase upsert complete prices={price_count} usage={usage_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
