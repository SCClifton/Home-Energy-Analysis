# Home Energy Dashboard Project Plan

Project name: Home Energy Analysis (fridge dashboard + modelling)

## 1. Purpose

Build a home energy “price + cost” dashboard that runs on a Raspberry Pi with a small screen mounted on the fridge. It should be simple enough that anyone in the house can glance at it and make decisions (run appliances now or later, charge the car now or later).

Then extend the codebase into a modelling tool to estimate the value of:
- Rooftop solar
- EV charging optimisation (Tesla Model Y, 7 kW charger)
- Vehicle-to-home behaviour (V2H), and V2G if feasible
- Home battery storage
- Financial returns (payback, ROI, IRR)

The year-long scenario baseline is historical calendar year 2025 (or the last 12 months if 2025 data is not complete).

## 2. Scope

In scope (core):
- Amber API integration for prices and (if practical) usage
- Local storage of interval time series (prices, usage, computed costs)
- Dashboard UI optimised for a small screen
- Raspberry Pi deployment with autostart on boot and kiosk mode
- Scenario engine using interval data (solar, battery, EV, V2H)
- Financial metrics for each scenario

Out of scope (initially):
- Cloud hosting or multi-user access
- Heavy front-end frameworks
- Home Assistant integration (optional later)

## 2.5 Current status

- Pi dashboard appliance is running with an offline-first SQLite cache and kiosk mode.
- Supabase ingestion exists for prices and Powerpal minute usage.
- Next modelling phase depends on baseline reconciliation and stable usage ingestion.

## 3. Data sources

### 3.1 Amber Electric API (prices + usage)
- Primary source for interval price and usage.
- Usage granularity depends on the site (5 or 30 minute intervals).
- Practical “near real-time” latency must be tested for this account.

### 3.2 Powerpal (optional)
- Current device connects to phone via BLE.
- Direct third-party BLE access might not be supported and could create warranty or anti-tamper risk.
- If not suitable, use exports for historical modelling, or replace with open monitoring.

### 3.3 OpenEnergyMonitor (optional, open alternative)
- Provides more open integration options.
- Can support near real-time local metering via Pi, MQTT, and/or emonCMS style workflows.

### 3.4 Tesla driving and charging (Tessie or Tesla API)
- Goal is to infer driving energy needs (kWh/day) and optimise charging timing.
- Use Tessie if available, or Tesla API depending on feasibility and policy constraints.

## 4. System architecture

High level flow:
1. Ingestion service pulls data from Amber (and later EV data).
2. Storage persists raw and processed interval data locally.
3. Dashboard reads stored data and renders a fridge-friendly UI.
4. Modelling engine reads stored interval data and runs scenario overlays.

Key principle:
- Avoid live API calls from the dashboard page.
- Ingestion writes data, dashboard reads data.

### Local + Supabase split (ops hygiene)

- Local SQLite cache keeps the appliance reliable and offline-first.
- Supabase Postgres is the durable historical store for analysis and modelling.
- Daily keepalive and daily forward-sync jobs keep Supabase warm and current.

## 5. Project phases

### Phase 0: Repo and foundations (done or in progress)
Goals:
- Refactor repo into clear modules for dashboard, ingestion, analysis, and Pi deployment.
- Basic Flask app runs locally.

Deliverables:
- Working local dev environment
- Basic dashboard route
- Repo structure in place

Definition of done:
- New developer can run the app locally in under 10 minutes.

### Phase 1: Live price dashboard (Amber only)
Goals:
- Pull current and near-term forecast prices from Amber.
- Display:
  - current c/kWh
  - next interval(s)
  - simple status indicator (cheap/normal/expensive)
  - last updated timestamp

Implementation notes:
- Start with a clean Amber client module.
- Store prices locally and render from storage (not directly from the API).

Deliverables:
- Amber client with `get_sites()` and price endpoints
- Local price storage
- Dashboard view for price

Definition of done:
- Dashboard updates correctly every few minutes.
- Ingestion survives internet dropouts and resumes.
- Data collected for at least 7 days without manual intervention.

### Phase 2: Cost per hour
Goal:
- Show estimated cost per hour (or cost per interval) based on live or near-live usage.

Two routes:
Route A (Amber usage):
- Use Amber usage data if latency is acceptable.

Route B (local metering):
- Add local metering (OpenEnergyMonitor or other) for near real-time household kW estimate.
- Calculate:
  - cost/hour = current_kW × current_price (c/kWh)

Deliverables:
- Usage ingestion path (Amber or local metering)
- Cost calculation logic
- Dashboard showing cost per hour and recent trend

Definition of done:
- Cost/hour feels “near real-time” for household decision making.
- Dashboard clearly shows when usage data is stale.

### Phase 3: Raspberry Pi deployment (fridge unit)
Goals:
- Run the dashboard on a Pi with a small screen.
- Autostart on boot.
- Full-screen kiosk display.
- Reliable Wi‑Fi and simple UI.

Deliverables:
- Pi setup scripts (install deps, configure service)
- systemd service file(s):
  - dashboard service (runs Flask app)
  - optional ingestion service (scheduler)
- kiosk mode setup (Chromium in full screen)

Definition of done:
- Power cycle recovery without keyboard or mouse.
- Dashboard loads automatically within a reasonable time after boot.
- Stable for at least 2 weeks of household use.

### Phase 3.5: Historical data pipeline hardening

Goals:
- Make the historical pipeline reliable, idempotent, and observable.

Deliverables:
- Amber price backfill (done/mostly done; confirm coverage and gaps).
- Amber usage ingestion with throttling/backoff and clear rate-limit handling (limits acknowledged).
- Powerpal minute CSV pipeline for usage history (if in scope).
- Idempotent upserts and provenance tracking via `ingest_events`.

Definition of done:
- Forward sync runs unattended for 14 days.
- Dashboard loads even when Amber is down (SQLite cache serves data).
- Supabase has continuous last-N-days data for both price and usage.
- Log visibility via journald (e.g. `journalctl -u home-energy-supabase-forward-sync.service --since "10 min ago" --no-pager`).

### Phase 4: 2025 scenario engine (solar + battery + EV + V2H)
Goal:
- Use 2025 interval data (prices + usage) as the baseline.
- Run scenario overlays to estimate savings and financial return.

Sub-components:
Solar model:
- PV generation time series (hourly or interval).
- Compute self-consumption and exports.

EV model:
- Estimate required kWh from driving history (Tessie) or assumptions.
- Charging constraints (7 kW, at-home windows).
- Compare “charge from solar” vs “charge at cheap intervals”.

Battery model:
- Capacity, power limits, round-trip efficiency.
- Shift solar to evening and avoid peak prices.
- Optional degradation assumptions.

V2H model:
- Treat EV battery as a storage resource with availability windows.
- Enforce minimum SoC and user constraints.

Financials:
- Annual bill impact
- payback
- ROI
- IRR (with stated discount rate)

Deliverables:
- Baseline annual bill for 2025 (no assets)
- Scenario runner driven by config (solar size, battery size, EV rules)
- Output summary tables and charts

Definition of done:
- Results reproducible from a single command.
- Reasonable sanity checks pass (energy balances, SOC limits, annual totals).
- Clear documentation of assumptions.

## 6. Data management

Principles:
- Keep code in GitHub.
- Keep large raw datasets and results out of Git.

Suggested local folders (gitignored, can be a symlink to Dropbox):
- `data_raw/` (exports, raw interval pulls)
- `data_processed/` (cleaned datasets)
- `results/` (scenario outputs)

Small sample files (optional) can live in repo for examples only.

## 7. Open questions to resolve early

- How fresh is Amber usage for this site in practice (lag, interval length)?
- Is Powerpal integration allowed and safe, or do we pivot to open metering for true real-time?
- What Tessie exports or endpoints are available, and what data quality do they provide?
- Do we start with rules-based dispatch for battery and EV, then add optimisation later?

## 8. Testing plan

Unit tests:
- tariff and bill calculation functions
- cost/hour calculation from kW and price
- scenario dispatch constraints (battery, EV, V2H)
- data validation and interval alignment

Integration tests:
- Amber client pulls and parses correctly (mocked and live)
- ingestion writes to storage correctly

Sanity checks:
- annual energy and cost totals match expectations
- SOC never violates min/max constraints
- no negative loads, no impossible exports unless explicitly modelled

## Next actions

1. Confirm forward-sync logs show daily runs and no errors for a 14-day window.
2. Validate Supabase last-N-days coverage for both prices and usage.
3. Tune Amber usage throttling/backoff and retry behaviour.
4. Update Pi operational docs as services evolve.

## 9. Documentation and project tracking

Add (or maintain):
- `PROJECT_PROGRESS.md` for running notes (decisions, issues, fixes, links to commits)
- `docs/architecture.md` for system overview
- `docs/decisions_log.md` for major choices and trade-offs
