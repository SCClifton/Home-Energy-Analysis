#!/usr/bin/env python3
"""
Download Powerpal minute-resolution CSV exports via the CSV export link.

Usage:
    python scripts/pull_powerpal_minute_csv.py --start 2024-10-01 --end 2025-03-31

Environment variables (required):
    POWERPAL_DEVICE_ID (e.g. 0005191c)
    POWERPAL_TOKEN (CSV export token)
    POWERPAL_SAMPLE (default 1)

Output:
    CSV files in data_raw/powerpal_minute/
    Manifest: data_raw/powerpal_minute/manifest_powerpal_minute.csv
"""
import argparse
import hashlib
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List

import pandas as pd
import requests
from dotenv import load_dotenv
from zoneinfo import ZoneInfo

# Load environment variables
project_root = Path(__file__).parent.parent
load_dotenv(project_root / "config/.env", override=False)
load_dotenv(project_root / ".env.local", override=True)

TZ = ZoneInfo("Australia/Sydney")
BASE_URL = "https://readings.powerpal.net/csv/v1"


def parse_yyyy_mm_dd(s: str) -> date:
    """Parse YYYY-MM-DD date string."""
    return datetime.strptime(s, "%Y-%m-%d").date()


def epoch_start(d: date) -> int:
    """Convert date to epoch seconds at 00:00:00 Australia/Sydney."""
    dt = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=TZ)
    return int(dt.timestamp())


def epoch_end(d: date) -> int:
    """Convert date to epoch seconds at 23:59:59 Australia/Sydney."""
    dt = datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=TZ)
    return int(dt.timestamp())


def chunk_ranges(start: date, end: date, max_days: int = 90) -> List[tuple[date, date]]:
    """Split date range into chunks of up to max_days."""
    chunks: List[tuple[date, date]] = []
    cur = start
    while cur <= end:
        chunk_end = min(cur + timedelta(days=max_days - 1), end)
        chunks.append((cur, chunk_end))
        cur = chunk_end + timedelta(days=1)
    return chunks


def build_url(device_id: str, token: str, start_date: date, end_date: date, sample: int) -> str:
    """Build Powerpal CSV export URL."""
    return (
        f"{BASE_URL}/{device_id}"
        f"?token={token}"
        f"&start={epoch_start(start_date)}"
        f"&end={epoch_end(end_date)}"
        f"&sample={sample}"
    )


def redact_token(s: str, token: str) -> str:
    """Redact token from string for logging."""
    if not token:
        return s
    return s.replace(token, "***REDACTED***")


def download_csv(url: str, out_path: Path, timeout: int = 60) -> tuple[int, int, str]:
    """
    Download CSV from URL and save to file.
    
    Returns:
        (http_status, bytes_downloaded, sha256_hash)
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=timeout) as resp:
        status_code = resp.status_code
        resp.raise_for_status()
        content = resp.content
        sha256 = hashlib.sha256(content).hexdigest()
        out_path.write_bytes(content)
        return (status_code, len(content), sha256)


def append_manifest(
    manifest_path: Path,
    file_path: Path,
    start_date: date,
    end_date: date,
    start_epoch: int,
    end_epoch: int,
    http_status: int,
    bytes_downloaded: int,
    sha256: str,
) -> None:
    """Append entry to manifest CSV."""
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Create manifest if it doesn't exist
    if not manifest_path.exists():
        manifest_df = pd.DataFrame(columns=[
            "file", "start_date", "end_date", "start_epoch", "end_epoch",
            "downloaded_at_utc", "sha256", "http_status", "bytes"
        ])
    else:
        manifest_df = pd.read_csv(manifest_path)
    
    # Append new row
    new_row = {
        "file": str(file_path),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "start_epoch": start_epoch,
        "end_epoch": end_epoch,
        "downloaded_at_utc": datetime.utcnow().isoformat() + "Z",
        "sha256": sha256,
        "http_status": http_status,
        "bytes": bytes_downloaded,
    }
    manifest_df = pd.concat([manifest_df, pd.DataFrame([new_row])], ignore_index=True)
    manifest_df.to_csv(manifest_path, index=False)


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Download Powerpal minute-resolution CSV exports"
    )
    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD (Australia/Sydney)")
    parser.add_argument("--end", required=True, help="End date YYYY-MM-DD (Australia/Sydney, inclusive)")
    parser.add_argument("--window-days", type=int, default=90,
                        help="Maximum days per download window (default: 90)")
    parser.add_argument("--out-dir", type=Path, default=Path("data_raw/powerpal_minute"),
                        help="Output directory for CSV files (default: data_raw/powerpal_minute)")
    parser.add_argument("--overwrite", type=str, default="false", choices=["true", "false"],
                        help="Overwrite existing files (default: false)")
    
    args = parser.parse_args()
    
    # Get environment variables
    device_id = os.getenv("POWERPAL_DEVICE_ID")
    token = os.getenv("POWERPAL_TOKEN")
    sample_str = os.getenv("POWERPAL_SAMPLE", "1")
    
    if not device_id or not token:
        print("ERROR: POWERPAL_DEVICE_ID and POWERPAL_TOKEN must be set in environment", file=sys.stderr)
        return 1
    
    try:
        sample = int(sample_str)
    except ValueError:
        print(f"ERROR: POWERPAL_SAMPLE must be an integer, got: {sample_str}", file=sys.stderr)
        return 1
    
    # Parse dates
    start = parse_yyyy_mm_dd(args.start)
    end = parse_yyyy_mm_dd(args.end)
    
    if start > end:
        print(f"ERROR: Start date {start} is after end date {end}", file=sys.stderr)
        return 1
    
    # Parse overwrite flag
    overwrite = args.overwrite.lower() == "true"
    
    # Setup output directory
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "manifest_powerpal_minute.csv"
    
    # Split into windows
    windows = chunk_ranges(start, end, max_days=args.window_days)
    
    print(f"Downloading Powerpal minute CSV data")
    print(f"Device ID: {device_id}")
    print(f"Sample: {sample}")
    print(f"Date range: {start} to {end} ({len(windows)} windows)")
    print(f"Output directory: {out_dir}")
    print()
    
    # Process each window
    for win_start, win_end in windows:
        start_epoch = epoch_start(win_start)
        end_epoch = epoch_end(win_end)
        
        # Build output filename
        out_filename = f"powerpal_{device_id}_{win_start.isoformat()}_{win_end.isoformat()}_sample{sample}.csv"
        out_path = out_dir / out_filename
        
        # Check if file exists
        if out_path.exists() and not overwrite:
            print(f"Skipping {win_start} to {win_end} (file exists: {out_path.name})")
            continue
        
        # Build URL
        url = build_url(device_id, token, win_start, win_end, sample)
        
        # Log (redact token)
        url_log = redact_token(url, token)
        print(f"Downloading {win_start} to {win_end}")
        print(f"  Start epoch: {start_epoch}")
        print(f"  End epoch: {end_epoch}")
        print(f"  URL: {url_log}")
        print(f"  Output: {out_path}")
        
        try:
            # Download
            http_status, bytes_downloaded, sha256 = download_csv(url, out_path)
            
            print(f"  Status: {http_status}")
            print(f"  Bytes: {bytes_downloaded:,}")
            print(f"  SHA256: {sha256}")
            
            # Append to manifest
            append_manifest(
                manifest_path,
                out_path,
                win_start,
                win_end,
                start_epoch,
                end_epoch,
                http_status,
                bytes_downloaded,
                sha256,
            )
            print(f"  ✓ Saved to manifest")
            print()
            
        except requests.RequestException as e:
            print(f"  ✗ Error downloading: {e}", file=sys.stderr)
            return 1
    
    print("=== Done ===")
    print(f"Downloaded {len(windows)} window(s)")
    print(f"Manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

