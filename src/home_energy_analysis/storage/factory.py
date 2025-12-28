"""
Factory function for getting SQLite cache instance.
"""
import os
from pathlib import Path
from . import sqlite_cache


_initialized = False
_db_path = None


def get_sqlite_cache() -> str:
    """
    Get the SQLite database path, initializing the database if needed.
    
    Reads SQLITE_PATH environment variable or defaults to ./data_local/cache.sqlite.
    Initializes the database (creates tables) on first call.
    
    Returns:
        Path to the SQLite database file
    """
    global _initialized, _db_path
    
    if _db_path is None:
        _db_path = os.getenv("SQLITE_PATH")
        if _db_path is None:
            # Default to ./data_local/cache.sqlite relative to project root
            # Path: src/home_energy_analysis/storage/factory.py -> src -> project root
            project_root = Path(__file__).parent.parent.parent.parent
            _db_path = str(project_root / "data_local" / "cache.sqlite")
    
    if not _initialized:
        sqlite_cache.init_db(_db_path)
        _initialized = True
    
    return _db_path

