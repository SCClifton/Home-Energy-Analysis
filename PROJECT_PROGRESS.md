# Project Progress

## 2025-12-28
- Dashboard now uses SQLite read-through cache for /api/price and /api/cost, with X-Data-Source header, retention pruning, and /api/health based on cache when available.
- Cache provides reliability for Raspberry Pi kitchen display: endpoints return cached data if fresh (<15 min), otherwise fetch from live Amber API and update cache.
- /api/cost matches usage intervals to prices by exact interval_start for accurate cost calculations.
- Tested with curl: first call shows X-Data-Source: live, second call shows X-Data-Source: cache. Verified offline behavior (cache serves when internet unavailable).

## 2025-12-28 (continued)
- Improved resilience: /api/price and /api/cost now serve cached data (even if stale) when live Amber API fails (network errors, missing env vars, API errors).
- Added X-Cache-Stale header (true/false) to indicate when cached data is being served but is older than 15 minutes.
- /api/health now shows "stale" status when cache exists but is older than 15 minutes (instead of "unknown").
- Offline behavior: Dashboard continues to function using cached data when internet is unavailable, providing graceful degradation for Raspberry Pi kitchen display.

## 2025-12-27
- What changed: added GET /api/health endpoint to dashboard app for monitoring data freshness and app status.
- Returns JSON with app_time, data_source ("live"), latest_price_interval_start, latest_usage_interval_start, data_age_seconds, and status ("ok"/"stale"/"unknown").
- Status "stale" is defined as data_age_seconds > 15 minutes (900 seconds).
- What was tested: endpoint returns correct JSON structure; tested with curl when app is running. Returns "unknown" status when AMBER_TOKEN/SITE_ID not configured (expected behavior).

## 2025-12-23

- What changed: added cost-per-hour calculation in the dashboard UI and a new /api/cost endpoint using Amber usage data.
- Formula used: usage_kw = kwh / (minutes / 60); cost_per_hour = usage_kw * price_per_kwh (c/kWh).
- Known limitations: Amber usage can lag by an interval, interval boundaries may not align with price data, and this is not a full bill calculation.
- What was tested: /api/price and /api/cost endpoints returning JSON when the dashboard is running.
- Next steps: add SQLite storage, improve interval alignment/selection, and wire up Pi kiosk/systemd deployment.

## 2025-12-23 (continued)
- Confirmed Powerpal CSV export format and implemented robust parser.
- Successfully pulled and validated a 91-day window (2025-06-24 → 2025-09-22):
  - 26,208 × 5-minute usage intervals from Powerpal
  - 26,208 matching wholesale price intervals from Amber
- Fixed Amber +1s timestamp offset by flooring to 5-minute buckets.
- Baseline pipeline now supports accurate historical joins of usage + price.
- Next steps: pull remaining Powerpal windows to complete last-12-months baseline, then layer solar / EV / battery scenarios.
