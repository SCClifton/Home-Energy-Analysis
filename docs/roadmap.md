# Roadmap

GitHub issues are the durable backlog for this project. This file is the tracked, human-readable summary of current ordering and ownership; `TODO_v2.md` is kept as a local scratchpad and is intentionally ignored.

## Current Priority

1. **Repo hygiene and restart audit**
   - Keep `main` clean, add pytest CI, close or update stale issues, and remove duplicate legacy source paths.
   - Confirm the Raspberry Pi dashboard runtime with read-only checks before changing services.

2. **Data reliability**
   - Amber usage backfill now has Retry-After aware throttling through PR #17.
   - Powerpal baseline diagnostics and cross-source reconciliation tooling are available through PR #18.
   - Remaining work is to run the live Supabase reconciliation once the Supabase connection is healthy.

3. **Operations and smoke verification**
   - Add a single smoke script that checks local SQLite cache state, dashboard endpoints, and optional Supabase connectivity.
   - Keep Pi documentation aligned with actual systemd units and expected health output.

4. **Dashboard and backend improvements**
   - Improve stale/offline/delayed UI states.
   - Tighten `/api/health`, `/api/totals`, and simulation freshness semantics based on smoke findings.
   - Continue Supabase backend hardening where reconciliation exposes gaps.

## GitHub Issue Mapping

- #16: pytest CI workflow.
- #15: repo tracking hygiene and status docs.
- #10: subsystem smoke verification script.
- #13: dashboard stale/offline indicators.
- #14: production WSGI on the Pi.
- #11: EV/V2H and financial metrics.
- #12: architecture/API/data model docs.

Closed or updated issues should include the validation command and result, not just a summary.
