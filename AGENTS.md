# Multi-Agent Strategy (Home Energy Analysis)

**Last updated:** 2026-02-08  
**Purpose:** Define a practical multi-agent operating model to deliver the roadmap faster with clear ownership, tight handoffs, and reliable verification.

## Project Operating Context
This repo powers a Raspberry Pi kitchen dashboard (offline-first, SQLite cache) and a Supabase-backed historical pipeline used for modelling (solar, battery, EV, V2H).

Primary sources of truth:
- `README.md` for architecture and setup.
- `TODO_v2.md` for priority order and acceptance outcomes.
- `PROJECT_PROGRESS.md` for chronological implementation history.
- `docs/STATUS_REPORT.md` for current state snapshot.
- `docs/pi_deployment.md` for Pi runtime and systemd operations.

## Non-Negotiables
- Never commit secrets. Use `.env.local` for local dev and `/etc/home-energy-analysis/dashboard.env` on Pi.
- Keep dashboard behavior offline-first and cache-first.
- Keep ingestion idempotent and safe to rerun.
- Normalize timestamps to UTC at storage boundaries; use Australia/Sydney only for human-facing time windows.
- Update operational docs when behavior changes.

## Repo Map (Execution-Oriented)
- `dashboard_app/`: Flask endpoints and kiosk UI.
- `scripts/`: ingestion, sync, backfill, verification scripts.
- `src/home_energy_analysis/storage/`: SQLite and Supabase data access layer.
- `pi/`: Pi update flow and systemd units.
- `analysis/`: baseline/scenario modelling code and notebooks.
- `tests/`: endpoint and storage correctness checks.
- `docs/`: deployment, status, decisions, and architecture notes.

## Agent Roster
Use the minimum number of agents needed for a task. Assign exactly one lead agent per task.

### 1) Orchestrator Agent
- Mission: break work into scoped tasks, assign owner, track dependencies, enforce quality gates.
- Owns: sequencing and cross-agent coordination.
- Primary files: `TODO_v2.md`, `PROJECT_PROGRESS.md`, `docs/STATUS_REPORT.md`.
- Deliverables: scoped task brief, owner assignment, done checklist, merged handoff summary.

### 2) Supabase & Data Management Agent
- Mission: schema health, data integrity, idempotent upserts, storage conventions, reconciliation readiness.
- Owns:
  - `src/home_energy_analysis/storage/supabase_db.py`
  - `src/home_energy_analysis/storage/supabase_schema.sql`
  - data-quality scripts and SQL checks in `scripts/`
- Deliverables: reliable ingest/query behavior, integrity checks, clear row-count and range logging.
- Hard requirements:
  - No duplicate interval keys.
  - Explicit source and provenance (`ingest_events`).
  - UTC normalization preserved end-to-end.

### 3) Ingestion Pipeline Agent
- Mission: robust Amber/Powerpal extraction and load workflows with throttling/backoff.
- Owns:
  - `scripts/backfill_amber_prices_to_supabase.py`
  - `scripts/backfill_amber_usage_to_supabase.py`
  - `scripts/pull_powerpal_minute_csv.py`
  - `scripts/load_powerpal_minute_to_supabase.py`
  - `scripts/forward_sync_supabase.py`
- Deliverables: resilient pipelines that tolerate 429/network faults and can be resumed safely.
- Hard requirements:
  - Respect `Retry-After` when present.
  - Configurable backoff and request pacing.
  - Logs include chunk windows, rows fetched, rows upserted, retries.

### 4) Dashboard API Agent
- Mission: Flask endpoint correctness, cache behavior, and totals/health reliability.
- Owns:
  - `dashboard_app/app/main.py`
  - cache interaction boundaries with `src/home_energy_analysis/storage/sqlite_cache.py`
  - endpoint tests in `tests/`
- Deliverables: deterministic cache-first endpoints and truthful health/totals semantics.
- Hard requirements:
  - Works when live credentials are unavailable.
  - `/api/health` reflects freshness accurately.
  - `/api/totals` month window aligns with Australia/Sydney boundaries and correct units.

### 5) Dashboard Design Agent (Raspberry Pi UX)
- Mission: optimize readability and UX for the 5-inch kitchen display.
- Owns:
  - `dashboard_app/app/templates/dashboard.html`
  - `dashboard_app/app/static/dashboard.js`
  - `dashboard_app/app/static/dashboard.css`
- Deliverables: high-legibility UI with explicit stale/offline/delayed indicators.
- Hard requirements:
  - Readable at arm’s length.
  - No ambiguity between live, cached, stale, and estimated values.
  - Graceful behavior during API/data delays.

### 6) Raspberry Pi Ops Agent
- Mission: reliable boot, services, timers, kiosk launch, and repeatable update process.
- Owns:
  - `pi/update.sh`
  - `pi/systemd/*.service`
  - `pi/systemd/*.timer`
  - `docs/pi_deployment.md`
- Deliverables: deterministic reboot behavior and documented operational runbooks.
- Hard requirements:
  - Dashboard and kiosk survive reboot/power-cycle.
  - Services load env from `/etc/home-energy-analysis/dashboard.env`.
  - Verification commands and expected output are documented.

### 7) QA & Verification Agent
- Mission: build confidence before merge and after deployment.
- Owns:
  - `tests/`
  - `scripts/verify_setup.py` (when introduced)
- Deliverables: focused tests for regressions and smoke checks for subsystem health.
- Hard requirements:
  - Validate timestamp normalization and totals windows.
  - Validate critical endpoints (`/api/health`, `/api/price`, `/api/totals`).
  - Emit clear pass/fail and diagnostics.

### 8) Modelling Agent
- Mission: deterministic baseline/scenario analysis for 2025.
- Owns:
  - `analysis/src/`
  - `analysis/notebooks/`
- Deliverables: reproducible baseline and scenario outputs with auditable assumptions.

## Current Priority Routing (P0 Lead + Support)
Align with `TODO_v2.md` and keep one lead per item.

1. MTD cost fix  
Lead: Dashboard API Agent  
Support: Supabase & Data Management Agent, QA & Verification Agent  
Key files: `dashboard_app/app/main.py`, `scripts/sync_cache.py`, `tests/test_totals_endpoint.py`

2. Amber usage 429 throttling/backoff  
Lead: Ingestion Pipeline Agent  
Support: Supabase & Data Management Agent, QA & Verification Agent  
Key files: `scripts/backfill_amber_usage_to_supabase.py`

3. 2025 baseline consolidation  
Lead: Ingestion Pipeline Agent  
Support: Supabase & Data Management Agent, Modelling Agent  
Key files: `scripts/pull_powerpal_minute_csv.py`, `scripts/load_powerpal_minute_to_supabase.py`, `docs/STATUS_REPORT.md`

4. Pi kiosk reliability hardening  
Lead: Raspberry Pi Ops Agent  
Support: Dashboard Design Agent, QA & Verification Agent  
Key files: `pi/systemd/`, `docs/pi_deployment.md`

5. Unified config loading  
Lead: Orchestrator Agent  
Support: Ingestion Pipeline Agent, Dashboard API Agent, Raspberry Pi Ops Agent  
Key files: `scripts/`, `dashboard_app/`, `docs/pi_deployment.md`, `README.md`

6. Cross-source reconciliation report  
Lead: Supabase & Data Management Agent  
Support: Ingestion Pipeline Agent, Modelling Agent  
Key files: `scripts/compare_usage_sources.py` or `analysis/notebooks/`

## Multi-Agent Workflow
1. Intake:
  - Orchestrator selects one scoped item from `TODO_v2.md`.
  - Assign lead + supporting agents.
  - Define explicit acceptance checks and touched files.
2. Implement:
  - Lead agent keeps diff tight and limited to scope.
  - Supporting agents only touch their owned surfaces.
3. Verify:
  - QA runs targeted tests plus smoke checks for changed surfaces.
  - Failures are fed back to lead agent before handoff.
4. Document:
  - If runtime behavior changed, update `docs/pi_deployment.md`.
  - If project state changed, update `docs/STATUS_REPORT.md`.
  - Log outcome in `PROJECT_PROGRESS.md`.
5. Handoff:
  - Lead agent posts concise handoff using template below.

## Handoff Template (Required)
Use this exact structure in updates/PR summaries:

```md
Task:
Owner:
Support:

Scope:
- Files changed:
- Out-of-scope:

Behavior changes:
- 

Validation run:
- Commands:
- Result:

Risks / follow-ups:
- 

Docs updated:
- PROJECT_PROGRESS.md: yes/no
- docs/STATUS_REPORT.md: yes/no
- docs/pi_deployment.md: yes/no
```

## Definition of Done (By Agent)

### Supabase & Data Management Agent
- Upserts remain idempotent.
- Row counts and windows are logged.
- UTC interval conventions preserved.

### Ingestion Pipeline Agent
- 429 and retry behavior is explicit and tested.
- Resume mode does not skip or duplicate target windows.
- Backfill failure modes are observable in logs.

### Dashboard API Agent
- Cache-first behavior remains intact with missing live credentials.
- Health and totals semantics match real cache state.
- Tests cover any changed endpoint logic.

### Dashboard Design Agent
- Stale/offline/delayed states are visually obvious.
- Mobile/Pi layout remains readable without overlap/truncation.
- No regressions in data rendering states.

### Raspberry Pi Ops Agent
- Services/timers are enableable and restart-safe.
- Reboot verification steps are documented and repeatable.
- Env loading path is consistent across units.

### QA & Verification Agent
- Automated checks cover touched critical paths.
- Smoke script (or equivalent commands) validates runtime assumptions.
- Test gaps are explicitly called out if unresolved.

## Quality Gates Before Merge
- Run targeted tests for changed code.
- Run relevant endpoint checks locally when API behavior changed.
- Confirm docs updates for any operational change.
- Confirm no secret material was introduced.

## Coordination Artifacts
- Priority and backlog: `TODO_v2.md`
- Implementation history: `PROJECT_PROGRESS.md`
- Current project state: `docs/STATUS_REPORT.md`
- Pi operations and runbooks: `docs/pi_deployment.md`

## Quick Commands
- Setup: `python3 -m venv .venv && source .venv/bin/activate`
- Install: `pip install -r requirements.txt && pip install -e .`
- Run dashboard: `PORT=5050 python dashboard_app/app/main.py`
- Health: `curl -fsS http://127.0.0.1:5050/api/health | python -m json.tool`
