# Project Progress

## 2025-12-23

- What changed: added cost-per-hour calculation in the dashboard UI and a new /api/cost endpoint using Amber usage data.
- Formula used: usage_kw = kwh / (minutes / 60); cost_per_hour = usage_kw * price_per_kwh (c/kWh).
- Known limitations: Amber usage can lag by an interval, interval boundaries may not align with price data, and this is not a full bill calculation.
- What was tested: /api/price and /api/cost endpoints returning JSON when the dashboard is running.
- Next steps: add SQLite storage, improve interval alignment/selection, and wire up Pi kiosk/systemd deployment.

## 2025-12-23 (continued)
- Confirmed Powerpal CSV export format and implemented robust parser.
- Successfully pulled and validated a 91-day window (2025-06-24 → 2025-09-22):
  - 26,208 × 5-minute usage intervals from Powerpal
  - 26,208 matching wholesale price intervals from Amber
- Fixed Amber +1s timestamp offset by flooring to 5-minute buckets.
- Baseline pipeline now supports accurate historical joins of usage + price.
- Next steps: pull remaining Powerpal windows to complete last-12-months baseline, then layer solar / EV / battery scenarios.
