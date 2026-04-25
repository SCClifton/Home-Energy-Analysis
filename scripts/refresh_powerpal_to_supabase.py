#!/usr/bin/env python3
"""Download Powerpal CSV exports and load them into Supabase."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Sequence

from dotenv import load_dotenv

project_root = Path(__file__).resolve().parents[1]
load_dotenv(project_root / ".env.local", override=False)
sys.path.insert(0, str(project_root / "scripts"))

from pull_powerpal_minute_csv import parse_export_url


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid date '{value}', expected YYYY-MM-DD") from exc


def _has_powerpal_config(export_url: str | None) -> bool:
    return bool(export_url) or bool(os.getenv("POWERPAL_DEVICE_ID") and os.getenv("POWERPAL_TOKEN"))


def run_command(cmd: list[str], dry_run: bool) -> int:
    printable = " ".join("***POWERPAL_EXPORT_URL***" if part.startswith("https://readings.powerpal.net/") else part for part in cmd)
    if dry_run:
        print(f"Dry run: would execute {printable}")
        return 0
    print(f"Running {printable}")
    result = subprocess.run(cmd, cwd=project_root, check=False)
    return result.returncode


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh Powerpal CSV data and load it into Supabase")
    parser.add_argument("--export-url", default=None, help="Powerpal CSV export URL from the app")
    parser.add_argument("--start", type=_parse_date, default=None, help="Start date YYYY-MM-DD Australia/Sydney")
    parser.add_argument("--end", type=_parse_date, default=None, help="End date YYYY-MM-DD Australia/Sydney, inclusive")
    parser.add_argument("--days-back", type=int, default=14, help="Rolling window when start/end are omitted")
    parser.add_argument("--window-days", type=int, default=90)
    parser.add_argument("--out-dir", type=Path, default=Path("data_raw/powerpal_minute"))
    parser.add_argument("--manifest", type=Path, default=None, help="Manifest to load; defaults under out-dir")
    parser.add_argument("--site-id", default=None, help="Supabase site id; defaults to AMBER_SITE_ID")
    parser.add_argument("--source", default="powerpal")
    parser.add_argument("--channel-type", default="general")
    parser.add_argument("--overwrite", choices=["true", "false"], default="true")
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument("--download-only", action="store_true")
    parser.add_argument("--skip-when-unconfigured", action="store_true", default=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    export_url = args.export_url or os.getenv("POWERPAL_EXPORT_URL")

    if not _has_powerpal_config(export_url):
        message = "POWERPAL_DEVICE_ID/POWERPAL_TOKEN or --export-url/POWERPAL_EXPORT_URL is required"
        if args.skip_when_unconfigured:
            print(f"Skipping Powerpal refresh: {message}")
            return 0
        print(f"ERROR: {message}", file=sys.stderr)
        return 1

    if args.start or args.end:
        if not args.start or not args.end:
            print("ERROR: --start and --end must be supplied together", file=sys.stderr)
            return 1
        start = args.start
        end = args.end
    elif export_url:
        try:
            export_values = parse_export_url(export_url)
        except Exception as exc:
            print(f"ERROR: Could not parse Powerpal export URL: {exc}", file=sys.stderr)
            return 1
        start = export_values.get("start")
        end = export_values.get("end")
        if not isinstance(start, date) or not isinstance(end, date):
            print("ERROR: --start and --end are required unless export URL includes start/end", file=sys.stderr)
            return 1
    else:
        end = date.today()
        start = end - timedelta(days=args.days_back)

    manifest = args.manifest or (args.out_dir / "manifest_powerpal_minute.csv")

    if not args.skip_download:
        pull_cmd = [
            sys.executable,
            str(project_root / "scripts" / "pull_powerpal_minute_csv.py"),
            "--start",
            start.isoformat(),
            "--end",
            end.isoformat(),
            "--window-days",
            str(args.window_days),
            "--out-dir",
            str(args.out_dir),
            "--overwrite",
            args.overwrite,
        ]
        if export_url:
            pull_cmd.extend(["--export-url", export_url])
        result = run_command(pull_cmd, args.dry_run)
        if result != 0:
            return result

    if args.download_only:
        print("Download complete; skipping Supabase load.")
        return 0

    if not args.dry_run and not os.getenv("SUPABASE_DB_URL"):
        print("ERROR: SUPABASE_DB_URL environment variable is required for load", file=sys.stderr)
        return 1

    load_cmd = [
        sys.executable,
        str(project_root / "scripts" / "load_powerpal_minute_to_supabase.py"),
        "--manifest",
        str(manifest),
        "--source",
        args.source,
        "--channel-type",
        args.channel_type,
    ]
    if args.site_id:
        load_cmd.extend(["--site-id", args.site_id])
    if args.dry_run:
        load_cmd.append("--dry-run")

    return run_command(load_cmd, args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
