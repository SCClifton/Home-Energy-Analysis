# Home Energy Dashboard and Modelling

This project builds a simple, glanceable home energy dashboard for the kitchen, then extends it into a modelling tool for solar, batteries, and EV charging.

The end goal is a small Raspberry Pi with a touchscreen mounted on the fridge that shows:
- Current electricity price (c/kWh) from Amber
- Estimated cost per hour (based on household usage)
- A simple “cheap / normal / expensive” indicator

Later phases add scenario modelling using historical calendar year 2025 (or the last 12 months) to estimate the value of:
- Rooftop solar (size options, self-consumption, exports)
- EV charging (Tesla Model Y, 7 kW home charger), solar vs cheap grid charging
- Vehicle-to-home behaviour (V2H), and V2G if feasible
- Home battery (Powerwall and alternatives), including payback, ROI, and IRR

## Status

Current state (local dev):
- Flask dashboard skeleton is running (basic “Dashboard running” page)
- Amber ingestion scripts exist and are being refactored into a cleaner client
- Repo structure has been refactored to separate dashboard, ingestion, analysis, and Raspberry Pi deployment

## Current features

- Current wholesale price (c/kWh)
- Estimated cost per hour (based on last interval)

## Endpoints

- /api/price
- /api/cost

Next step:
- Create a new Amber API token and wire in a proper `amber_client.py`

## Architecture (high level)

1. Ingestion pulls interval prices and usage from Amber.
2. Data is stored locally (start with SQLite and/or parquet for analysis outputs).
3. Dashboard reads the stored data and renders a simple view for the fridge screen.
4. Modelling scripts use the same stored data to run solar, EV, and battery scenarios.

## Data sources

Planned and/or in progress:
- Amber Electric API (prices, usage)
- Powerpal (optional, likely via exports rather than direct BLE integration)
- OpenEnergyMonitor (open alternative for real-time local metering)
- Tessie (Tesla driving and charging history) or Tesla API where feasible

## Repo structure

Key folders:
- `dashboard_app/`  
  Flask web app (UI + API endpoints later)
- `ingestion/`  
  Amber client and ingestion jobs (scheduled pulls, data validation)
- `analysis/`  
  Modelling code, notebooks, and scenario engine (solar, battery, EV, finance)
- `pi/`  
  Raspberry Pi setup scripts and systemd service definitions
- `docs/`  
  Notes, architecture, and decisions log

Local-only (gitignored):
- `.venv/` (Python virtual environment)
- `data/` or `Data/` (raw exports, large files)
- `logs/`

## Local setup

### Prerequisites
- macOS or Linux
- Python 3.11+ recommended
- An Amber API token (create in the Amber app)

### Create and activate a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Configure environment variables (local dev)

Create `config/.env` (not committed):

```bash
AMBER_TOKEN=your_token_here
AMBER_SITE_ID=your_site_id_here
PORT=5050

# Powerpal (usage backfill)
POWERPAL_DEVICE_ID=...
POWERPAL_TOKEN=...
POWERPAL_SAMPLE=...
```

Load into your shell:

```bash
set -a
source config/.env
set +a
```

### Run the dashboard

```bash
PORT=5050 python dashboard_app/app/main.py
```

Open:

* [http://localhost:5050](http://localhost:5050)

**Note:** Do not commit `config/.env` or `.env.local` to git.

### Sync cache
Refresh the SQLite cache with latest data from Amber API:

**Note:** This requires `AMBER_TOKEN` and `AMBER_SITE_ID` to be loaded from `config/.env`.

```bash
set -a
source config/.env
set +a
export SQLITE_PATH="$PWD/data_local/cache.sqlite"
python scripts/sync_cache.py
```

Test the endpoint:
```bash
curl -s http://127.0.0.1:5050/api/totals | python -m json.tool
```

### Supabase (optional)

This project supports storing data in Supabase Postgres alongside the Raspberry Pi SQLite cache. The Pi remains SQLite-first for appliance reliability, Supabase is the durable store for historical analysis.

#### Environment files

* `config/.env` (local dev, not committed): Amber + Powerpal credentials.
* `.env.local` (repo root, not committed): Supabase Postgres connection string.

Create `.env.local` in the repo root:

```bash
# Supabase (Mac only)
SUPABASE_DB_URL=postgresql://USER:PASSWORD@HOST:PORT/postgres
```

When running scripts, we load env in this order:

1. `config/.env` (Amber/Powerpal)
2. `.env.local` (Supabase override)

**Note:** Do not commit `config/.env` or `.env.local` to git.

#### Supabase setup

1. Create a Supabase project.
2. In Supabase, open SQL Editor and run:
   `src/home_energy_analysis/storage/supabase_schema.sql`
3. Test the connection:

```bash
python scripts/test_supabase_db.py
```

#### Connection notes (pooler vs direct)

* **Recommended (most networks): Pooler (Session mode)**
  Use the pooler connection string shown in Supabase "Connect". It typically uses:

  * host: `aws-1-ap-southeast-2.pooler.supabase.com`
  * port: `5432`
  * user: `postgres.<project-ref>` (example: `postgres.naebksqkrgixatdzgmir`)
* **Direct connection (IPv6-only)**
  Supabase direct connections may fail on IPv4-only or IPv6-not-routable networks, even if DNS shows an AAAA record.

#### Load parquet into Supabase

Use your Amber site id from `config/.env` (AMBER_SITE_ID).

Load prices:

```bash
python scripts/load_parquet_to_supabase.py \
  --kind prices \
  --parquet data_processed/prices_2025-12-20_2025-12-23.parquet \
  --site-id YOUR_AMBER_SITE_ID \
  --source amber \
  --is-forecast false
```

Load usage:

```bash
python scripts/load_parquet_to_supabase.py \
  --kind usage \
  --parquet data_processed/usage_2025-12-20_2025-12-23.parquet \
  --site-id YOUR_AMBER_SITE_ID \
  --source amber \
  --channel-type general
```

The script handles:
- Column name normalization (e.g., `per_kwh` → `price_cents_per_kwh`)
- Timezone conversion to UTC
- Idempotent upserts (safe to run multiple times)
- Missing columns (gracefully handles optional fields)

#### Backfill from Amber API into Supabase

Prices backfill (7-day chunks):

```bash
python scripts/backfill_amber_prices_to_supabase.py \
  --start 2024-06-16 \
  --chunk-days 7 \
  --resume false
```

Notes:

* Use `--resume false` for historical backfills.
* Use `--resume true` later for forward sync (continue from latest interval already in Supabase).

Usage backfill (Amber API limitations + rate limits):

* Amber usage history via API may be limited (older windows can return 0 rows).
* Usage backfill can hit HTTP 429 rate limits. If you see 429s, reduce request rate (smaller windows) and retry later.

Example usage backfill attempt for recent windows:

```bash
python scripts/backfill_amber_usage_to_supabase.py \
  --start 2025-10-05 \
  --chunk-days 7 \
  --min-chunk-days 1 \
  --resume false \
  --channel-type general
```

#### Troubleshooting

* `FATAL: password authentication failed`
  Check you used the correct password and the correct username. Pooler requires `postgres.<project-ref>` not plain `postgres`.
* `SSL connection has been closed unexpectedly` or `Circuit breaker open`
  Pooler instability or upstream DB not available. Retry, restart the Supabase project, and rely on connection retries (implemented in `supabase_db.get_conn()`).
* `failed to resolve host ...` (Python) while `dig` works
  DNS resolver path issue. Prefer pooler hostname and retry.

Raspberry Pi deployment (planned)

Hardware (typical):
	•	Raspberry Pi 5 (4GB is fine for a kiosk dashboard)
	•	5-inch DSI touchscreen
	•	Reliable 5V USB-C supply (mains power is strongly recommended for always-on display)

Deployment approach:
	•	Install Raspberry Pi OS
	•	Install project dependencies
	•	Run the Flask app as a systemd service
	•	Launch Chromium in kiosk mode on boot pointing to http://localhost:<port>

All Pi-specific scripts and service files live under pi/.

Roadmap and definition of done

Phase 1: Live price dashboard (Amber only)
	•	Show current c/kWh and next interval(s)
	•	Cache and log price history locally
Definition of done:
	•	Dashboard shows price and updates reliably
	•	Ingestion runs unattended for at least 7 days

Phase 2: Cost per hour

Route A (Amber usage):
	•	Use Amber interval usage if latency is acceptable
Route B (local metering):
	•	Use local hardware (OpenEnergyMonitor or similar) for near real-time kW
Definition of done:
	•	Dashboard shows cost/hour with a clear “last updated” timestamp

Phase 3: Raspberry Pi fridge display
	•	Autostart on boot, full-screen kiosk
	•	Readable at a glance
Definition of done:
	•	Power cycle recovery without keyboard/mouse
	•	Stable for at least 2 weeks of daily household use

Phase 4: 2025 scenario engine (solar + battery + EV + V2H)
	•	Build baseline 2025 bill model
	•	Overlay solar generation, storage dispatch, EV charging, V2H rules
Definition of done:
	•	Scenarios produce consistent annual cost and key metrics
	•	Results are reproducible from a single command

Testing (planned)
	•	Unit tests:
	•	tariff and cost calculations
	•	interval alignment and data validation
	•	dispatch constraints (battery and EV)
	•	Integration tests:
	•	“pull Amber data and store it” end-to-end (mocked and live)
	•	Sanity checks:
	•	annual totals, seasonality, bounds checks

Notes

This repo deliberately keeps large datasets out of Git.
Use a local data/ folder (often a symlink to Dropbox) for raw exports and results.

Licence: MIT, see LICENSE
Copyright (c) 2025 Sam Clifton

## Historical baseline (Powerpal + Amber)

Amber’s API provides long history for wholesale prices but only limited history for usage.
To build a longer historical baseline, this project uses:

- **Powerpal CSV exports** for usage (up to ~90 days per export, up to ~12 months history)
- **Amber API** for wholesale prices over the same date ranges

### Scripts

**Powerpal usage → 5-minute kWh parquet**
```bash
python scripts/pull_powerpal.py --start YYYY-MM-DD --end YYYY-MM-DD
```

Output:
`data_processed/powerpal/powerpal_usage_5min_<start>_<end>.parquet`

**Amber prices → parquet**
```bash
python scripts/pull_historical.py --start YYYY-MM-DD --end YYYY-MM-DD --outdir data_processed
```

Output:
`data_processed/prices_<start>_<end>.parquet`

**Timestamp alignment**

Powerpal usage is aligned exactly on 5-minute boundaries (…:00).
Amber prices often arrive with a +1 second offset (…:01).

During baseline modelling, Amber price timestamps are floored to 5-minute buckets to ensure perfect alignmente data.

All baseline costs are energy-only wholesale and exclude network charges, supply charges, and GST.

Note: data_raw/ and data_processed/ are git-ignored and never committed.

