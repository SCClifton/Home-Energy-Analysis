# TODO (running list)

Last updated: 2026-01-05

This file is a practical checklist aligned with `README.md`, `ProjectPlan.md`, and `PROJECT_PROGRESS.md`.

## Done

### Supabase foundation

* Supabase project created and schema deployed:

  * `ingest_events`, `price_intervals`, `usage_intervals`
* Supabase connectivity stabilised (pooler session mode) and scripts validated:

  * `scripts/test_supabase_db.py`
  * `scripts/load_parquet_to_supabase.py`
* Amber prices backfilled into Supabase (historical range verified).

### Powerpal minute pipeline

* Implemented Powerpal minute CSV export download:

  * windowed downloads (90-day), token redaction, manifest tracking
* Implemented Powerpal minute CSV load to Supabase:

  * idempotent upserts into `usage_intervals` with `source='powerpal'`
  * ingest provenance via `ingest_events`
* Fixed DST edge cases in timestamp parsing (UTC timestamps handled correctly).

## In progress

### Usage baseline consolidation

* Confirm earliest available Powerpal minute history and document the gap (if any).
* Decide whether to backfill older history using a different export setting (if available) or accept earliest minute start.

## Next up (high priority)

### Amber usage ingestion hardening

* Add proper 429 throttling/backoff to `backfill_amber_usage_to_supabase.py`:

  * sleep between requests
  * respect Retry-After if present
  * reduce chunk size dynamically
* Re-run Amber usage backfill for the last ~90 days once throttling is in place.

### Cross-source reconciliation

* Add a comparison report:

  * daily kWh totals Powerpal vs Amber (overlapping periods)
  * highlight missing intervals, timezone offsets, and drift
* Decide which source becomes the canonical “baseline usage” series for modelling (likely Powerpal for history, Amber for near-real-time).

### Forward sync workflow

* Define a simple ongoing cadence:

  * Powerpal: weekly token refresh + last 7 days download/load
  * Amber: continue price forward sync and limited usage forward sync
* Optional: Pi pushes deltas from SQLite cache to Supabase (keep Pi SQLite-first).

## Later (but planned)

### Raspberry Pi kiosk auto-boot

* Make Chromium kiosk start deterministic on reboot (systemd user service or desktop autostart hardening).
* Confirm recovery after power loss without manual steps.

### Modelling phase (baseline 2025)

* Build baseline annual bill and scenario engine inputs from Supabase:

  * solar, battery, EV charging, V2H overlays
  * ROI/payback outputs
* Add sanity checks (energy balance, interval completeness, no negative loads).

### Replace meter (optional)

* Evaluate open metering hardware (OpenEnergyMonitor or similar) if tokenised exports remain too manual for long-term use.

## References

* `README.md` for run commands and environment setup.
* `ProjectPlan.md` for phased roadmap and architecture principles.
* `PROJECT_PROGRESS.md` for a dated log of changes and decisions.
