#!/usr/bin/env python3
"""
Forward sync recent Amber prices and usage into Supabase.
"""
import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path
import subprocess

from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def _parse_date(value: str) -> date:
    """Parse YYYY-MM-DD date string."""
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid date '{value}', expected YYYY-MM-DD") from exc


def _run_backfill(script_path: Path, start_date: date, end_date: date, dry_run: bool) -> int:
    cmd = [
        sys.executable,
        str(script_path),
        "--start",
        start_date.isoformat(),
        "--end",
        end_date.isoformat(),
    ]
    if dry_run:
        logger.info("Dry run: would execute %s", " ".join(cmd))
        return 0

    logger.info("Running %s", " ".join(cmd))
    result = subprocess.run(cmd, cwd=script_path.parent.parent, check=False)
    if result.returncode != 0:
        logger.error("Command failed with exit code %s", result.returncode)
    return result.returncode


def _run_sqlite_sync(script_path: Path, days_back: int, dry_run: bool) -> int:
    cmd = [
        sys.executable,
        str(script_path),
        "--days-back",
        str(days_back),
    ]
    if dry_run:
        cmd.append("--dry-run")
        logger.info("Dry run: would execute %s", " ".join(cmd))
        return 0

    logger.info("Running %s", " ".join(cmd))
    result = subprocess.run(cmd, cwd=script_path.parent.parent, check=False)
    if result.returncode != 0:
        logger.error("Command failed with exit code %s", result.returncode)
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Forward sync recent Amber prices and usage into Supabase",
    )
    parser.add_argument(
        "--days-back",
        type=int,
        default=3,
        help="Days to sync backwards from end date (default: 3)",
    )
    parser.add_argument(
        "--end-date",
        type=_parse_date,
        default=date.today(),
        help="End date YYYY-MM-DD (default: today in local time)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log commands without writing to Supabase",
    )
    parser.add_argument(
        "--skip-sqlite-cache",
        action="store_true",
        help="Do not forward the local SQLite cache rows after API backfills",
    )

    args = parser.parse_args()

    if args.days_back < 0:
        logger.error("--days-back must be >= 0")
        return 1

    end_date = args.end_date
    start_date = end_date - timedelta(days=args.days_back)

    project_root = Path(__file__).resolve().parents[1]
    # Local fallback for development. On Pi, systemd EnvironmentFile provides env.
    load_dotenv(project_root / ".env.local", override=False)

    logger.info("Forward sync window: %s to %s", start_date.isoformat(), end_date.isoformat())

    prices_script = project_root / "scripts" / "backfill_amber_prices_to_supabase.py"
    usage_script = project_root / "scripts" / "backfill_amber_usage_to_supabase.py"
    sqlite_script = project_root / "scripts" / "sync_sqlite_to_supabase.py"

    failures = 0
    result = _run_backfill(prices_script, start_date, end_date, args.dry_run)
    if result != 0:
        failures += 1

    result = _run_backfill(usage_script, start_date, end_date, args.dry_run)
    if result != 0:
        failures += 1

    if not args.skip_sqlite_cache:
        result = _run_sqlite_sync(sqlite_script, args.days_back, args.dry_run)
        if result != 0:
            failures += 1

    if failures:
        logger.error("Forward sync completed with %s failed step(s)", failures)
        return 1

    logger.info("Forward sync complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
