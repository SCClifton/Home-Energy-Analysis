#!/usr/bin/env python3
"""
Supabase keepalive probe.

Runs a lightweight query to keep the Supabase project warm and verify connectivity.
Intended for systemd timer execution on the Raspberry Pi.
"""
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Add project root to path
project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root / "src"))

from home_energy_analysis.storage import supabase_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def main() -> int:
    # For local/dev use, allow .env.local fallback. On Pi, systemd should provide env.
    load_dotenv(project_root / ".env.local", override=False)

    if not os.getenv("SUPABASE_DB_URL"):
        logger.error("SUPABASE_DB_URL environment variable is required")
        return 1

    try:
        conn = supabase_db.get_conn()
    except Exception as exc:
        logger.error("Failed to open Supabase connection: %s", exc)
        return 1

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT NOW()")
            now_row = cur.fetchone()
        conn.close()
        logger.info("Supabase keepalive ok (db_time=%s)", now_row[0] if now_row else "unknown")
        return 0
    except Exception as exc:
        logger.error("Supabase keepalive query failed: %s", exc)
        try:
            conn.close()
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
