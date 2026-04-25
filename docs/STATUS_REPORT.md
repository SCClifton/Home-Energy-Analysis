# Home Energy Analysis, Repo Status (2026-04-25, restart audit)

## What’s working now
- Raspberry Pi appliance runs the Flask dashboard via `home-energy-dashboard.service` with a local SQLite cache and a cache refresh timer (`home-energy-sync-cache.timer`).
- Chromium kiosk mode is configured and documented; a user systemd service exists and has been verified as working after reboot in `docs/pi_deployment.md`.
- Dashboard endpoints are implemented and UI renders live-first price, 3-hour forecast, and month-to-date totals (`dashboard_app/app/main.py`, `dashboard_app/app/templates/dashboard.html`, `dashboard_app/app/static/dashboard.js`).
- Supabase schema and ingestion pipeline are in place with idempotent upserts and ingest provenance (`src/home_energy_analysis/storage/supabase_schema.sql`, `src/home_energy_analysis/storage/supabase_db.py`).
- Powerpal minute CSV download and load pipeline works with DST-safe parsing (`scripts/pull_powerpal_minute_csv.py`, `scripts/load_powerpal_minute_to_supabase.py`).
- Digital twin simulation pipeline is implemented with backtest + live modes, writing interval + summary outputs to SQLite cache tables (`analysis/src/scenario/`, `scripts/run_scenario_simulation.py`, `scripts/run_simulation_live.py`).
- Simulation dashboard page and APIs are implemented (`/simulation`, `/api/simulation/status`, `/api/simulation/intervals`, `/api/simulation/flow`).
- Annual purchase-decision analysis is implemented with cache-backed APIs and `/analysis` dashboard page for solar/battery sizing, financial outputs, load shifting, and data quality.
- GitHub is the durable backlog; `docs/roadmap.md` is the tracked summary and local `TODO_v2.md` is ignored.
- Pytest CI is defined in `.github/workflows/pytest.yml`.

## What’s been implemented recently
- Added annual solar/battery decision modelling:
  - Scenario sweeps for configured solar and battery sizes across base and optimizer dispatch.
  - Conservative financial metrics including payback, IRR, effective rate, 15-year cashflow, and net benefit.
  - Load-shifting and energy-efficiency pattern detection from interval usage and prices.
  - Cache-backed analysis payloads in SQLite (`analysis_runs`) and Flask APIs under `/api/analysis/*`.
  - New `/analysis` dashboard page for recommendations, scenario comparison, sensitivity, monthly source mix, bill impact, load-shift opportunities, and data quality.
- Added touch swipe navigation across the Pi kiosk pages (`/`, `/simulation`, `/analysis`).
- Added Pi annual analysis service/timer and update flow:
  - `pi/systemd/home-energy-annual-analysis.service`
  - `pi/systemd/home-energy-annual-analysis.timer`
  - `pi/update.sh` installs/enables the timer and triggers a run after cache refresh.
- Added annual modelling commands:
  - `scripts/modelling_preflight.py --year 2025`
  - `scripts/run_annual_analysis.py --year 2025 --refresh-weather`
- Added annual analysis automated coverage (`tests/test_annual_analysis.py`, `tests/test_analysis_endpoint.py`) and verified full suite passing (`46 passed`).
- Added Powerpal refresh and cache-forwarding operations:
  - `scripts/refresh_powerpal_to_supabase.py` downloads app-generated CSV links and loads the manifest into Supabase.
  - `scripts/pull_powerpal_minute_csv.py` can parse the one-off Powerpal export URL directly.
  - `scripts/sync_sqlite_to_supabase.py` forwards recent SQLite cache rows into Supabase with `source='sqlite-cache'`.
  - `scripts/forward_sync_supabase.py` now runs the SQLite forwarder after Amber API backfills.
  - `pi/systemd/home-energy-powerpal-refresh.*` adds a weekly Pi timer that skips cleanly when Powerpal credentials are not configured.
- Merged PR #17: Amber usage backfill now handles HTTP 429 with Retry-After aware throttling, backoff, and adaptive chunk sizing.
- Merged PR #18: Powerpal loader now supports manifest dry runs with coverage diagnostics, and `scripts/compare_usage_sources.py` compares Powerpal vs Amber daily usage totals.
- Added `scripts/verify_setup.py` for local/Pi smoke checks covering SQLite cache, dashboard endpoints, optional Supabase connectivity, and optional systemd status.
- Moved the active Amber client into the packaged namespace (`src/home_energy_analysis/ingestion/`) and removed tracked duplicate legacy ingestion/processing modules.
- Added `docs/roadmap.md` and ignored scratch presentation exports (`docs/presentations/test_*.pptx`).
- Restored Supabase keepalive artifacts in repo (`scripts/supabase_keepalive.py`, `pi/systemd/home-energy-supabase-keepalive.*`).
- Aligned forward-sync systemd unit with Pi env-file loading (`EnvironmentFile=/etc/home-energy-analysis/dashboard.env`).
- Standardised active script env loading to use process environment with `.env.local` fallback (no hard dependency on `config/.env`).
- Improved dashboard stale-data communication for month-to-date totals:
  - Explicit "reported"/lagging context for delayed usage.
  - Human-readable lag formatting and clearer empty-state messaging when current-month usage is missing from cache.
- Supabase storage + Amber price backfill pipeline with resume support (`scripts/backfill_amber_prices_to_supabase.py`, `scripts/test_supabase_db.py`).
- Powerpal minute export pipeline and loader with manifest tracking (`scripts/pull_powerpal_minute_csv.py`, `scripts/load_powerpal_minute_to_supabase.py`).
- Kiosk service and updated Pi deployment docs (`docs/pi_deployment.md`).
- Dashboard endpoints for forecast and MTD totals plus UI rendering logic (`dashboard_app/app/main.py`, `dashboard_app/app/static/dashboard.js`).
- Added simulation model package:
  - PV model using Open-Meteo irradiance/weather near Vaucluse NSW.
  - Battery SoC + power constraints + degradation term.
  - Rule-based and optimizer-style dispatch modes.
- Extended SQLite schema/storage for simulation cache-first reads:
  - `irradiance`, `simulation_intervals`, `simulation_runs`.
  - Idempotent upsert/read helpers in `sqlite_cache.py`.
- Added Pi timer artifacts for 5-minute live simulation refresh:
  - `pi/systemd/home-energy-simulation.service`
  - `pi/systemd/home-energy-simulation.timer`
- Added simulation-focused automated coverage (`tests/test_scenario_engine.py`, `tests/test_simulation_endpoint.py`) and verified full suite passing (`28 passed`).
- Upgraded front-end design quality for both dashboard pages:
  - Main dashboard style refresh with clearer hierarchy and simulation status integration in Data Status.
  - Simulation dashboard redesign with Tesla-style directional flow board, money-flow cards, and explicit stale-state treatment.
- Created detailed presentation artifacts for stakeholder walkthrough:
  - Source deck: `docs/presentations/digital_twin_simulation_walkthrough_2026-02-08.md`
  - Exported PPTX: `docs/presentations/digital_twin_simulation_walkthrough_2026-02-08.pptx`
  - Supporting chart/flow generators in `scripts/`.

## Known issues and limitations
- Powerpal remains an app-generated CSV/export-link workflow. Direct BLE integration is unsupported and should not be used.
- Annual analysis recommendations are only as good as the loaded usage/price/irradiance coverage; use `scripts/modelling_preflight.py --year 2025` before relying on purchase decisions.
- Annual PV output uses modelled Open-Meteo irradiance near Vaucluse, not measured rooftop generation or roof-shading geometry.
- Local Supabase smoke testing still fails with `Tenant or user not found`; the configured `SUPABASE_DB_URL` needs refresh before live Supabase loads/reconciliation.
- The Pi was found on LAN as `home-energy-pi.local` / `192.168.5.244`; the older `192.168.5.210` reference is stale.
- Simulation weather refresh depends on Open-Meteo network reachability; fallback is cached irradiance rows only.

## What’s missing

### P0
- Refresh/fix `SUPABASE_DB_URL`, then run live Supabase smoke and Powerpal/Amber reconciliation.
- Reconfirm Pi LAN reachability and read-only runtime status (`home-energy-dashboard`, cache timer, simulation timer, kiosk service).
- Use `scripts/verify_setup.py --pi-systemd` on the Pi after pulling this branch/merge.

### P1
- Dashboard offline/stale UI indicators wired to existing API flags.
- Architecture/API/data model documentation pass.

### P2
- EV/V2H extensions and rooftop geometry/shading inputs on top of the shipped annual analysis baseline.
- Replace Flask dev server with gunicorn on Pi.
- Evaluate open metering hardware and document decision.
- Stronger financial validation against installer quotes and external calculators.
- Architecture and API documentation pass.

## Recommended next step
Restore Supabase and Pi runtime visibility before new feature work.

- Refresh the local/Pi `SUPABASE_DB_URL` and rerun `.venv/bin/python scripts/test_supabase_db.py`.
- Use `home-energy-pi.local` for Pi SSH/LAN checks, then run `python scripts/verify_setup.py --pi-systemd` on the Pi.
- Once those pass, run `scripts/compare_usage_sources.py` for the 2025 overlap window and use the result to prioritize dashboard/backend fixes.
- Then run `python scripts/modelling_preflight.py --year 2025` and `python scripts/run_annual_analysis.py --year 2025 --refresh-weather` to populate `/analysis`.

## Quick commands cheat sheet
- How to run locally
  - `python3 -m venv .venv && source .venv/bin/activate`
  - `pip install -r requirements.txt && pip install -e .`
  - `PORT=5050 python dashboard_app/app/main.py`

- How to update the Pi
  - `cd ~/repos/Home-Energy-Analysis && ./pi/update.sh`

- How to verify health
  - `curl -fsS http://127.0.0.1:5050/api/health | python -m json.tool`
  - `systemctl --user status home-energy-kiosk.service --no-pager -l`
  - `sudo systemctl status home-energy-dashboard.service --no-pager -l`
