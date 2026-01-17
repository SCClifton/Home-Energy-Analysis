# Home Energy Analysis

A home energy dashboard for a Raspberry Pi kitchen display, plus a data pipeline for historical analysis and modelling (solar, battery, EV).

The Pi runs as an offline-first appliance using a local SQLite cache. Supabase Postgres is the durable store for historical analysis and modelling.

## What this repo does

1. **Dashboard appliance**: A glanceable display showing current electricity price (c/kWh), cost per hour, and a short-term forecast. Designed for a Raspberry Pi with a 5-inch touchscreen mounted in the kitchen.

2. **Data pipeline**: Scripts to pull prices and usage from Amber Electric, usage history from Powerpal CSV exports, and load everything into Supabase for analysis.

3. **Modelling (planned)**: Scenario engine to estimate the value of rooftop solar, home batteries, EV charging strategies, and vehicle-to-home (V2H).

## Current status (2026-01-05)

### Working

- Raspberry Pi runs as an offline-first appliance (SQLite cache) and boots into Chromium kiosk mode.
- Dashboard runs as a systemd service (`home-energy-dashboard.service`) on port 5050.
- Supabase keepalive timer exists to prevent free-tier pausing.
- Supabase forward sync runs daily and is idempotent.
- Amber prices are backfilled into Supabase from 2024-06-16 to present.
- Powerpal minute CSV pipeline downloads and loads into Supabase (from 2024-12-30 onward).

### Known limitations

- Amber usage history via API is limited (older windows may return 0 rows).
- Amber usage backfill can hit HTTP 429 rate limits (needs throttling and backoff).
- Powerpal CSV export tokens are short-lived (manual refresh required).
- `/api/health` may show `status: stale` when the usage cache is old; this does not prevent the UI from loading.

## Architecture

### Raspberry Pi appliance

1. Flask dashboard runs locally on `http://127.0.0.1:5050`.
2. Dashboard reads from a local SQLite cache for resilience.
3. A systemd timer (if enabled) refreshes the cache from Amber.
4. Chromium runs in kiosk mode pointing to the local dashboard.

### Supabase (historical storage)

Supabase stores time-series data for analysis and modelling:

- `ingest_events` (provenance tracking)
- `price_intervals` (wholesale prices)
- `usage_intervals` (energy consumption)

## Repo structure

| Folder | Purpose |
|--------|---------|
| `dashboard_app/` | Flask web app (UI and API endpoints) |
| `scripts/` | Ingestion and backfill scripts (Amber, Powerpal, Supabase loaders) |
| `src/home_energy_analysis/storage/` | Storage layer (SQLite cache schema, Supabase schema and connection code) |
| `analysis/` | Notebooks and analysis utilities |
| `docs/` | Operational docs (`pi_deployment.md` is the source of truth for Pi setup) |
| `pi/` | Pi helper scripts (update script, service files) |

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

Load your secrets:

```bash
set -a
source config/.env
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

Outputs CSVs to `data_raw/powerpal_minute/` with a manifest for tracking.

Note: Powerpal tokens are short-lived and require manual refresh.

### Load into Supabase

```bash
python scripts/load_powerpal_minute_to_supabase.py \
  --csv data_raw/powerpal_minute/YOUR_FILE.csv \
  --source powerpal \
  --channel-type general
```

The loader handles DST edge cases by treating timestamps as UTC. Inserts are idempotent (safe to rerun).

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
| Kiosk script | `~/bin/home-energy-kiosk.sh` | Chromium launcher (waits for `/api/health`, launches fullscreen) |
| Kiosk user service | `~/.config/systemd/user/home-energy-kiosk.service` | Systemd user unit for kiosk |

### Verify on the Pi

```bash
sudo systemctl status home-energy-dashboard.service --no-pager -l
systemctl --user status home-energy-kiosk.service --no-pager -l
pgrep -a chromium | head -n 1
curl -fsS http://127.0.0.1:5050/api/health | python -m json.tool

# Optional: confirm cache refresh timer exists
systemctl list-timers --all | grep -E "home-energy-sync-cache" || true
```

## Troubleshooting

### Kiosk white screen or keyring prompt

Fixed by Chromium flags in the kiosk script (`--password-store=basic`, `--use-mock-keychain`, `--disable-extensions`). See `docs/pi_deployment.md`.

### Supabase connection failures

- Ensure you are using the pooler hostname and port 5432.
- Ensure the username is `postgres.<project-ref>`, not plain `postgres`.
- If you see `SSL connection has been closed unexpectedly`, retry or restart the Supabase project.

### Amber usage 429 rate limits

Reduce request rate, use smaller chunk sizes, and implement backoff. This is a known limitation that needs hardening.

## Roadmap

### P0: Appliance reliability

- Keep Pi boot-to-dashboard reliable.
- Keep cache refresh and stale handling robust.

### P1: Data reliability

- Add 429-aware backoff to Amber usage backfill.
- Cross-source reconciliation report (Powerpal vs Amber daily totals).
- Define forward sync cadence for both sources.

### P2: Modelling

- Build 2025 baseline (usage + price series).
- Overlay solar, battery, EV charging, V2H scenarios.
- Produce ROI/payback outputs.

## Licence

MIT. See `LICENSE`.

Copyright (c) 2025 Sam Clifton
