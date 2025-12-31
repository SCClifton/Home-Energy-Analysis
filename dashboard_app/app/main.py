import os
from datetime import datetime, timezone, timedelta
from flask import Flask, jsonify, render_template, Response
import sys
import sqlite3
from zoneinfo import ZoneInfo

# Add parent directory to path to import amber_client
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
from ingestion.amber_client import AmberClient, AmberAPIError

# Note: Developers must run 'pip install -e .' to use the packaged cache module
from home_energy_analysis.storage.factory import get_sqlite_cache
from home_energy_analysis.storage import sqlite_cache

# Initialize cache (lazy, but we'll call get_sqlite_cache() in handlers)
_cache_path = None


def _get_cache_path():
    """Get the cache database path, initializing if needed."""
    global _cache_path
    if _cache_path is None:
        _cache_path = get_sqlite_cache()
    return _cache_path


def _reset_cache_path():
    """Reset the cached path (useful for testing)."""
    global _cache_path
    _cache_path = None


def parse_iso_z(ts: str) -> datetime:
    """Parse ISO8601 timestamp with trailing 'Z' to datetime."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def floor_to_5min(dt: datetime) -> datetime:
    """
    Floor a datetime to the nearest 5-minute boundary in UTC.
    Strip seconds and microseconds.
    
    Args:
        dt: Datetime to floor (assumed to be timezone-aware, will convert to UTC)
        
    Returns:
        Datetime floored to 5-minute boundary in UTC
    """
    # Ensure UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    
    # Floor to 5-minute boundary: remove seconds/microseconds, floor minute
    floored_minute = (dt.minute // 5) * 5
    return dt.replace(minute=floored_minute, second=0, microsecond=0)


def normalize_interval_timestamp(ts: str) -> str:
    """
    Normalize an ISO8601 timestamp string to a 5-minute boundary.
    
    Args:
        ts: ISO8601 timestamp string (e.g., "2024-01-01T01:50:01Z")
        
    Returns:
        Normalized ISO8601 timestamp string (e.g., "2024-01-01T01:50:00Z")
    """
    dt = parse_iso_z(ts)
    normalized = floor_to_5min(dt)
    return normalized.isoformat().replace("+00:00", "Z")


def is_fresh(interval_start: str, max_age_seconds: int = 900) -> bool:
    """Check if an interval_start timestamp is within max_age_seconds of now (UTC)."""
    try:
        interval_dt = parse_iso_z(interval_start)
        now = datetime.now(timezone.utc)
        delta = now - interval_dt
        return delta.total_seconds() <= max_age_seconds
    except Exception:
        # Conservative: treat parsing errors as stale
        return False

def create_app() -> Flask:
    app = Flask(__name__)

    @app.get("/api/price")
    def get_price():
        """Fetch current price from Amber API (live-first) with cache fallback."""
        token = os.getenv("AMBER_TOKEN")
        site_id = os.getenv("AMBER_SITE_ID")
        channel_type = "general"
        
        if not site_id:
            return jsonify({"error": "AMBER_SITE_ID environment variable is not set"}), 500
        
        cache_path = _get_cache_path()
        
        # Compute current 5-minute interval
        now_utc = datetime.now(timezone.utc)
        current_interval_start = floor_to_5min(now_utc)
        current_interval_start_str = current_interval_start.isoformat().replace("+00:00", "Z")
        
        # Try live API first if credentials are available
        cached_row = None
        if token:
            try:
                # Create client with short timeout for responsiveness
                client = AmberClient(token=token, timeout=2)
                prices = client.get_prices_current(site_id)
                
                if prices:
                    # Find the "general" channel interval for current
                    current = None
                    for price in prices:
                        if price.get("channelType") == channel_type or price.get("channelType") == "general":
                            # Check if this is the current interval
                            price_start = price.get("startTime")
                            if price_start:
                                price_start_normalized = normalize_interval_timestamp(price_start)
                                if price_start_normalized == current_interval_start_str:
                                    current = price
                                    break
                    
                    # If no exact match, use first interval
                    if not current and prices:
                        current = prices[0]
                    
                    if current:
                        interval_start_raw = current.get("startTime")
                        interval_end_raw = current.get("endTime")
                        
                        # Normalize timestamps before caching
                        interval_start = normalize_interval_timestamp(interval_start_raw)
                        interval_end = normalize_interval_timestamp(interval_end_raw)
                        
                        # Cache the price row
                        try:
                            cache_row = {
                                "site_id": site_id,
                                "interval_start": interval_start,
                                "interval_end": interval_end,
                                "channel_type": channel_type,
                                "per_kwh": current.get("perKwh"),
                                "renewables": current.get("renewables"),
                                "descriptor": current.get("descriptor")
                            }
                            sqlite_cache.upsert_prices(cache_path, [cache_row])
                        except Exception:
                            # Cache write failure is non-fatal
                            pass
                        
                        response = jsonify({
                            "site_id": site_id,
                            "per_kwh": current.get("perKwh"),
                            "interval_start": interval_start,
                            "interval_end": interval_end,
                            "renewables": current.get("renewables"),
                            "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                        })
                        response.headers["X-Data-Source"] = "live"
                        response.headers["X-Cache-Stale"] = "false"
                        return response
            except (AmberAPIError, Exception) as e:
                # Live API failed - fall through to cache
                pass
        
        # Fallback to cache: try exact interval first
        try:
            cached_row = sqlite_cache.get_price_for_interval(cache_path, site_id, current_interval_start_str, channel_type)
            if cached_row:
                interval_start = normalize_interval_timestamp(cached_row["interval_start"])
                interval_end = normalize_interval_timestamp(cached_row["interval_end"])
                
                # Calculate age
                cached_dt = parse_iso_z(interval_end)
                age_seconds = int((now_utc - cached_dt).total_seconds())
                is_stale = age_seconds > 900
                
                response = jsonify({
                    "site_id": cached_row["site_id"],
                    "per_kwh": cached_row["per_kwh"],
                    "interval_start": interval_start,
                    "interval_end": interval_end,
                    "renewables": cached_row.get("renewables"),
                    "is_stale": is_stale,
                    "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                })
                response.headers["X-Data-Source"] = "cache"
                response.headers["X-Cache-Stale"] = "true" if is_stale else "false"
                return response
        except Exception:
            pass
        
        # Try latest cached price as final fallback
        try:
            cached_row = sqlite_cache.get_latest_price(cache_path, site_id, channel_type)
            if cached_row:
                interval_start = normalize_interval_timestamp(cached_row["interval_start"])
                interval_end = normalize_interval_timestamp(cached_row["interval_end"])
                
                # Calculate age
                cached_dt = parse_iso_z(interval_end)
                age_seconds = int((now_utc - cached_dt).total_seconds())
                is_stale = age_seconds > 900
                
                response = jsonify({
                    "site_id": cached_row["site_id"],
                    "per_kwh": cached_row["per_kwh"],
                    "interval_start": interval_start,
                    "interval_end": interval_end,
                    "renewables": cached_row.get("renewables"),
                    "is_stale": is_stale,
                    "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                })
                response.headers["X-Data-Source"] = "cache"
                response.headers["X-Cache-Stale"] = "true" if is_stale else "false"
                return response
        except Exception:
            pass
        
        # No data available
        return jsonify({"error": "No price data available"}), 500

    @app.get("/api/forecast")
    def get_forecast():
        """Fetch forecast prices (live-first) with cache fallback."""
        from flask import request
        
        token = os.getenv("AMBER_TOKEN")
        site_id = os.getenv("AMBER_SITE_ID")
        channel_type = "general"
        
        if not site_id:
            return jsonify({"error": "AMBER_SITE_ID environment variable is not set"}), 500
        
        # Parse hours parameter (default 3, clamp 1-6)
        try:
            hours = int(request.args.get("hours", 3))
            hours = max(1, min(6, hours))
        except (ValueError, TypeError):
            hours = 3
        
        # Calculate number of intervals needed (assuming 5-minute intervals)
        # For 30-minute intervals, this would be hours * 2, but we'll use 5-min as default
        intervals_needed = hours * 12  # 12 intervals per hour for 5-minute intervals
        
        cache_path = _get_cache_path()
        now_utc = datetime.now(timezone.utc)
        
        # Try live API first if credentials are available
        if token:
            try:
                client = AmberClient(token=token, timeout=2)
                forecast_prices = client.get_prices_forecast(site_id, next_intervals=intervals_needed)
                
                if forecast_prices:
                    # Filter to "general" channel and normalize
                    forecast_intervals = []
                    cache_rows = []
                    
                    for price in forecast_prices:
                        price_channel = price.get("channelType") or price.get("channel_type")
                        if price_channel == channel_type or price_channel == "general":
                            interval_start_raw = price.get("startTime")
                            interval_end_raw = price.get("endTime")
                            
                            if interval_start_raw and interval_end_raw:
                                interval_start = normalize_interval_timestamp(interval_start_raw)
                                interval_end = normalize_interval_timestamp(interval_end_raw)
                                
                                # Only include future intervals
                                if parse_iso_z(interval_start) > now_utc:
                                    forecast_intervals.append({
                                        "start": interval_start,
                                        "end": interval_end,
                                        "per_kwh": price.get("perKwh"),
                                        "descriptor": price.get("descriptor"),
                                        "spikeStatus": price.get("spikeStatus"),
                                        "renewables": price.get("renewables")
                                    })
                                    
                                    cache_rows.append({
                                        "site_id": site_id,
                                        "interval_start": interval_start,
                                        "interval_end": interval_end,
                                        "channel_type": channel_type,
                                        "per_kwh": price.get("perKwh"),
                                        "renewables": price.get("renewables"),
                                        "descriptor": price.get("descriptor")
                                    })
                    
                    # Cache the forecast intervals
                    if cache_rows:
                        try:
                            sqlite_cache.upsert_prices(cache_path, cache_rows)
                        except Exception:
                            pass
                    
                    if forecast_intervals:
                        response = jsonify({"intervals": forecast_intervals})
                        response.headers["X-Data-Source"] = "live"
                        return response
            except (AmberAPIError, Exception) as e:
                # Live API failed - fall through to cache
                pass
        
        # Fallback to cache
        try:
            cached_forecast = sqlite_cache.get_forecast_intervals(cache_path, site_id, channel_type, max_intervals=intervals_needed)
            if cached_forecast:
                intervals = []
                for row in cached_forecast:
                    interval_start = normalize_interval_timestamp(row["interval_start"])
                    interval_end = normalize_interval_timestamp(row["interval_end"])
                    
                    # Only include future intervals
                    if parse_iso_z(interval_start) > now_utc:
                        intervals.append({
                            "start": interval_start,
                            "end": interval_end,
                            "per_kwh": row["per_kwh"],
                            "descriptor": row.get("descriptor"),
                            "renewables": row.get("renewables")
                        })
                
                if intervals:
                    response = jsonify({"intervals": intervals})
                    response.headers["X-Data-Source"] = "cache"
                    return response
        except Exception:
            pass
        
        # No forecast data available
        return jsonify({"intervals": [], "message": "No forecast data available"}), 200

    @app.get("/api/cost")
    def get_cost():
        """Calculate estimated cost per hour from current price and recent usage with read-through cache."""
        token = os.getenv("AMBER_TOKEN")
        site_id = os.getenv("AMBER_SITE_ID")
        channel_type = "general"
        
        if not site_id:
            return jsonify({"error": "AMBER_SITE_ID environment variable is not set"}), 500
        
        cache_path = _get_cache_path()
        now_utc = datetime.now(timezone.utc)
        
        # Get current price (same logic as /api/price)
        current_interval_start = floor_to_5min(now_utc)
        current_interval_start_str = current_interval_start.isoformat().replace("+00:00", "Z")
        
        cached_price = None
        try:
            cached_price = sqlite_cache.get_price_for_interval(cache_path, site_id, current_interval_start_str, channel_type)
            # Normalize timestamps defensively when reading from cache
            if cached_price:
                cached_price["interval_start"] = normalize_interval_timestamp(cached_price["interval_start"])
                cached_price["interval_end"] = normalize_interval_timestamp(cached_price["interval_end"])
        except Exception:
            pass
        
        if not cached_price:
            try:
                cached_price = sqlite_cache.get_latest_price(cache_path, site_id, channel_type)
                # Normalize timestamps defensively when reading from cache
                if cached_price:
                    cached_price["interval_start"] = normalize_interval_timestamp(cached_price["interval_start"])
                    cached_price["interval_end"] = normalize_interval_timestamp(cached_price["interval_end"])
            except Exception:
                pass
        
        # If still no price, try live API only if token is available
        if not cached_price:
            if not token:
                return jsonify({"error": "No price data available"}), 500
            try:
                client = AmberClient(token=token)
                prices = client.get_prices_current(site_id)
                if prices:
                    current = prices[0]
                    interval_start_raw = current.get("startTime")
                    interval_end_raw = current.get("endTime")
                    interval_start = normalize_interval_timestamp(interval_start_raw)
                    interval_end = normalize_interval_timestamp(interval_end_raw)
                    
                    cached_price = {
                        "per_kwh": current.get("perKwh"),
                        "interval_start": interval_start,
                        "interval_end": interval_end
                    }
                    
                    # Cache it
                    try:
                        cache_row = {
                            "site_id": site_id,
                            "interval_start": interval_start,
                            "interval_end": interval_end,
                            "channel_type": channel_type,
                            "per_kwh": current.get("perKwh"),
                            "renewables": current.get("renewables"),
                            "descriptor": current.get("descriptor")
                        }
                        sqlite_cache.upsert_prices(cache_path, [cache_row])
                    except Exception:
                        pass
            except Exception:
                pass
        
        if not cached_price:
            return jsonify({"error": "No price data available"}), 500
        
        price_per_kwh = cached_price["per_kwh"]
        
        # Get latest usage
        cached_usage = None
        try:
            cached_usage = sqlite_cache.get_latest_usage(cache_path, site_id, channel_type)
            # Normalize timestamps defensively when reading from cache
            if cached_usage:
                cached_usage["interval_start"] = normalize_interval_timestamp(cached_usage["interval_start"])
                cached_usage["interval_end"] = normalize_interval_timestamp(cached_usage["interval_end"])
        except Exception:
            pass
        
        # Cache-only: return error if no usage data available
        if not cached_usage:
            return jsonify({"error": "No usage data available"}), 500
        
        # Calculate cost
        kwh = cached_usage["kwh"]
        usage_start = parse_iso_z(cached_usage["interval_start"])
        usage_end = parse_iso_z(cached_usage["interval_end"])
        duration_seconds = (usage_end - usage_start).total_seconds()
        duration_minutes = duration_seconds / 60.0 if duration_seconds > 0 else 5.0
        duration_hours = duration_minutes / 60.0
        usage_kw = kwh / duration_hours if duration_hours > 0 else 0
        cost_per_hour = usage_kw * price_per_kwh if price_per_kwh else None
        
        # Calculate usage age
        usage_interval_start_dt = parse_iso_z(cached_usage["interval_start"])
        usage_age_seconds = int((now_utc - usage_interval_start_dt).total_seconds())
        
        # Determine if usage is stale (threshold: 15 minutes = 900 seconds)
        usage_is_stale = usage_age_seconds > 900
        
        # Normalize timestamps defensively before returning (already normalized, but ensure consistency)
        usage_interval_start_normalized = normalize_interval_timestamp(cached_usage["interval_start"])
        
        response_data = {
            "cost_per_hour": cost_per_hour,
            "usage_kw": usage_kw,
            "price_per_kwh": price_per_kwh,
            "usage_interval_start": usage_interval_start_normalized,
            "usage_age_seconds": usage_age_seconds,
            "is_estimated": usage_is_stale,
            "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        }
        
        response = jsonify(response_data)
        response.headers["X-Data-Source"] = "cache"
        response.headers["X-Cache-Stale"] = "true" if usage_is_stale else "false"
        return response

    @app.get("/api/health")
    def get_health():
        """Health check endpoint returning app status and data freshness."""
        app_time = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        data_source = "cache"
        
        token = os.getenv("AMBER_TOKEN")
        site_id = os.getenv("AMBER_SITE_ID")
        channel_type = "general"
        
        latest_price_interval_start = None
        latest_usage_interval_start = None
        price_age_seconds = None
        usage_age_seconds = None
        status = "unknown"
        
        # Try cache first
        cache_path = _get_cache_path()
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat().replace("+00:00", "Z")
        
        try:
            cached_price = sqlite_cache.get_latest_price(cache_path, site_id, channel_type, max_interval_start=now_iso)
            if cached_price:
                latest_price_interval_start = cached_price["interval_start"]
                try:
                    price_dt = parse_iso_z(latest_price_interval_start)
                    price_age_seconds = int((now - price_dt).total_seconds())
                    # Safety clamp: prevent negative ages
                    price_age_seconds = max(0, price_age_seconds)
                except Exception:
                    pass
        except Exception:
            pass
        
        try:
            cached_usage = sqlite_cache.get_latest_usage(cache_path, site_id, channel_type, max_interval_start=now_iso)
            if cached_usage:
                latest_usage_interval_start = cached_usage["interval_start"]
                try:
                    usage_dt = parse_iso_z(latest_usage_interval_start)
                    usage_age_seconds = int((now - usage_dt).total_seconds())
                    # Safety clamp: prevent negative ages
                    usage_age_seconds = max(0, usage_age_seconds)
                except Exception:
                    pass
        except Exception:
            pass
        
        # If cache is empty, fall back to live API
        if (price_age_seconds is None and usage_age_seconds is None) and token and site_id:
            try:
                client = AmberClient(token=token)
                
                # Get latest price interval
                try:
                    prices = client.get_prices_current(site_id)
                    if prices and len(prices) > 0:
                        latest_price_interval_start = prices[0].get("startTime")
                        try:
                            price_dt = parse_iso_z(latest_price_interval_start)
                            price_age_seconds = int((now - price_dt).total_seconds())
                        except Exception:
                            pass
                        data_source = "live"
                except Exception:
                    pass
                
                # Get latest usage interval
                try:
                    usage_data = client.get_usage_recent(site_id, intervals=1)
                    if usage_data and len(usage_data) > 0:
                        latest_usage_interval_start = usage_data[0].get("startTime")
                        try:
                            usage_dt = parse_iso_z(latest_usage_interval_start)
                            usage_age_seconds = int((now - usage_dt).total_seconds())
                        except Exception:
                            pass
                        data_source = "live"
                except Exception:
                    pass
            except Exception:
                pass
        
        # Determine status: ok only if BOTH are fresh (threshold: 15 minutes = 900 seconds)
        threshold_seconds = 900
        if price_age_seconds is not None and usage_age_seconds is not None:
            if price_age_seconds <= threshold_seconds and usage_age_seconds <= threshold_seconds:
                status = "ok"
            else:
                status = "stale"
        elif price_age_seconds is not None or usage_age_seconds is not None:
            # Only one metric available - check if it's fresh
            available_age = price_age_seconds if price_age_seconds is not None else usage_age_seconds
            if available_age <= threshold_seconds:
                status = "ok"
            else:
                status = "stale"
        else:
            status = "unknown"
        
        return jsonify({
            "app_time": app_time,
            "data_source": data_source,
            "latest_price_interval_start": latest_price_interval_start,
            "latest_usage_interval_start": latest_usage_interval_start,
            "price_age_seconds": price_age_seconds,
            "usage_age_seconds": usage_age_seconds,
            "status": status
        })

    @app.get("/api/totals")
    def get_totals():
        """Get month-to-date cost totals from cache using usage.cost_aud."""
        site_id = os.getenv("AMBER_SITE_ID")
        channel_type = "general"
        
        # Cache-only: return empty result if site_id missing, don't error
        if not site_id:
            return jsonify({
                "month_to_date_cost_aud": None,
                "as_of_interval_end": None,
                "intervals_count": 0,
                "missing_price_intervals": 0,
                "missing_usage_intervals": 0,
                "usage_age_seconds": None,
                "is_delayed": False,
                "message": "AMBER_SITE_ID not set"
            })
        
        cache_path = _get_cache_path()
        
        # Get current month start in Australia/Sydney timezone
        sydney_tz = ZoneInfo("Australia/Sydney")
        now_sydney = datetime.now(sydney_tz)
        month_start_sydney = now_sydney.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        month_start_utc = month_start_sydney.astimezone(timezone.utc)
        month_start_utc_str = month_start_utc.isoformat().replace("+00:00", "Z")
        
        # Get current time in UTC for "as of" calculation
        now_utc = datetime.now(timezone.utc)
        
        try:
            conn = sqlite3.connect(cache_path)
            cursor = conn.cursor()
            
            # Query usage rows with cost_aud for current month
            # Filter to channel_type == "general" and cost_aud IS NOT NULL
            cursor.execute("""
                SELECT 
                    interval_start,
                    interval_end,
                    cost_aud
                FROM usage
                WHERE 
                    site_id = ? AND
                    channel_type = ? AND
                    interval_start >= ? AND
                    cost_aud IS NOT NULL
                ORDER BY interval_start ASC
            """, (site_id, channel_type, month_start_utc_str))
            
            rows = cursor.fetchall()
            
            # Get latest usage interval_end for "as of" timestamp (from rows with cost_aud)
            cursor.execute("""
                SELECT interval_end
                FROM usage
                WHERE 
                    site_id = ? AND
                    channel_type = ? AND
                    interval_start >= ? AND
                    cost_aud IS NOT NULL
                ORDER BY interval_start DESC
                LIMIT 1
            """, (site_id, channel_type, month_start_utc_str))
            
            latest_usage_row = cursor.fetchone()
            as_of_interval_end = latest_usage_row[0] if latest_usage_row else None
            
            # Get usage age from latest usage interval (any usage, not just with cost)
            cursor.execute("""
                SELECT interval_end
                FROM usage
                WHERE site_id = ? AND channel_type = ? AND interval_start >= ?
                ORDER BY interval_start DESC
                LIMIT 1
            """, (site_id, channel_type, month_start_utc_str))
            
            latest_any_usage = cursor.fetchone()
            usage_age_seconds = None
            if latest_any_usage:
                try:
                    latest_usage_dt = parse_iso_z(latest_any_usage[0])
                    usage_age_seconds = int((now_utc - latest_usage_dt).total_seconds())
                except Exception:
                    pass
            
            conn.close()
            
            # Calculate totals from cost_aud
            if not rows:
                return jsonify({
                    "month_to_date_cost_aud": None,
                    "as_of_interval_end": None,
                    "intervals_count": 0,
                    "missing_price_intervals": 0,
                    "missing_usage_intervals": 0,
                    "usage_age_seconds": usage_age_seconds,
                    "is_delayed": usage_age_seconds is not None and usage_age_seconds > 1800,
                    "message": "Waiting for usage data"
                })
            
            total_cost_aud = 0.0
            for row in rows:
                interval_start, interval_end, cost_aud = row
                if cost_aud is not None:
                    total_cost_aud += cost_aud
            
            # Determine if delayed (usage is lagging or very stale)
            is_delayed = False
            if usage_age_seconds is not None:
                is_delayed = usage_age_seconds > 1800  # > 30 minutes
            
            return jsonify({
                "month_to_date_cost_aud": round(total_cost_aud, 2),
                "as_of_interval_end": as_of_interval_end,
                "intervals_count": len(rows),
                "missing_price_intervals": 0,  # No longer relevant - using cost_aud
                "missing_usage_intervals": 0,  # No longer relevant - using cost_aud
                "usage_age_seconds": usage_age_seconds,
                "is_delayed": is_delayed
            })
            
        except Exception as e:
            # Return empty result on error, don't throw 500
            return jsonify({
                "month_to_date_cost_aud": None,
                "as_of_interval_end": None,
                "intervals_count": 0,
                "missing_price_intervals": 0,
                "missing_usage_intervals": 0,
                "usage_age_seconds": None,
                "is_delayed": False,
                "message": f"Error: {str(e)}"
            })

    @app.get("/")
    def index():
        """Home page with kiosk-style dashboard."""
        return render_template("dashboard.html")

    return app

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5050"))
    debug = os.getenv("DEBUG", "0") == "1"
    app = create_app()
    app.run(host="0.0.0.0", port=port, debug=debug, use_reloader=debug)
