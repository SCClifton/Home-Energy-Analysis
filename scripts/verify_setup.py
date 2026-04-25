#!/usr/bin/env python3
"""Smoke checks for local/Pi Home Energy Analysis runtime state."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

from dotenv import load_dotenv

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from home_energy_analysis.storage import sqlite_cache, supabase_db


@dataclass
class CheckResult:
    name: str
    status: str
    detail: str


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _age_text(value: Optional[str]) -> str:
    dt = _parse_iso(value)
    if not dt:
        return "unknown age"
    seconds = max(0, int((datetime.now(timezone.utc) - dt).total_seconds()))
    if seconds < 3600:
        return f"{seconds // 60}m old"
    if seconds < 86400:
        return f"{seconds // 3600}h old"
    return f"{seconds // 86400}d old"


def _result(name: str, ok: bool, detail: str, warn: bool = False) -> CheckResult:
    status = "PASS" if ok else ("WARN" if warn else "FAIL")
    return CheckResult(name, status, detail)


def check_sqlite(db_path: Path, site_id: str, stale_hours: int) -> CheckResult:
    try:
        sqlite_cache.init_db(str(db_path))
        latest_price = sqlite_cache.get_latest_price(str(db_path), site_id)
        latest_usage = sqlite_cache.get_latest_usage(str(db_path), site_id)
    except Exception as exc:
        return _result("sqlite-cache", False, f"{db_path}: {exc}")

    details: list[str] = [str(db_path)]
    warn = False
    for label, row in (("price", latest_price), ("usage", latest_usage)):
        if row:
            interval = row.get("interval_start")
            details.append(f"{label} {interval} ({_age_text(interval)})")
            dt = _parse_iso(interval)
            if dt and (datetime.now(timezone.utc) - dt).total_seconds() > stale_hours * 3600:
                warn = True
        else:
            warn = True
            details.append(f"{label} missing")

    return _result("sqlite-cache", True, "; ".join(details), warn=warn)


def check_endpoint(base_url: str, path: str, timeout: float) -> CheckResult:
    url = f"{base_url.rstrip('/')}{path}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            data = json.loads(body) if body else {}
            status = data.get("status") or data.get("source") or "ok"
            return _result(f"endpoint {path}", True, f"HTTP {response.status}; status={status}")
    except urllib.error.HTTPError as exc:
        return _result(f"endpoint {path}", False, f"HTTP {exc.code}: {exc.reason}")
    except Exception as exc:
        return _result(f"endpoint {path}", False, str(exc))


def check_supabase() -> CheckResult:
    if not os.getenv("SUPABASE_DB_URL"):
        return _result("supabase", True, "SUPABASE_DB_URL not set; skipped", warn=True)
    try:
        with supabase_db.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT NOW()")
                now = cur.fetchone()[0]
        return _result("supabase", True, f"connected; database time {now}")
    except Exception as exc:
        return _result("supabase", False, str(exc))


def check_systemctl(command: Sequence[str], name: str) -> CheckResult:
    try:
        completed = subprocess.run(
            command,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=8,
        )
    except FileNotFoundError:
        return _result(name, True, "systemctl not available; skipped", warn=True)
    except Exception as exc:
        return _result(name, False, str(exc))

    output = completed.stdout.strip().splitlines()
    detail = output[0] if output else f"exit {completed.returncode}"
    return _result(name, completed.returncode == 0, detail)


def print_results(results: Sequence[CheckResult]) -> int:
    exit_code = 0
    for result in results:
        print(f"[{result.status}] {result.name}: {result.detail}")
        if result.status == "FAIL":
            exit_code = 1
    return exit_code


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run Home Energy Analysis smoke checks")
    parser.add_argument("--base-url", default=os.getenv("DASHBOARD_URL", "http://127.0.0.1:5050"))
    parser.add_argument("--sqlite-path", type=Path, default=Path(os.getenv("SQLITE_PATH", project_root / "data_local" / "cache.sqlite")))
    parser.add_argument("--site-id", default=os.getenv("AMBER_SITE_ID", "smoke-site"))
    parser.add_argument("--timeout", type=float, default=3.0)
    parser.add_argument("--stale-hours", type=int, default=24)
    parser.add_argument("--skip-endpoints", action="store_true")
    parser.add_argument("--skip-supabase", action="store_true")
    parser.add_argument("--pi-systemd", action="store_true", help="Also check Pi systemd units read-only")
    args = parser.parse_args(argv)

    load_dotenv(project_root / ".env.local", override=False)

    results: list[CheckResult] = [
        check_sqlite(args.sqlite_path, args.site_id, args.stale_hours),
    ]

    if not args.skip_endpoints:
        for path in ("/api/health", "/api/price", "/api/totals"):
            results.append(check_endpoint(args.base_url, path, args.timeout))

    if not args.skip_supabase:
        results.append(check_supabase())

    if args.pi_systemd:
        results.extend([
            check_systemctl(["systemctl", "is-active", "home-energy-dashboard.service"], "dashboard-service"),
            check_systemctl(["systemctl", "is-active", "home-energy-sync-cache.timer"], "sync-cache-timer"),
            check_systemctl(["systemctl", "is-active", "home-energy-simulation.timer"], "simulation-timer"),
            check_systemctl(["systemctl", "--user", "is-active", "home-energy-kiosk.service"], "kiosk-service"),
        ])

    return print_results(results)


if __name__ == "__main__":
    raise SystemExit(main())
