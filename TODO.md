# TODO (running list)

Last updated: 2026-01-06

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

### Raspberry Pi appliance

* Dashboard service running via systemd, auto-starts on boot
* SQLite cache sync timer active (every 5 minutes)
* Kiosk mode Chromium launcher working (manual launch; auto-start on reboot still needs hardening)

## Bugs (P0)

### Fix month-to-date cost calculation (dashboard)

**Observed behaviour:**  
MTD cost shows **$655.09** as of Monday ~1am, which is clearly incorrect for ~5 days of household electricity (likely wrong by an order of magnitude).

**Expected behaviour:**  
MTD should match sum of interval costs for current month (Australia/Sydney timezone) and be plausible (e.g., ~$20–50 for first week of month).

**Where to look:**
* `dashboard_app/app/main.py` — `/api/totals` endpoint (lines ~580–710)
* `scripts/sync_cache.py` — how `cost_aud` is stored in SQLite `usage` table
* Check if `cost_aud` values are in cents vs dollars

**Hypotheses to check:**
* [ ] Cents vs dollars unit mismatch (multiplying by 100, or treating cents as dollars)
* [ ] Time window filter wrong (not restricting to current month, timezone boundary bug, inclusive/exclusive errors)
* [ ] Aggregation double-counting intervals
* [ ] Using price (c/kWh) without multiplying by kWh, or using W instead of kWh
* [ ] Mixing Amber prices with Powerpal minute usage incorrectly

**Debug steps:**
* [ ] Log the start/end timestamps used for "month-to-date" (check `month_start_utc_str` calculation)
* [ ] Print number of intervals summed (`intervals_count` in response)
* [ ] Print min/max interval timestamps included in query
* [ ] Compare sum of kWh and average c/kWh to sanity-check
* [ ] Query SQLite directly: `SELECT SUM(cost_aud), COUNT(*) FROM usage WHERE interval_start >= ? AND cost_aud IS NOT NULL`
* [ ] Check sample `cost_aud` values in database (are they 0.01–0.50 range or 1–50 range?)

**Acceptance criteria:**
* [ ] MTD matches a direct SQL/query check (or a one-off script sum) for the same period
* [ ] Add a regression test for `/api/totals` that checks MTD is computed over the correct window and units
* [ ] MTD value is plausible for the number of days elapsed in the month

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
* Decide which source becomes the canonical "baseline usage" series for modelling (likely Powerpal for history, Amber for near-real-time).

### Usage baseline consolidation

* Confirm earliest available Powerpal minute history and document the gap (if any).
* Decide whether to backfill older history using a different export setting (if available) or accept earliest minute start.
* Load all available Powerpal minute data into Supabase for 2025 baseline.

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
