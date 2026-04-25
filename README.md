# Home Energy Analysis

A home energy dashboard for a Raspberry Pi kitchen display, plus a data pipeline for historical analysis and modelling (solar, battery, EV).

The Pi runs as an offline-first appliance using a local SQLite cache. Supabase Postgres is the durable store for historical analysis and modelling.

## What this repo does

1. **Dashboard appliance**: A glanceable display showing current electricity price (c/kWh), cost per hour, and a short-term forecast. Designed for a Raspberry Pi with a 5-inch touchscreen mounted in the kitchen.

2. **Data pipeline**: Scripts to pull prices and usage from Amber Electric, usage history from Powerpal CSV exports, and load everything into Supabase for analysis.

3. **Digital twin simulation**: A backtest/live scenario engine for a hypothetical 10 kW PV + 10 kWh battery with export arbitrage and savings outputs for dashboard display.

## Current status (2026-04-25)

### Working

- Raspberry Pi runs as an offline-first appliance (SQLite cache) and boots into Chromium kiosk mode.
- Dashboard runs as a systemd service (`home-energy-dashboard.service`) on port 5050.
- Supabase keepalive timer exists to prevent free-tier pausing.
- Supabase forward sync runs daily and is idempotent.
- Amber prices are backfilled into Supabase from 2024-06-16 to present.
- Amber usage backfill has Retry-After aware throttling and adaptive chunk sizing.
- Powerpal minute CSV pipeline downloads and loads into Supabase (from 2024-12-30 onward).
- Powerpal/Amber daily reconciliation tooling is available for overlapping usage sources.
- Digital twin simulation pipeline is available in both backtest and live modes:
  - Uses Supabase + SQLite cache for historical/live input data.
  - Uses Open-Meteo irradiance/weather near Vaucluse NSW for PV estimates.
  - Stores simulation timeseries + summary in SQLite for offline-first dashboard reads.
- Second dashboard page (`/simulation`) is available with savings, SoC, solar/export metrics, and interval chart data.

### Known limitations

- Amber usage history via API is limited (older windows may return 0 rows).
- Powerpal CSV export tokens are short-lived (manual refresh required).
- Local Supabase smoke testing currently reaches the pooler but fails with `Tenant or user not found`; refresh `SUPABASE_DB_URL` before live reconciliation or Supabase loads.
- The last read-only Pi audit from this Mac could not reach the documented IP (`192.168.5.210`), so live service state still needs confirmation on the LAN or at the Pi.
- `/api/health` may show `status: stale` when the usage cache is old; this does not prevent the UI from loading.
- Simulation weather ingestion depends on network reachability to Open-Meteo. When unavailable, simulation falls back to cached irradiance rows.

## Architecture

### Raspberry Pi appliance

1. Flask dashboard runs locally on `http://127.0.0.1:5050`.
2. Dashboard reads from a local SQLite cache for resilience.
3. A systemd timer (if enabled) refreshes the cache from Amber.
4. A second 5-minute systemd timer runs live digital twin simulation and writes to SQLite.
5. Chromium runs in kiosk mode pointing to the local dashboard.

### Supabase (historical storage)

Supabase stores time-series data for analysis and modelling:

- `ingest_events` (provenance tracking)
- `price_intervals` (wholesale prices)
- `usage_intervals` (energy consumption)

## Repo structure

| Folder | Purpose |
|--------|---------|
| `dashboard_app/` | Flask web app (UI and API endpoints) |
| `scripts/` | Ingestion/backfill/simulation orchestration scripts |
| `src/home_energy_analysis/ingestion/` | Packaged external API clients, including Amber |
| `src/home_energy_analysis/storage/` | Storage layer (SQLite cache schema, Supabase schema and connection code) |
| `analysis/` | Scenario engine, notebooks, and analysis utilities |
| `docs/` | Operational docs (`pi_deployment.md` is the source of truth for Pi setup) |
| `pi/` | Pi helper scripts (update script, service files) |

Roadmap management:

- GitHub issues are the durable backlog.
- `docs/roadmap.md` is the tracked roadmap summary.
- `TODO_v2.md` is ignored local scratch space.

Local-only (gitignored):

- `.venv/` (Python virtual environment)
- `data_raw/`, `data_processed/`, `data_local/` (raw exports, processed files, SQLite cache)
- `logs/`

## Secrets and environment

Never commit secrets.

### Local dev (Mac)

Use `.env.local` (gitignored) and/or export env vars in your shell.

```bash
AMBER_TOKEN=your_token_here
AMBER_SITE_ID=your_site_id_here
SUPABASE_DB_URL=postgresql://USER:PASSWORD@HOST:PORT/postgres
PORT=5050

# Powerpal (usage backfill)
POWERPAL_DEVICE_ID=your_device_id
POWERPAL_TOKEN=your_token
POWERPAL_SAMPLE=1
```

### Raspberry Pi

Runtime environment is stored at `/etc/home-energy-analysis/dashboard.env` (not committed, root-owned). Systemd services load it via `EnvironmentFile=`.

Keys include `AMBER_TOKEN`, `AMBER_SITE_ID`, `SUPABASE_DB_URL`, `PORT`, `SQLITE_PATH`, `RETENTION_DAYS`, `DEBUG`.
Simulation-specific optional keys: `SIM_CONTROLLER`, `SIM_HISTORY_HOURS`, `SIM_FORECAST_HOURS`, `SIM_REFRESH_WEATHER`.
Powerpal refresh keys: either `POWERPAL_EXPORT_URL`, or `POWERPAL_DEVICE_ID`, `POWERPAL_TOKEN`, `POWERPAL_SAMPLE`.

## Local development quickstart (Mac)

### Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -e .
```

### Configure environment

Load your secrets (from `.env.local`) if you want shell-exported variables:

```bash
set -a
source .env.local
set +a
```

### Run the dashboard

```bash
PORT=5050 python dashboard_app/app/main.py
```

Open `http://127.0.0.1:5050/` in your browser.

### Health check

```bash
curl -fsS http://127.0.0.1:5050/api/health | python -m json.tool
```

### Smoke checks

```bash
python scripts/verify_setup.py
python scripts/verify_setup.py --pi-systemd
```

### Live UI iteration loop (recommended)

Use this when tuning dashboard HTML/CSS/JS locally:

```bash
PORT=5050 DEBUG=1 \
AMBER_SITE_ID=YOUR_SITE_ID \
SQLITE_PATH=$(pwd)/data_local/cache.sqlite \
python dashboard_app/app/main.py
```

Then open `http://127.0.0.1:5050/` and hard-refresh (`Cmd+Shift+R`) after edits.
Set browser viewport to `800x480` to mirror the Pi display.

## Dashboard data semantics (important)

The dashboard is cache-first. If usage is delayed, cost-related cards can be stale.

- `CACHED PRICE` means price data is from SQLite cache.
- `Price`/`Usage` freshness pills come from `/api/health` age thresholds.
- `MONTH TO DATE` is computed from cached `usage.cost_aud` rows only.
- If usage data is delayed, the UI intentionally shows "reported"/lag wording.
- If there are no current-month usage rows in cache, MTD may legitimately show `—`.
- `/simulation` reads only from cached `simulation_runs` and `simulation_intervals` rows for offline-first behavior.
- Simulation responses always include `as_of` and stale state semantics.

## Digital twin simulation

### What it models

- Baseline: actual consumption + actual interval prices.
- Scenario: baseline + hypothetical 10 kW PV + 10 kWh battery.
- Battery controls:
  - Rule controller (`--controller rule`)
  - Optimizer-like lookahead controller (`--controller optimizer`) with export arbitrage.

### Default assumptions (explicit)

- PV: `10 kW` nameplate, performance ratio `0.82`, temperature coefficient `-0.004 /°C`.
- Battery: `10 kWh` capacity, `1 kWh` reserve (10%), `5 kW` charge/discharge caps, round-trip efficiency `90%`.
- Export limit: `5 kW`.
- Degradation term: `0.02 AUD/kWh` discharged.
- Tariff valuation: interval Amber wholesale price applied to both import and export cashflow in this model version.

### Run live mode

```bash
python scripts/run_simulation_live.py
```

### Run backtest mode

```bash
python scripts/run_scenario_simulation.py \
  --mode backtest \
  --controller optimizer \
  --start 2025-01-01T00:00:00Z \
  --end 2025-02-01T00:00:00Z \
  --refresh-weather
```

### Simulation API endpoints

- `GET /api/simulation/status`
- `GET /api/simulation/intervals?window=today|mtd|next24h`
- `GET /simulation` (dashboard page)

## Annual purchase-decision analysis

The `/analysis` page shows cache-backed annual solar, battery, and efficiency modelling.
It is separate from the live `/simulation` page so heavy annual analysis can run offline
or on a schedule without blocking the kitchen dashboard.
On the Pi touchscreen, horizontal swipes cycle between `/`, `/simulation`, and `/analysis`.

### Generate the cached analysis

```bash
python scripts/modelling_preflight.py --year 2025
python scripts/run_annual_analysis.py --year 2025 --refresh-weather
```

The preflight command is read-only and reports coverage for usage, price, and irradiance
inputs. The annual analysis command writes one JSON payload into SQLite for cache-first
API/dashboard reads.

On the Pi, `pi/update.sh` installs/enables `home-energy-annual-analysis.timer`,
which runs the same analysis command daily and triggers an immediate run after update.

### Analysis API endpoints

- `GET /api/analysis/scenarios?year=2025`
- `GET /api/analysis/recommendation?year=2025&goal=lowest_cost|fastest_payback|self_sufficiency`
- `GET /api/analysis/load-shift?year=2025`
- `GET /api/analysis/data-quality?year=2025`

### Analysis assumptions

- Powerpal remains an app CSV/export-link workflow only; no direct BLE integration.
- Powerpal is treated as import/consumption data only, not solar export metering.
- Solar sizes: `0, 6.6, 8, 10, 12, 15 kW`.
- Battery sizes: `0, 5, 10, 13.5, 20, 30 kWh`.
- Conservative export value defaults to `2c/kWh`.
- Vaucluse irradiance is modelled from Open-Meteo historical weather and is not measured rooftop output.

## Supabase

### Setup

1. Create a Supabase project.
2. Apply schema via SQL Editor: `src/home_energy_analysis/storage/supabase_schema.sql`
3. Test connectivity:

```bash
python scripts/test_supabase_db.py
```

### Connection notes

- Use the pooler connection string (session mode, port 5432).
- Pooler username format is `postgres.<project-ref>`, not plain `postgres`.

### Backfill Amber prices

```bash
python scripts/backfill_amber_prices_to_supabase.py \
  --start 2024-06-16 \
  --chunk-days 7 \
  --resume false
```

Use `--resume true` for forward sync (continue from latest interval in Supabase).

### Backfill Amber usage

Note: API limits and rate limiting apply. May need throttling.

```bash
python scripts/backfill_amber_usage_to_supabase.py \
  --start 2025-10-05 \
  --chunk-days 7 \
  --min-chunk-days 1 \
  --resume false \
  --channel-type general
```

## Powerpal minute CSV pipeline

### Download exports

Downloads 90-day windows from Powerpal:

```bash
python scripts/pull_powerpal_minute_csv.py --start 2024-10-01 --end 2025-03-31
```

You can also paste the app-generated CSV export URL for a one-off refresh without saving the token:

```bash
python scripts/refresh_powerpal_to_supabase.py \
  --export-url "https://readings.powerpal.net/csv/v1/DEVICE?token=TOKEN&start=...&end=...&sample=1" \
  --start 2025-01-01 \
  --end 2025-12-31
```

Or store it temporarily in `.env.local` / the Pi env as `POWERPAL_EXPORT_URL`. If `--start` and `--end` are omitted, the script uses the date window embedded in the export URL. To backfill a longer period while the token is valid, supply your own `--start` / `--end`; the downloader will split the request into 90-day windows.

Outputs CSVs to `data_raw/powerpal_minute/` with a manifest for tracking.

Note: Powerpal's supported path is still app-generated CSV/export links. Do not use direct BLE access for v1.

### Load into Supabase

```bash
python scripts/load_powerpal_minute_to_supabase.py \
  --csv data_raw/powerpal_minute/YOUR_FILE.csv \
  --source powerpal \
  --channel-type general
```

The loader handles DST edge cases by treating timestamps as UTC. Inserts are idempotent (safe to rerun).

### SQLite cache forward sync

The Pi can also forward recent cached price/usage rows into Supabase with explicit `source='sqlite-cache'` provenance:

```bash
python scripts/sync_sqlite_to_supabase.py --days-back 7
```

`scripts/forward_sync_supabase.py` now runs this cache forwarder after the Amber API backfills unless `--skip-sqlite-cache` is supplied.

## Raspberry Pi deployment

See `docs/pi_deployment.md` for the complete setup guide.

Pi systemd services use `/etc/home-energy-analysis/dashboard.env`.

### Summary

| Component | Path / Unit | Description |
|-----------|-------------|-------------|
| Dashboard service | `home-energy-dashboard.service` | Flask app (starts on boot, restarts on failure) |
| Cache refresh timer | `home-energy-sync-cache.timer` | Cache refresh (if enabled) |
| Supabase keepalive service | `home-energy-supabase-keepalive.service` | Prevents Supabase free-tier pausing |
| Supabase keepalive timer | `home-energy-supabase-keepalive.timer` | Daily keepalive |
| Supabase forward sync service | `home-energy-supabase-forward-sync.service` | Daily forward sync of prices/usage |
| Supabase forward sync timer | `home-energy-supabase-forward-sync.timer` | Daily forward sync schedule |
| Powerpal refresh service | `home-energy-powerpal-refresh.service` | Weekly CSV-link download + Supabase load |
| Powerpal refresh timer | `home-energy-powerpal-refresh.timer` | Weekly Powerpal refresh when configured |
| Simulation live service | `home-energy-simulation.service` | Runs digital twin live-mode pipeline |
| Simulation live timer | `home-energy-simulation.timer` | Every 5 minutes |
| Kiosk script | `~/bin/home-energy-kiosk.sh` | Chromium launcher (waits for `/api/health`, launches fullscreen) |
| Kiosk user service | `~/.config/systemd/user/home-energy-kiosk.service` | Systemd user unit for kiosk |

### Verify on the Pi

```bash
sudo systemctl status home-energy-dashboard.service --no-pager -l
systemctl --user status home-energy-kiosk.service --no-pager -l
pgrep -a chromium | head -n 1
curl -fsS http://127.0.0.1:5050/api/health | python -m json.tool
curl -fsS http://127.0.0.1:5050/api/simulation/status | python -m json.tool

# Optional: confirm cache refresh timer exists
systemctl list-timers --all | grep -E "home-energy-sync-cache|home-energy-simulation" || true
```

### GitHub -> Pi deployment workflow

On your development machine:

```bash
git add -A
git commit -m "Detailed message describing behavior changes and operational impact"
git push
```

On the Pi:

```bash
cd ~/repos/Home-Energy-Analysis
git pull --ff-only
./pi/update.sh
```

Post-deploy verification:

```bash
curl -fsS http://127.0.0.1:5050/api/health | python -m json.tool
curl -fsS http://127.0.0.1:5050/api/totals | python -m json.tool
curl -fsS http://127.0.0.1:5050/api/simulation/status | python -m json.tool
python scripts/verify_setup.py --pi-systemd
systemctl --user status home-energy-kiosk.service --no-pager -l
sudo systemctl list-timers --all | grep home-energy
```

## Troubleshooting

### Kiosk white screen or keyring prompt

Fixed by Chromium flags in the kiosk script (`--password-store=basic`, `--use-mock-keychain`, `--disable-extensions`). See `docs/pi_deployment.md`.

### Supabase connection failures

- Ensure you are using the pooler hostname and port 5432.
- Ensure the username is `postgres.<project-ref>`, not plain `postgres`.
- If you see `SSL connection has been closed unexpectedly`, retry or restart the Supabase project.

### Amber usage 429 rate limits

`scripts/backfill_amber_usage_to_supabase.py` supports Retry-After aware throttling, configurable backoff, and adaptive chunk sizing. Use smaller `--chunk-days`, non-zero `--base-delay`, and `--min-chunk-days 1` for cautious long backfills.

## Roadmap

### P0: Appliance reliability

- Keep Pi boot-to-dashboard reliable.
- Keep cache refresh and stale handling robust.

### P1: Data reliability

- Add 429-aware backoff to Amber usage backfill.
- Cross-source reconciliation report (Powerpal vs Amber daily totals).
- Define forward sync cadence for both sources.

### P2: Modelling

- Extend the digital twin model with EV/V2H options and richer tariff structures.
- Add optimizer improvements (strict optimization formulation).
- Produce ROI/payback outputs from simulation baselines.

## Licence

MIT. See `LICENSE`.

Copyright (c) 2025 Sam Clifton
