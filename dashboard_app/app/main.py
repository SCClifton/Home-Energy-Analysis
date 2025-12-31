import os
from datetime import datetime, timezone
from flask import Flask, jsonify, render_template_string, Response
import sys

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
        """Fetch current price from Amber API with read-through cache."""
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
        
        # Try to get price for current interval
        cached_row = None
        try:
            cached_row = sqlite_cache.get_price_for_interval(cache_path, site_id, current_interval_start_str, channel_type)
            if cached_row:
                # Found exact interval match - normalize timestamps defensively before returning
                interval_start = normalize_interval_timestamp(cached_row["interval_start"])
                interval_end = normalize_interval_timestamp(cached_row["interval_end"])
                response = jsonify({
                    "site_id": cached_row["site_id"],
                    "per_kwh": cached_row["per_kwh"],
                    "interval_start": interval_start,
                    "interval_end": interval_end,
                    "renewables": cached_row.get("renewables"),
                    "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                })
                response.headers["X-Data-Source"] = "cache"
                response.headers["X-Cache-Stale"] = "false"
                return response
        except Exception:
            # If cache read fails, fall through
            pass
        
        # Current interval not found: try latest cached price as fallback
        try:
            cached_row = sqlite_cache.get_latest_price(cache_path, site_id, channel_type)
            if cached_row:
                # Normalize timestamps defensively before returning
                interval_start = normalize_interval_timestamp(cached_row["interval_start"])
                interval_end = normalize_interval_timestamp(cached_row["interval_end"])
                response = jsonify({
                    "site_id": cached_row["site_id"],
                    "per_kwh": cached_row["per_kwh"],
                    "interval_start": interval_start,
                    "interval_end": interval_end,
                    "renewables": cached_row.get("renewables"),
                    "is_stale": True,
                    "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                })
                response.headers["X-Data-Source"] = "cache"
                response.headers["X-Cache-Stale"] = "true"
                return response
        except Exception:
            # If cache read fails, fall through
            pass
        
        # Cache miss: only try live API if token is available
        if not token:
            return jsonify({"error": "AMBER_TOKEN environment variable is not set"}), 500
        
        try:
            client = AmberClient(token=token)
            prices = client.get_prices_current(site_id)
            
            if not prices:
                # Live API returned no data, return error
                return jsonify({"error": "No price data available"}), 500
            
            # Pick the first interval as "current"
            current = prices[0]
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
            
            # Prune old data (non-blocking)
            try:
                retention_days = int(os.getenv("RETENTION_DAYS", "14"))
                sqlite_cache.prune_old_data(cache_path, retention_days)
            except Exception:
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
            return response
        except (AmberAPIError, Exception) as e:
            # Live API failed: try stale cache if available
            if cached_row:
                # Normalize timestamps defensively before returning
                interval_start = normalize_interval_timestamp(cached_row["interval_start"])
                interval_end = normalize_interval_timestamp(cached_row["interval_end"])
                response = jsonify({
                    "site_id": cached_row["site_id"],
                    "per_kwh": cached_row["per_kwh"],
                    "interval_start": interval_start,
                    "interval_end": interval_end,
                    "renewables": cached_row.get("renewables"),
                    "is_stale": True,
                    "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                })
                response.headers["X-Data-Source"] = "cache"
                response.headers["X-Cache-Stale"] = "true"
                return response
            # No cache available, return error
            return jsonify({"error": f"Amber API error: {str(e)}"}), 500

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
        
        # If no usage in cache, try live API only if token is available
        if not cached_usage:
            if not token:
                return jsonify({"error": "No usage data available"}), 500
            try:
                client = AmberClient(token=token)
                usage_data = client.get_usage_recent(site_id, intervals=1)
                if usage_data:
                    usage_interval = usage_data[0]
                    interval_start_raw = usage_interval.get("startTime")
                    interval_end_raw = usage_interval.get("endTime")
                    interval_start = normalize_interval_timestamp(interval_start_raw)
                    interval_end = normalize_interval_timestamp(interval_end_raw)
                    
                    cached_usage = {
                        "kwh": usage_interval.get("kwh"),
                        "interval_start": interval_start,
                        "interval_end": interval_end
                    }
                    
                    # Cache it
                    try:
                        usage_cache_row = {
                            "site_id": site_id,
                            "interval_start": interval_start,
                            "interval_end": interval_end,
                            "channel_type": channel_type,
                            "kwh": usage_interval.get("kwh")
                        }
                        sqlite_cache.upsert_usage(cache_path, [usage_cache_row])
                    except Exception:
                        pass
            except Exception:
                pass
        
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
        response.headers["X-Data-Source"] = "cache" if cached_usage and cached_price else "live"
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
        
        try:
            cached_price = sqlite_cache.get_latest_price(cache_path, site_id, channel_type)
            if cached_price:
                latest_price_interval_start = cached_price["interval_start"]
                try:
                    price_dt = parse_iso_z(latest_price_interval_start)
                    price_age_seconds = int((now - price_dt).total_seconds())
                except Exception:
                    pass
        except Exception:
            pass
        
        try:
            cached_usage = sqlite_cache.get_latest_usage(cache_path, site_id, channel_type)
            if cached_usage:
                latest_usage_interval_start = cached_usage["interval_start"]
                try:
                    usage_dt = parse_iso_z(latest_usage_interval_start)
                    usage_age_seconds = int((now - usage_dt).total_seconds())
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

    @app.get("/")
    def index():
        """Home page with current price display."""
        html = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Home Energy Dashboard</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: #1a1a1a;
            color: #ffffff;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            padding: 20px;
        }
        .container {
            text-align: center;
            max-width: 600px;
            width: 100%;
        }
        .price-display {
            margin-bottom: 30px;
        }
        .price-value {
            font-size: 72px;
            font-weight: 700;
            color: #4ade80;
            margin: 20px 0;
            line-height: 1;
        }
        .price-label {
            font-size: 18px;
            color: #9ca3af;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        .info {
            font-size: 14px;
            color: #6b7280;
            margin-top: 20px;
        }
        .error {
            color: #ef4444;
            font-size: 18px;
            padding: 20px;
            background: #7f1d1d;
            border-radius: 8px;
            margin-top: 20px;
        }
        .loading {
            color: #9ca3af;
            font-size: 18px;
        }
        .interval-time {
            font-size: 16px;
            color: #d1d5db;
            margin-top: 10px;
        }
        .renewables {
            font-size: 14px;
            color: #60a5fa;
            margin-top: 5px;
        }
        .cost-display {
            margin-top: 40px;
            padding-top: 40px;
            border-top: 1px solid #374151;
        }
        .cost-value {
            font-size: 48px;
            font-weight: 700;
            color: #fbbf24;
            margin: 20px 0;
            line-height: 1;
        }
        .cost-label {
            font-size: 16px;
            color: #9ca3af;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        .cost-note {
            font-size: 12px;
            color: #6b7280;
            margin-top: 10px;
            font-style: italic;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="price-display">
            <div class="price-label">Current Price</div>
            <div id="price-value" class="price-value">--</div>
            <div id="interval-time" class="interval-time"></div>
            <div id="renewables" class="renewables"></div>
        </div>
        
        <div class="cost-display">
            <div class="cost-label">Estimated Cost per Hour</div>
            <div id="cost-value" class="cost-value">--</div>
            <div id="cost-note" class="cost-note">Based on last interval</div>
            <div id="cost-error" class="error" style="display: none;"></div>
        </div>
        
        <div id="error" class="error" style="display: none;"></div>
        <div id="loading" class="loading" style="display: none;">Loading...</div>
        <div id="last-updated" class="info"></div>
    </div>

    <script>
        function updatePrice() {
            const priceValue = document.getElementById('price-value');
            const intervalTime = document.getElementById('interval-time');
            const renewables = document.getElementById('renewables');
            const error = document.getElementById('error');
            const loading = document.getElementById('loading');
            const lastUpdated = document.getElementById('last-updated');
            
            // Show loading, hide error
            loading.style.display = 'block';
            error.style.display = 'none';
            
            fetch('/api/price')
                .then(response => {
                    if (!response.ok) {
                        return response.json().then(data => {
                            throw new Error(data.error || 'Failed to fetch price');
                        });
                    }
                    return response.json();
                })
                .then(data => {
                    // Update price
                    priceValue.textContent = data.per_kwh !== null && data.per_kwh !== undefined 
                        ? data.per_kwh.toFixed(1) 
                        : '--';
                    priceValue.textContent += ' c/kWh';
                    
                    // Update interval time
                    if (data.interval_start && data.interval_end) {
                        const start = new Date(data.interval_start);
                        const end = new Date(data.interval_end);
                        const startStr = start.toLocaleTimeString('en-AU', { hour: '2-digit', minute: '2-digit' });
                        const endStr = end.toLocaleTimeString('en-AU', { hour: '2-digit', minute: '2-digit' });
                        intervalTime.textContent = `${startStr} - ${endStr}`;
                    } else {
                        intervalTime.textContent = '';
                    }
                    
                    // Update renewables
                    if (data.renewables !== null && data.renewables !== undefined) {
                        renewables.textContent = `Renewables: ${data.renewables.toFixed(1)}%`;
                    } else {
                        renewables.textContent = '';
                    }
                    
                    // Update last updated
                    if (data.fetched_at) {
                        const fetched = new Date(data.fetched_at);
                        lastUpdated.textContent = `Last updated: ${fetched.toLocaleTimeString('en-AU')}`;
                    }
                    
                    loading.style.display = 'none';
                })
                .catch(err => {
                    priceValue.textContent = '--';
                    intervalTime.textContent = '';
                    renewables.textContent = '';
                    error.textContent = `Error: ${err.message}`;
                    error.style.display = 'block';
                    loading.style.display = 'none';
                    
                    const now = new Date();
                    lastUpdated.textContent = `Last updated: ${now.toLocaleTimeString('en-AU')} (error)`;
                });
        }
        
        function updateCost() {
            const costValue = document.getElementById('cost-value');
            const costError = document.getElementById('cost-error');
            
            fetch('/api/cost')
                .then(response => {
                    if (!response.ok) {
                        return response.json().then(data => {
                            throw new Error(data.error || 'Failed to fetch cost');
                        });
                    }
                    return response.json();
                })
                .then(data => {
                    // Update cost
                    if (data.cost_per_hour !== null && data.cost_per_hour !== undefined) {
                        costValue.textContent = data.cost_per_hour.toFixed(2) + ' c/hr';
                    } else {
                        costValue.textContent = '--';
                    }
                    costError.style.display = 'none';
                })
                .catch(err => {
                    costValue.textContent = '--';
                    costError.textContent = `Usage data unavailable: ${err.message}`;
                    costError.style.display = 'block';
                });
        }
        
        function updateAll() {
            updatePrice();
            updateCost();
        }
        
        // Update immediately on load
        updateAll();
        
        // Update every 30 seconds
        setInterval(updateAll, 30000);
    </script>
</body>
</html>
        """
        return render_template_string(html)

    return app

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5050))
    app = create_app()
    app.run(host="0.0.0.0", port=port, debug=True)
