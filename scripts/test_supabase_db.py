#!/usr/bin/env python3
"""
Smoke test script for Supabase Postgres connection.

Uses current process environment, with optional `.env.local` fallback for local dev.
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from home_energy_analysis.storage import supabase_db


def main():
    """Load environment and test database connection."""
    # Optional local fallback.
    env_path = project_root / ".env.local"
    if env_path.exists():
        load_dotenv(env_path, override=False)
    
    # Check for required env var
    if not os.environ.get("SUPABASE_DB_URL"):
        print("Error: SUPABASE_DB_URL environment variable is required")
        sys.exit(1)
    
    # Test connection
    try:
        conn = supabase_db.get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT NOW() as current_time")
            result = cur.fetchone()
            print(f"✓ Connection successful!")
            print(f"  Current database time: {result[0]}")
        conn.close()
    except Exception as e:
        print(f"✗ Connection failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
