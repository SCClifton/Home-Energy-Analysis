#!/usr/bin/env python3
"""
Smoke test script for Supabase Postgres connection.
Loads .env.local and runs a simple "SELECT NOW()" query.
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
    # Load .env.local from project root
    env_path = project_root / ".env.local"
    if not env_path.exists():
        print(f"Error: .env.local not found at {env_path}")
        print("Please create .env.local with SUPABASE_DB_URL=...")
        sys.exit(1)
    
    load_dotenv(env_path)
    
    # Check for required env var
    if not os.environ.get("SUPABASE_DB_URL"):
        print("Error: SUPABASE_DB_URL not found in .env.local")
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

