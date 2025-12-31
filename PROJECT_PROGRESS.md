# Project Progress

## 2025-12-31 (Cache-first logic, timestamp normalisation, and data correctness)

### What changed
- Implemented **end-to-end timestamp normalisation** for Amber data across ingestion, storage, and API layers:
  - All `interval_start` and `interval_end` values are now normalised to exact 5-minute boundaries (`…:00Z`).
  - Fixed legacy Amber `+1 second` offsets (`…:01Z`) without requiring database migration.
- Added **defensive normalisation on cache reads** so legacy cached rows cannot leak incorrect timestamps to API responses or the UI.
- Updated SQLite cache read logic to support **legacy `:01Z` rows**:
  - Exact `:00Z` matches are preferred.
  - Fallback to `+1 second` legacy rows when required.
- Reworked `/api/price` and `/api/cost` to be **cache-first and deterministic**:
  - Flow: exact interval → latest cached (stale) → live Amber (only if cache empty and env vars present).
  - Prevents unnecessary live API calls and avoids errors when Amber credentials are unavailable (eg local dev).
- Improved `/api/health` semantics:
  - Added separate `price_age_seconds` and `usage_age_seconds`.
  - Reintroduced `data_age_seconds` for backward compatibility.
  - Status is now:
    - `ok` only when both price and usage are fresh,
    - `stale` when either is stale,
    - `unknown` when cache is empty.
- Added unit test coverage for legacy timestamp fallback behaviour to ensure deterministic cache reads.

### Why this was done
- Amber API occasionally returns timestamps with a `+1s` offset, causing interval mismatches.
- Cached data was being skipped due to strict timestamp equality, forcing unnecessary live API calls.
- Local development without Amber credentials was failing even when cached data existed.
- `/api/health` was previously reporting misleading “ok” states when usage data was many hours stale.

### What was tested
- Unit tests updated and passing, including new coverage for legacy timestamp handling.
- Local Flask app runs correctly using cached data only (no Amber credentials required).
- Cache-first behaviour verified for `/api/price`, `/api/cost`, and `/api/health`.
- Deterministic fallback order confirmed (exact → latest cached → live if available).

### Outcome
- Dashboard now behaves as a **true offline-first appliance**:
  - Always serves cached data when available.
  - Clearly marks stale and estimated values.
  - Only attempts live Amber calls when genuinely required.
- Timestamp handling is consistent across ingestion, storage, API responses, and UI.
- Local development workflow is robust without secrets.
- Raspberry Pi deployment remains unchanged and benefits immediately from improved correctness.

### Files touched
- `dashboard_app/app/main.py`
- `src/home_energy_analysis/storage/sqlite_cache.py`
- `scripts/sync_cache.py`
- `tests/test_sqlite_cache.py`

### Next steps
- Surface `is_stale` / `is_estimated` flags visually in the dashboard UI.
- Minor UI tuning for 5" screen (font size, spacing, status indicators).
- Decide whether to pursue near-real-time usage via local metering to reduce Amber usage lag.


## 2025-12-29 (Raspberry Pi deployment + operations)

### What changed
- Completed end-to-end deployment of the Home Energy dashboard on a Raspberry Pi 5 as a headless appliance with optional kiosk display.
- Raspberry Pi OS (64-bit, desktop) installed and configured with SSH-first workflow (no permanent keyboard/mouse/monitor required).
- GitHub repo cloned to Pi and aligned to `main` branch (merged `feature/pi-sqlite-cache` into `main`).
- Python virtual environment created on-device and project installed in editable mode (`pip install -e .`) using `pyproject.toml`.
- Secure environment configuration added at `/etc/home-energy-analysis/dashboard.env`:
  - `AMBER_TOKEN`, `AMBER_SITE_ID`, `PORT`, `SQLITE_PATH`, `RETENTION_DAYS`, `DEBUG`
  - File owned by root, readable via dedicated `homeenergy` group for service user.
- Persistent SQLite cache directory created at `/var/lib/home-energy-analysis`.

### Services & scheduling
- Added systemd service `home-energy-dashboard.service`:
  - Starts on boot
  - Runs Flask app under venv
  - Restarts on failure
  - Debug mode disabled (single process, no reloader).
- Added systemd oneshot service + timer:
  - `home-energy-sync-cache.service`
  - `home-energy-sync-cache.timer` (runs every 5 minutes with jitter)
  - Verified successful cache refresh via journald logs.
- Verified reboot resilience:
  - Dashboard service and cache timer both start cleanly after reboot.

### Kiosk mode
- Installed Chromium kiosk dependencies (`chromium`, `xdotool`, `unclutter`).
- Added user-level kiosk launcher script:
  - Waits for `/api/health` before launching browser.
  - Launches Chromium fullscreen to `http://localhost:5050`.
  - Disables screen blanking and hides cursor.
- Added desktop autostart entry so kiosk launches automatically on login.
- System is ready for permanent kitchen display mounting.

### What was tested
- SSH-only management workflow (headless operation).
- Dashboard accessible from LAN (`http://<pi-ip>:5050`).
- `/api/health` reports correct status.
- Offline-first behaviour confirmed using SQLite cache.
- systemd timer successfully refreshes cache on schedule.
- Reboot test confirms full recovery without manual intervention.

### Outcome
- Raspberry Pi now operates as a self-healing, offline-capable energy display appliance.
- No manual intervention required after power loss or reboot.
- Update workflow is stable: develop on Mac → push to GitHub → `git pull` + service restart on Pi.

### Next steps
- (Optional) Add update helper script (`git pull` + restart).
- (Optional) Swap Flask dev server for gunicorn.
- (Optional) Add UI indicators for cache age / offline state.


## 2025-12-29 (Raspberry Pi deployment + operations)

### What changed
- Completed end-to-end deployment of the Home Energy dashboard on a Raspberry Pi 5 as a headless appliance with optional kiosk display.
- Raspberry Pi OS (64-bit, desktop) installed and configured with SSH-first workflow (no permanent keyboard/mouse/monitor required).
- GitHub repo cloned to Pi and aligned to `main` branch (merged `feature/pi-sqlite-cache` into `main`).
- Python virtual environment created on-device and project installed in editable mode (`pip install -e .`) using `pyproject.toml`.
- Secure environment configuration added at `/etc/home-energy-analysis/dashboard.env`:
  - `AMBER_TOKEN`, `AMBER_SITE_ID`, `PORT`, `SQLITE_PATH`, `RETENTION_DAYS`, `DEBUG`
  - File owned by root, readable via dedicated `homeenergy` group for service user.
- Persistent SQLite cache directory created at `/var/lib/home-energy-analysis`.

### Services & scheduling
- Added systemd service `home-energy-dashboard.service`:
  - Starts on boot
  - Runs Flask app under venv
  - Restarts on failure
  - Debug mode disabled (single process, no reloader).
- Added systemd oneshot service + timer:
  - `home-energy-sync-cache.service`
  - `home-energy-sync-cache.timer` (runs every 5 minutes with jitter)
  - Verified successful cache refresh via journald logs.
- Verified reboot resilience:
  - Dashboard service and cache timer both start cleanly after reboot.

### Kiosk mode
- Installed Chromium kiosk dependencies (`chromium`, `xdotool`, `unclutter`).
- Added user-level kiosk launcher script:
  - Waits for `/api/health` before launching browser.
  - Launches Chromium fullscreen to `http://localhost:5050`.
  - Disables screen blanking and hides cursor.
- Added desktop autostart entry so kiosk launches automatically on login.
- System is ready for permanent kitchen display mounting.

### What was tested
- SSH-only management workflow (headless operation).
- Dashboard accessible from LAN (`http://<pi-ip>:5050`).
- `/api/health` reports correct status.
- Offline-first behaviour confirmed using SQLite cache.
- systemd timer successfully refreshes cache on schedule.
- Reboot test confirms full recovery without manual intervention.

### Outcome
- Raspberry Pi now operates as a self-healing, offline-capable energy display appliance.
- No manual intervention required after power loss or reboot.
- Update workflow is stable: develop on Mac → push to GitHub → `git pull` + service restart on Pi.

### Next steps
- (Optional) Add update helper script (`git pull` + restart).
- (Optional) Swap Flask dev server for gunicorn.
- (Optional) Add UI indicators for cache age / offline state.


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

## 2025-12-28 (packaging + sync)
- Packaged SQLite cache as `home_energy_analysis.storage` using pyproject.toml so imports/tests are clean (pip install -e .).
- Included sqlite_schema.sql as package data and updated schema loading to use importlib.resources.
- Configured pytest in pyproject.toml to only collect tests/ (avoids Amber smoke scripts breaking pytest).
- Added scripts/sync_cache.py to refresh SQLite cache on demand (prices + latest usage), prune old rows, and print a one-line status summary.
- What was tested: pip install -e ., pytest (storage tests), running scripts/sync_cache.py updates cache and dashboard reads fresh cached data.
- Next steps: enables future Pi systemd timer + kiosk deployment.

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
