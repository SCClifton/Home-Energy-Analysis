import os
from datetime import datetime
from flask import Flask, jsonify, render_template_string
import sys

# Add parent directory to path to import amber_client
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
from ingestion.amber_client import AmberClient, AmberAPIError

def create_app() -> Flask:
    app = Flask(__name__)

    @app.get("/api/price")
    def get_price():
        """Fetch current price from Amber API."""
        token = os.getenv("AMBER_TOKEN")
        site_id = os.getenv("AMBER_SITE_ID")
        
        if not token:
            return jsonify({"error": "AMBER_TOKEN environment variable is not set"}), 500
        if not site_id:
            return jsonify({"error": "AMBER_SITE_ID environment variable is not set"}), 500
        
        try:
            client = AmberClient(token=token)
            prices = client.get_prices_current(site_id)
            
            if not prices:
                return jsonify({"error": "No price data available"}), 500
            
            # Pick the first interval as "current"
            current = prices[0]
            
            return jsonify({
                "site_id": site_id,
                "per_kwh": current.get("perKwh"),
                "interval_start": current.get("startTime"),
                "interval_end": current.get("endTime"),
                "renewables": current.get("renewables"),
                "fetched_at": datetime.utcnow().isoformat() + "Z"
            })
        except AmberAPIError as e:
            return jsonify({"error": f"Amber API error: {str(e)}"}), 500
        except Exception as e:
            return jsonify({"error": f"Unexpected error: {str(e)}"}), 500

    @app.get("/api/cost")
    def get_cost():
        """Calculate estimated cost per hour from current price and recent usage."""
        token = os.getenv("AMBER_TOKEN")
        site_id = os.getenv("AMBER_SITE_ID")
        
        if not token:
            return jsonify({"error": "AMBER_TOKEN environment variable is not set"}), 500
        if not site_id:
            return jsonify({"error": "AMBER_SITE_ID environment variable is not set"}), 500
        
        try:
            client = AmberClient(token=token)
            
            # Get current price
            prices = client.get_prices_current(site_id)
            if not prices:
                return jsonify({"error": "No price data available"}), 500
            current_price = prices[0]
            price_per_kwh = current_price.get("perKwh")
            
            # Get recent usage
            usage_data = client.get_usage_recent(site_id, intervals=1)
            if not usage_data:
                return jsonify({"error": "No usage data available"}), 500
            
            usage_interval = usage_data[0]
            kwh = usage_interval.get("kwh")
            duration_minutes = usage_interval.get("duration", 30)  # Default to 30 if not provided
            
            # Calculate usage in kW (power)
            # kWh / (duration in hours) = kW
            duration_hours = duration_minutes / 60.0
            usage_kw = kwh / duration_hours if duration_hours > 0 else 0
            
            # Calculate cost per hour
            # cost_per_hour = usage_kw * price_per_kwh (in cents)
            cost_per_hour = usage_kw * price_per_kwh if price_per_kwh else None
            
            return jsonify({
                "cost_per_hour": cost_per_hour,
                "usage_kw": usage_kw,
                "price_per_kwh": price_per_kwh,
                "interval_minutes": duration_minutes,
                "fetched_at": datetime.utcnow().isoformat() + "Z"
            })
        except AmberAPIError as e:
            return jsonify({"error": f"Amber API error: {str(e)}"}), 500
        except Exception as e:
            return jsonify({"error": f"Unexpected error: {str(e)}"}), 500

    @app.get("/api/health")
    def get_health():
        """Health check endpoint returning app status and data freshness."""
        app_time = datetime.utcnow().isoformat() + "Z"
        data_source = "live"
        
        token = os.getenv("AMBER_TOKEN")
        site_id = os.getenv("AMBER_SITE_ID")
        
        latest_price_interval_start = None
        latest_usage_interval_start = None
        data_age_seconds = None
        status = "unknown"
        
        if token and site_id:
            try:
                client = AmberClient(token=token)
                
                # Get latest price interval
                try:
                    prices = client.get_prices_current(site_id)
                    if prices and len(prices) > 0:
                        latest_price_interval_start = prices[0].get("startTime")
                except Exception:
                    pass  # Ignore errors, will result in null
                
                # Get latest usage interval
                try:
                    usage_data = client.get_usage_recent(site_id, intervals=1)
                    if usage_data and len(usage_data) > 0:
                        latest_usage_interval_start = usage_data[0].get("startTime")
                except Exception:
                    pass  # Ignore errors, will result in null
                
                # Calculate data age from the most recent of price or usage
                now = datetime.utcnow()
                latest_interval_start = None
                
                if latest_price_interval_start and latest_usage_interval_start:
                    # Use the more recent of the two
                    price_dt = datetime.fromisoformat(latest_price_interval_start.replace("Z", "+00:00"))
                    usage_dt = datetime.fromisoformat(latest_usage_interval_start.replace("Z", "+00:00"))
                    latest_interval_start = max(price_dt, usage_dt)
                elif latest_price_interval_start:
                    latest_interval_start = datetime.fromisoformat(latest_price_interval_start.replace("Z", "+00:00"))
                elif latest_usage_interval_start:
                    latest_interval_start = datetime.fromisoformat(latest_usage_interval_start.replace("Z", "+00:00"))
                
                if latest_interval_start:
                    # Calculate age in seconds
                    delta = now - latest_interval_start.replace(tzinfo=None)
                    data_age_seconds = int(delta.total_seconds())
                    
                    # Determine status: stale if > 15 minutes (900 seconds)
                    if data_age_seconds > 900:
                        status = "stale"
                    else:
                        status = "ok"
                else:
                    status = "unknown"
                    
            except Exception:
                # If there's an error, status remains "unknown"
                pass
        
        return jsonify({
            "app_time": app_time,
            "data_source": data_source,
            "latest_price_interval_start": latest_price_interval_start,
            "latest_usage_interval_start": latest_usage_interval_start,
            "data_age_seconds": data_age_seconds,
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
