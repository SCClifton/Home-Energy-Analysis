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

Configure environment variables

Create config/.env (not committed):
AMBER_TOKEN=your_token_here
AMBER_SITE_ID=optional_site_id_here
PORT=5050

Load it into your shell:
set -a
source config/.env
set +a

Run the dashboard
PORT=5050 python dashboard_app/app/main.py

Open:
	•	http://localhost:5050

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

MIT License
Copyright (c) 2025 Sam Clifton