"""
SQLite cache for Amber API price and usage data.
"""
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any
from importlib import resources


def init_db(db_path: str) -> None:
    """
    Initialize the SQLite database by creating parent directories and tables.
    
    Args:
        db_path: Path to the SQLite database file
    """
    # Create parent directories if they don't exist
    db_file = Path(db_path)
    db_file.parent.mkdir(parents=True, exist_ok=True)
    
    # Read schema file using importlib.resources (works when installed as package)
    try:
        # Python 3.9+ style
        schema_text = resources.files(__package__).joinpath("sqlite_schema.sql").read_text(encoding="utf-8")
    except AttributeError:
        # Fallback for older Python versions
        with resources.open_text(__package__, "sqlite_schema.sql", encoding="utf-8") as f:
            schema_text = f.read()
    
    # Create connection and execute schema
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(schema_text)
        conn.commit()
        
        # Run idempotent migrations for existing databases
        _migrate_usage_table(conn)
        conn.commit()
    finally:
        conn.close()


def _migrate_usage_table(conn: sqlite3.Connection) -> None:
    """
    Idempotent migration to add cost_aud, quality, channel_identifier columns to usage table.
    Safe to run multiple times - checks for column existence before adding.
    """
    cursor = conn.cursor()
    
    # Get existing columns
    cursor.execute("PRAGMA table_info(usage)")
    existing_columns = {row[1] for row in cursor.fetchall()}
    
    # Add missing columns if they don't exist
    if "cost_aud" not in existing_columns:
        cursor.execute("ALTER TABLE usage ADD COLUMN cost_aud REAL")
    
    if "quality" not in existing_columns:
        cursor.execute("ALTER TABLE usage ADD COLUMN quality TEXT")
    
    if "channel_identifier" not in existing_columns:
        cursor.execute("ALTER TABLE usage ADD COLUMN channel_identifier TEXT")


def upsert_prices(db_path: str, rows: List[Dict[str, Any]]) -> None:
    """
    Insert or update price rows in the database.
    
    Args:
        db_path: Path to the SQLite database file
        rows: List of dictionaries with keys: site_id, interval_start, interval_end,
              channel_type, per_kwh, renewables (optional), descriptor (optional)
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        updated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        
        for row in rows:
            cursor.execute("""
                INSERT INTO prices (
                    site_id, interval_start, interval_end, channel_type,
                    per_kwh, renewables, descriptor, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (site_id, interval_start, channel_type)
                DO UPDATE SET
                    interval_end = excluded.interval_end,
                    per_kwh = excluded.per_kwh,
                    renewables = excluded.renewables,
                    descriptor = excluded.descriptor,
                    updated_at = excluded.updated_at
            """, (
                row["site_id"],
                row["interval_start"],
                row["interval_end"],
                row["channel_type"],
                row["per_kwh"],
                row.get("renewables"),
                row.get("descriptor"),
                updated_at
            ))
        
        conn.commit()
    finally:
        conn.close()


def upsert_usage(db_path: str, rows: List[Dict[str, Any]]) -> None:
    """
    Insert or update usage rows in the database.
    
    Args:
        db_path: Path to the SQLite database file
        rows: List of dictionaries with keys: site_id, interval_start, interval_end,
              channel_type, kwh, and optionally cost_aud, quality, channel_identifier
    """
    conn = sqlite3.connect(db_path)
    try:
        # Ensure migrations are run (idempotent)
        _migrate_usage_table(conn)
        conn.commit()
        
        cursor = conn.cursor()
        updated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        
        for row in rows:
            cursor.execute("""
                INSERT INTO usage (
                    site_id, interval_start, interval_end, channel_type,
                    kwh, cost_aud, quality, channel_identifier, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (site_id, interval_start, channel_type)
                DO UPDATE SET
                    interval_end = excluded.interval_end,
                    kwh = excluded.kwh,
                    cost_aud = excluded.cost_aud,
                    quality = excluded.quality,
                    channel_identifier = excluded.channel_identifier,
                    updated_at = excluded.updated_at
            """, (
                row["site_id"],
                row["interval_start"],
                row["interval_end"],
                row["channel_type"],
                row["kwh"],
                row.get("cost_aud"),
                row.get("quality"),
                row.get("channel_identifier"),
                updated_at
            ))
        
        conn.commit()
    finally:
        conn.close()


def get_latest_price(db_path: str, site_id: str, channel_type: str = "general", max_interval_start: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Get the latest price row for a given site and channel type.
    
    Only considers intervals that have started (interval_start <= max_interval_start if provided).
    This prevents selecting future intervals cached for forecast purposes.
    
    Args:
        db_path: Path to the SQLite database file
        site_id: Site ID to query
        channel_type: Channel type (default: "general")
        max_interval_start: Maximum interval_start (ISO8601 string). If None, no time filter is applied.
        
    Returns:
        Dictionary with price data or None if not found
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        if max_interval_start:
            cursor.execute("""
                SELECT site_id, interval_start, interval_end, channel_type,
                       per_kwh, renewables, descriptor, updated_at
                FROM prices
                WHERE site_id = ? AND channel_type = ? AND interval_start <= ?
                ORDER BY interval_start DESC
                LIMIT 1
            """, (site_id, channel_type, max_interval_start))
        else:
            cursor.execute("""
                SELECT site_id, interval_start, interval_end, channel_type,
                       per_kwh, renewables, descriptor, updated_at
                FROM prices
                WHERE site_id = ? AND channel_type = ?
                ORDER BY interval_start DESC
                LIMIT 1
            """, (site_id, channel_type))
        
        row = cursor.fetchone()
        if row is None:
            return None
        
        return {
            "site_id": row[0],
            "interval_start": row[1],
            "interval_end": row[2],
            "channel_type": row[3],
            "per_kwh": row[4],
            "renewables": row[5],
            "descriptor": row[6],
            "updated_at": row[7]
        }
    finally:
        conn.close()


def get_latest_usage(db_path: str, site_id: str, channel_type: str = "general", max_interval_start: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Get the latest usage row for a given site and channel type.
    
    Only considers intervals that have started (interval_start <= max_interval_start if provided).
    This prevents selecting future intervals (usage should never be future, but keeps logic consistent).
    
    Args:
        db_path: Path to the SQLite database file
        site_id: Site ID to query
        channel_type: Channel type (default: "general")
        max_interval_start: Maximum interval_start (ISO8601 string). If None, no time filter is applied.
        
    Returns:
        Dictionary with usage data or None if not found
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        if max_interval_start:
            cursor.execute("""
                SELECT site_id, interval_start, interval_end, channel_type,
                       kwh, updated_at
                FROM usage
                WHERE site_id = ? AND channel_type = ? AND interval_start <= ?
                ORDER BY interval_start DESC
                LIMIT 1
            """, (site_id, channel_type, max_interval_start))
        else:
            cursor.execute("""
                SELECT site_id, interval_start, interval_end, channel_type,
                       kwh, updated_at
                FROM usage
                WHERE site_id = ? AND channel_type = ?
                ORDER BY interval_start DESC
                LIMIT 1
            """, (site_id, channel_type))
        
        row = cursor.fetchone()
        if row is None:
            return None
        
        return {
            "site_id": row[0],
            "interval_start": row[1],
            "interval_end": row[2],
            "channel_type": row[3],
            "kwh": row[4],
            "updated_at": row[5]
        }
    finally:
        conn.close()


def get_price_for_interval(db_path: str, site_id: str, interval_start: str, channel_type: str = "general") -> Optional[Dict[str, Any]]:
    """
    Get a price row for a specific interval.
    
    Supports legacy :01Z timestamps by trying exact match first, then +1 second fallback.
    This allows reading cached rows with legacy :01Z timestamps when querying for :00Z.
    
    Args:
        db_path: Path to the SQLite database file
        site_id: Site ID to query
        interval_start: Interval start time (ISO8601 string, normalized :00Z)
        channel_type: Channel type (default: "general")
        
    Returns:
        Dictionary with price data or None if not found
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        
        # Try exact match first (preferred :00Z format)
        cursor.execute("""
            SELECT site_id, interval_start, interval_end, channel_type,
                   per_kwh, renewables, descriptor, updated_at
            FROM prices
            WHERE site_id = ? AND interval_start = ? AND channel_type = ?
            LIMIT 1
        """, (site_id, interval_start, channel_type))
        
        row = cursor.fetchone()
        if row is not None:
            return {
                "site_id": row[0],
                "interval_start": row[1],
                "interval_end": row[2],
                "channel_type": row[3],
                "per_kwh": row[4],
                "renewables": row[5],
                "descriptor": row[6],
                "updated_at": row[7]
            }
        
        # Fallback: try legacy :01Z pattern (target + 1 second)
        # Parse ISO timestamp, add 1 second, format back
        try:
            dt = datetime.fromisoformat(interval_start.replace("Z", "+00:00"))
            legacy_interval_start = (dt + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
        except Exception:
            # If parsing fails, return None
            return None
        
        cursor.execute("""
            SELECT site_id, interval_start, interval_end, channel_type,
                   per_kwh, renewables, descriptor, updated_at
            FROM prices
            WHERE site_id = ? AND interval_start = ? AND channel_type = ?
            LIMIT 1
        """, (site_id, legacy_interval_start, channel_type))
        
        row = cursor.fetchone()
        if row is None:
            return None
        
        return {
            "site_id": row[0],
            "interval_start": row[1],
            "interval_end": row[2],
            "channel_type": row[3],
            "per_kwh": row[4],
            "renewables": row[5],
            "descriptor": row[6],
            "updated_at": row[7]
        }
    finally:
        conn.close()


def get_usage_for_interval(db_path: str, site_id: str, interval_start: str, channel_type: str = "general") -> Optional[Dict[str, Any]]:
    """
    Get a usage row for a specific interval.
    
    Supports legacy :01Z timestamps by trying exact match first, then +1 second fallback.
    This allows reading cached rows with legacy :01Z timestamps when querying for :00Z.
    
    Args:
        db_path: Path to the SQLite database file
        site_id: Site ID to query
        interval_start: Interval start time (ISO8601 string, normalized :00Z)
        channel_type: Channel type (default: "general")
        
    Returns:
        Dictionary with usage data or None if not found
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        
        # Try exact match first (preferred :00Z format)
        cursor.execute("""
            SELECT site_id, interval_start, interval_end, channel_type,
                   kwh, updated_at
            FROM usage
            WHERE site_id = ? AND interval_start = ? AND channel_type = ?
            LIMIT 1
        """, (site_id, interval_start, channel_type))
        
        row = cursor.fetchone()
        if row is not None:
            return {
                "site_id": row[0],
                "interval_start": row[1],
                "interval_end": row[2],
                "channel_type": row[3],
                "kwh": row[4],
                "updated_at": row[5]
            }
        
        # Fallback: try legacy :01Z pattern (target + 1 second)
        # Parse ISO timestamp, add 1 second, format back
        try:
            dt = datetime.fromisoformat(interval_start.replace("Z", "+00:00"))
            legacy_interval_start = (dt + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
        except Exception:
            # If parsing fails, return None
            return None
        
        cursor.execute("""
            SELECT site_id, interval_start, interval_end, channel_type,
                   kwh, updated_at
            FROM usage
            WHERE site_id = ? AND interval_start = ? AND channel_type = ?
            LIMIT 1
        """, (site_id, legacy_interval_start, channel_type))
        
        row = cursor.fetchone()
        if row is None:
            return None
        
        return {
            "site_id": row[0],
            "interval_start": row[1],
            "interval_end": row[2],
            "channel_type": row[3],
            "kwh": row[4],
            "updated_at": row[5]
        }
    finally:
        conn.close()


def get_forecast_intervals(db_path: str, site_id: str, channel_type: str = "general", max_intervals: int = 24) -> List[Dict[str, Any]]:
    """
    Get forecast intervals (future prices) from cache.
    
    Args:
        db_path: Path to the SQLite database file
        site_id: Site ID to query
        channel_type: Channel type (default: "general")
        max_intervals: Maximum number of intervals to return
        
    Returns:
        List of price dictionaries sorted by interval_start ASC
    """
    now_utc = datetime.now(timezone.utc)
    now_str = now_utc.isoformat().replace("+00:00", "Z")
    
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT site_id, interval_start, interval_end, channel_type,
                   per_kwh, renewables, descriptor, updated_at
            FROM prices
            WHERE site_id = ? AND channel_type = ? AND interval_start > ?
            ORDER BY interval_start ASC
            LIMIT ?
        """, (site_id, channel_type, now_str, max_intervals))
        
        rows = cursor.fetchall()
        return [
            {
                "site_id": row[0],
                "interval_start": row[1],
                "interval_end": row[2],
                "channel_type": row[3],
                "per_kwh": row[4],
                "renewables": row[5],
                "descriptor": row[6],
                "updated_at": row[7]
            }
            for row in rows
        ]
    finally:
        conn.close()


def upsert_irradiance(db_path: str, rows: List[Dict[str, Any]]) -> None:
    """
    Insert or update irradiance rows.

    Args:
        db_path: Path to SQLite database.
        rows: List of dictionaries with keys:
            location_id, interval_start, interval_end, ghi_wm2 and optional
            temperature_c, cloud_cover_pct, source.
    """
    if not rows:
        return

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        updated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        for row in rows:
            cursor.execute(
                """
                INSERT INTO irradiance (
                    location_id, interval_start, interval_end, ghi_wm2,
                    temperature_c, cloud_cover_pct, source, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (location_id, interval_start)
                DO UPDATE SET
                    interval_end = excluded.interval_end,
                    ghi_wm2 = excluded.ghi_wm2,
                    temperature_c = excluded.temperature_c,
                    cloud_cover_pct = excluded.cloud_cover_pct,
                    source = excluded.source,
                    updated_at = excluded.updated_at
                """,
                (
                    row["location_id"],
                    row["interval_start"],
                    row["interval_end"],
                    row["ghi_wm2"],
                    row.get("temperature_c"),
                    row.get("cloud_cover_pct"),
                    row.get("source", "open-meteo"),
                    updated_at,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def get_irradiance_range(
    db_path: str,
    location_id: str,
    start_interval: str,
    end_interval: str,
) -> List[Dict[str, Any]]:
    """
    Get irradiance rows in [start_interval, end_interval).
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                location_id, interval_start, interval_end, ghi_wm2,
                temperature_c, cloud_cover_pct, source, updated_at
            FROM irradiance
            WHERE location_id = ? AND interval_start >= ? AND interval_start < ?
            ORDER BY interval_start ASC
            """,
            (location_id, start_interval, end_interval),
        )
        rows = cursor.fetchall()
        return [
            {
                "location_id": row[0],
                "interval_start": row[1],
                "interval_end": row[2],
                "ghi_wm2": row[3],
                "temperature_c": row[4],
                "cloud_cover_pct": row[5],
                "source": row[6],
                "updated_at": row[7],
            }
            for row in rows
        ]
    finally:
        conn.close()


def upsert_simulation_intervals(db_path: str, rows: List[Dict[str, Any]]) -> None:
    """
    Insert or update simulation interval rows.
    """
    if not rows:
        return

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        updated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        for row in rows:
            cursor.execute(
                """
                INSERT INTO simulation_intervals (
                    scenario_id, controller_mode, interval_start, interval_end,
                    baseline_import_kwh, scenario_import_kwh, battery_charge_kwh,
                    battery_discharge_kwh, battery_soc_kwh, pv_generation_kwh,
                    export_kwh, baseline_cost_aud, scenario_cost_aud, savings_aud,
                    forecast, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (scenario_id, controller_mode, interval_start)
                DO UPDATE SET
                    interval_end = excluded.interval_end,
                    baseline_import_kwh = excluded.baseline_import_kwh,
                    scenario_import_kwh = excluded.scenario_import_kwh,
                    battery_charge_kwh = excluded.battery_charge_kwh,
                    battery_discharge_kwh = excluded.battery_discharge_kwh,
                    battery_soc_kwh = excluded.battery_soc_kwh,
                    pv_generation_kwh = excluded.pv_generation_kwh,
                    export_kwh = excluded.export_kwh,
                    baseline_cost_aud = excluded.baseline_cost_aud,
                    scenario_cost_aud = excluded.scenario_cost_aud,
                    savings_aud = excluded.savings_aud,
                    forecast = excluded.forecast,
                    updated_at = excluded.updated_at
                """,
                (
                    row["scenario_id"],
                    row["controller_mode"],
                    row["interval_start"],
                    row["interval_end"],
                    row["baseline_import_kwh"],
                    row["scenario_import_kwh"],
                    row["battery_charge_kwh"],
                    row["battery_discharge_kwh"],
                    row["battery_soc_kwh"],
                    row["pv_generation_kwh"],
                    row["export_kwh"],
                    row["baseline_cost_aud"],
                    row["scenario_cost_aud"],
                    row["savings_aud"],
                    1 if row.get("forecast", False) else 0,
                    updated_at,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def get_simulation_intervals(
    db_path: str,
    scenario_id: str,
    controller_mode: str,
    start_interval: str,
    end_interval: str,
    limit: int = 5000,
) -> List[Dict[str, Any]]:
    """
    Get simulation intervals in [start_interval, end_interval), sorted by interval_start.
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                scenario_id, controller_mode, interval_start, interval_end,
                baseline_import_kwh, scenario_import_kwh, battery_charge_kwh,
                battery_discharge_kwh, battery_soc_kwh, pv_generation_kwh,
                export_kwh, baseline_cost_aud, scenario_cost_aud, savings_aud,
                forecast, updated_at
            FROM simulation_intervals
            WHERE scenario_id = ?
              AND controller_mode = ?
              AND interval_start >= ?
              AND interval_start < ?
            ORDER BY interval_start ASC
            LIMIT ?
            """,
            (scenario_id, controller_mode, start_interval, end_interval, limit),
        )
        rows = cursor.fetchall()
        return [
            {
                "scenario_id": row[0],
                "controller_mode": row[1],
                "interval_start": row[2],
                "interval_end": row[3],
                "baseline_import_kwh": row[4],
                "scenario_import_kwh": row[5],
                "battery_charge_kwh": row[6],
                "battery_discharge_kwh": row[7],
                "battery_soc_kwh": row[8],
                "pv_generation_kwh": row[9],
                "export_kwh": row[10],
                "baseline_cost_aud": row[11],
                "scenario_cost_aud": row[12],
                "savings_aud": row[13],
                "forecast": bool(row[14]),
                "updated_at": row[15],
            }
            for row in rows
        ]
    finally:
        conn.close()


def upsert_simulation_run(db_path: str, run_row: Dict[str, Any]) -> None:
    """
    Upsert latest simulation summary row for a scenario/controller/mode.
    """
    assumptions_json = run_row.get("assumptions_json")
    if assumptions_json is not None and not isinstance(assumptions_json, str):
        assumptions_json = json.dumps(assumptions_json, sort_keys=True)

    updated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO simulation_runs (
                scenario_id, controller_mode, run_mode,
                as_of, window_start, window_end,
                today_savings_aud, mtd_savings_aud, next_24h_projected_savings_aud,
                current_battery_soc_kwh, today_solar_generation_kwh, today_export_revenue_aud,
                stale, stale_reason, assumptions_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (scenario_id, controller_mode, run_mode)
            DO UPDATE SET
                as_of = excluded.as_of,
                window_start = excluded.window_start,
                window_end = excluded.window_end,
                today_savings_aud = excluded.today_savings_aud,
                mtd_savings_aud = excluded.mtd_savings_aud,
                next_24h_projected_savings_aud = excluded.next_24h_projected_savings_aud,
                current_battery_soc_kwh = excluded.current_battery_soc_kwh,
                today_solar_generation_kwh = excluded.today_solar_generation_kwh,
                today_export_revenue_aud = excluded.today_export_revenue_aud,
                stale = excluded.stale,
                stale_reason = excluded.stale_reason,
                assumptions_json = excluded.assumptions_json,
                updated_at = excluded.updated_at
            """,
            (
                run_row["scenario_id"],
                run_row["controller_mode"],
                run_row["run_mode"],
                run_row["as_of"],
                run_row["window_start"],
                run_row["window_end"],
                run_row["today_savings_aud"],
                run_row["mtd_savings_aud"],
                run_row["next_24h_projected_savings_aud"],
                run_row["current_battery_soc_kwh"],
                run_row["today_solar_generation_kwh"],
                run_row["today_export_revenue_aud"],
                1 if run_row.get("stale", False) else 0,
                run_row.get("stale_reason"),
                assumptions_json,
                updated_at,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_latest_simulation_run(
    db_path: str,
    scenario_id: str,
    controller_mode: str,
    run_mode: str = "live",
) -> Optional[Dict[str, Any]]:
    """
    Fetch latest simulation summary row for scenario/controller/mode.
    """
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                scenario_id, controller_mode, run_mode,
                as_of, window_start, window_end,
                today_savings_aud, mtd_savings_aud, next_24h_projected_savings_aud,
                current_battery_soc_kwh, today_solar_generation_kwh, today_export_revenue_aud,
                stale, stale_reason, assumptions_json, updated_at
            FROM simulation_runs
            WHERE scenario_id = ?
              AND controller_mode = ?
              AND run_mode = ?
            LIMIT 1
            """,
            (scenario_id, controller_mode, run_mode),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        assumptions = row[14]
        try:
            assumptions = json.loads(assumptions) if assumptions else None
        except json.JSONDecodeError:
            assumptions = assumptions
        return {
            "scenario_id": row[0],
            "controller_mode": row[1],
            "run_mode": row[2],
            "as_of": row[3],
            "window_start": row[4],
            "window_end": row[5],
            "today_savings_aud": row[6],
            "mtd_savings_aud": row[7],
            "next_24h_projected_savings_aud": row[8],
            "current_battery_soc_kwh": row[9],
            "today_solar_generation_kwh": row[10],
            "today_export_revenue_aud": row[11],
            "stale": bool(row[12]),
            "stale_reason": row[13],
            "assumptions": assumptions,
            "updated_at": row[15],
        }
    finally:
        conn.close()


def prune_old_data(db_path: str, retention_days: int) -> int:
    """
    Delete rows older than the retention period.
    
    Args:
        db_path: Path to the SQLite database file
        retention_days: Number of days to retain data
    
    Returns:
        Number of rows deleted (from both tables combined)
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    cutoff_str = cutoff.isoformat().replace("+00:00", "Z")
    
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        
        # Delete old prices
        cursor.execute("""
            DELETE FROM prices
            WHERE interval_start < ?
        """, (cutoff_str,))
        prices_deleted = cursor.rowcount
        
        # Delete old usage
        cursor.execute("""
            DELETE FROM usage
            WHERE interval_start < ?
        """, (cutoff_str,))
        usage_deleted = cursor.rowcount
        
        conn.commit()
        return prices_deleted + usage_deleted
    finally:
        conn.close()
