#!/usr/bin/env python3
"""Export a polished digital twin walkthrough PPTX via Keynote automation."""

from __future__ import annotations

import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ASSETS = PROJECT_ROOT / "docs" / "presentations" / "assets"
DB_PATH = PROJECT_ROOT / "data_local" / "cache.sqlite"
OUT_PPTX = PROJECT_ROOT / "docs" / "presentations" / "digital_twin_simulation_walkthrough_2026-02-08.pptx"
SCENARIO_ID = "house_twin_10kw_10kwh"


@dataclass
class SlideSpec:
    title: str
    body: str
    image: Optional[Path] = None
    image_x: int = 90
    image_y: int = 166
    image_width: int = 1180


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _as_expr(text: str) -> str:
    lines = text.split("\n")
    quoted = [f'"{_escape(line)}"' for line in lines]
    if len(quoted) == 1:
        return quoted[0]
    return " & return & ".join(quoted)


def _run_applescript(script: str) -> None:
    subprocess.run(["osascript", "-e", script], check=True)


def _init_doc(title: str, body: str) -> None:
    script = f'''
tell application "Keynote"
  activate
  set d to make new document
  tell d
    tell current slide
      try
        set object text of default title item to {_as_expr(title)}
      end try
      try
        set object text of default body item to {_as_expr(body)}
      end try
    end tell
  end tell
end tell
'''
    _run_applescript(script)


def _add_slide(spec: SlideSpec) -> None:
    if spec.image is not None and not spec.image.exists():
        raise FileNotFoundError(f"Missing image for slide '{spec.title}': {spec.image}")

    image_block = ""
    if spec.image is not None:
        image_block = f'''
      try
        make new image with properties {{file:(POSIX file "{spec.image}"), position:{{{spec.image_x}, {spec.image_y}}}, width:{spec.image_width}}}
      end try
'''

    script = f'''
tell application "Keynote"
  tell front document
    set s to make new slide
    tell s
      try
        set object text of default title item to {_as_expr(spec.title)}
      end try
      try
        set object text of default body item to {_as_expr(spec.body)}
      end try
{image_block}
    end tell
  end tell
end tell
'''
    _run_applescript(script)


def _export_and_close(path: Path) -> None:
    script = f'''
tell application "Keynote"
  tell front document
    set outFile to POSIX file "{path}"
    export to outFile as Microsoft PowerPoint
    close saving no
  end tell
end tell
'''
    _run_applescript(script)


def _load_metrics() -> dict:
    data: dict[str, dict[str, float | str]] = {}
    if not DB_PATH.exists():
        return data

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        for mode in ("optimizer", "rule"):
            cur.execute(
                """
                SELECT as_of,
                       today_savings_aud,
                       mtd_savings_aud,
                       next_24h_projected_savings_aud,
                       current_battery_soc_kwh,
                       today_solar_generation_kwh,
                       today_export_revenue_aud
                FROM simulation_runs
                WHERE scenario_id = ?
                  AND controller_mode = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (SCENARIO_ID, mode),
            )
            row = cur.fetchone()
            if row is not None:
                data[mode] = {k: row[k] for k in row.keys()}

            cur.execute(
                """
                SELECT
                  COALESCE(SUM(baseline_cost_aud), 0) AS baseline_cost,
                  COALESCE(SUM(scenario_cost_aud), 0) AS scenario_cost,
                  COALESCE(SUM(savings_aud), 0) AS savings
                FROM simulation_intervals
                WHERE scenario_id = ?
                  AND controller_mode = ?
                """,
                (SCENARIO_ID, mode),
            )
            totals = cur.fetchone()
            if totals is not None:
                data.setdefault(mode, {})
                data[mode]["baseline_cost"] = totals["baseline_cost"]
                data[mode]["scenario_cost"] = totals["scenario_cost"]
                data[mode]["window_savings"] = totals["savings"]
    finally:
        conn.close()

    return data


def _safe_mode(metrics: dict, mode: str, key: str, default: float = 0.0) -> float:
    value = metrics.get(mode, {}).get(key)
    if value is None:
        return default
    try:
        return float(value)
    except Exception:
        return default


def _summary_slide_body(metrics: dict) -> str:
    opt_today = _safe_mode(metrics, "optimizer", "today_savings_aud")
    opt_mtd = _safe_mode(metrics, "optimizer", "mtd_savings_aud")
    opt_n24 = _safe_mode(metrics, "optimizer", "next_24h_projected_savings_aud")
    rule_today = _safe_mode(metrics, "rule", "today_savings_aud")
    rule_mtd = _safe_mode(metrics, "rule", "mtd_savings_aud")
    rule_n24 = _safe_mode(metrics, "rule", "next_24h_projected_savings_aud")

    return (
        "Latest cached run highlights:\n"
        f"- Optimizer: today {opt_today:+.4f} AUD, MTD {opt_mtd:+.4f} AUD, next24h {opt_n24:+.4f} AUD\n"
        f"- Rule: today {rule_today:+.4f} AUD, MTD {rule_mtd:+.4f} AUD, next24h {rule_n24:+.4f} AUD\n"
        "\n"
        "Interpretation:\n"
        "- Optimizer captures price spreads better in this window\n"
        "- Rule thresholds are easier to interpret but less adaptive"
    )


def main() -> int:
    metrics = _load_metrics()

    slides = [
        SlideSpec(
            title="Presentation scope",
            body=(
                "1. Digital twin from first principles\n"
                "2. Data architecture and offline-first runtime\n"
                "3. Controller logic and physical constraints\n"
                "4. Detailed results and graph diagnostics\n"
                "5. Tesla-style energy and money flow visuals\n"
                "6. Deployment and upgrade path"
            ),
        ),
        SlideSpec(
            title="First principles model",
            body=(
                "Per 5-minute interval:\n"
                "- Baseline cost = load x price\n"
                "- Scenario cost = import x price - export x price + degradation\n"
                "- Savings = baseline - scenario\n"
                "\n"
                "Physical layers:\n"
                "- PV output from irradiance and temperature\n"
                "- Battery SoC dynamics with power and reserve constraints\n"
                "- Dispatch controller selects charge/discharge/export actions"
            ),
        ),
        SlideSpec(
            title="Assumptions used",
            body=(
                "PV assumptions:\n"
                "- 10 kW nameplate, PR 0.82\n"
                "- Temp coefficient -0.004 / degC\n"
                "\n"
                "Battery assumptions:\n"
                "- 10 kWh capacity, 1 kWh reserve, initial 5 kWh\n"
                "- 5 kW charge/discharge/export limits\n"
                "- 90% round-trip efficiency\n"
                "- Degradation term 0.02 AUD/kWh discharged"
            ),
        ),
        SlideSpec(
            title="Data and runtime architecture",
            body=(
                "Inputs:\n"
                "- Amber usage/prices (SQLite cache + Supabase history)\n"
                "- Open-Meteo irradiance near Vaucluse NSW\n"
                "\n"
                "Execution:\n"
                "- backtest mode and 5-minute live mode\n"
                "- writes simulation_intervals + simulation_runs to SQLite\n"
                "\n"
                "Dashboard APIs:\n"
                "- /api/simulation/status\n"
                "- /api/simulation/intervals\n"
                "- /api/simulation/flow"
            ),
        ),
        SlideSpec(
            title="Controller comparison summary",
            body=_summary_slide_body(metrics),
        ),
        SlideSpec(
            title="Daily savings by controller",
            body="Sydney-day aggregate view of interval savings.",
            image=ASSETS / "chart_daily_savings.png",
        ),
        SlideSpec(
            title="Cumulative savings trajectory",
            body="Running savings total over the backtest window.",
            image=ASSETS / "chart_cumulative_savings.png",
        ),
        SlideSpec(
            title="Cost and savings breakdown",
            body="Baseline vs scenario cost and resulting net savings.",
            image=ASSETS / "chart_money_breakdown.png",
        ),
        SlideSpec(
            title="Energy movement totals",
            body="Import, charge, discharge, export and PV totals by controller.",
            image=ASSETS / "chart_energy_totals.png",
        ),
        SlideSpec(
            title="Battery dynamics (optimizer)",
            body="State-of-charge and interval charge/discharge behavior.",
            image=ASSETS / "chart_optimizer_soc_flows.png",
        ),
        SlideSpec(
            title="Interval savings heatmap",
            body="Optimizer interval savings by Sydney 30-minute slot.",
            image=ASSETS / "chart_savings_heatmap.png",
        ),
        SlideSpec(
            title="Flow mockup: midday solar surplus",
            body=(
                "Design objective from Tesla/Home Assistant references:\n"
                "- separate connection ports to avoid ambiguous center crossings\n"
                "- directional energy arrows + dedicated money row"
            ),
            image=ASSETS / "mockup_flow_midday_solar.png",
            image_x=86,
            image_y=148,
            image_width=1200,
        ),
        SlideSpec(
            title="Flow mockup: evening peak support",
            body="Battery-to-home path dominates while grid top-up is explicitly smaller.",
            image=ASSETS / "mockup_flow_evening_peak.png",
            image_x=86,
            image_y=148,
            image_width=1200,
        ),
        SlideSpec(
            title="Flow mockup: overnight arbitrage charge",
            body="Grid-to-battery charging path is isolated from grid-to-home path for clarity.",
            image=ASSETS / "mockup_flow_overnight_charge.png",
            image_x=86,
            image_y=148,
            image_width=1200,
        ),
        SlideSpec(
            title="Dashboard UX changes delivered",
            body=(
                "Main dashboard:\n"
                "- stronger hierarchy, premium card styling, clearer status chips\n"
                "- simulation status integrated in Data Status panel\n"
                "\n"
                "Simulation dashboard:\n"
                "- Tesla-style live flow board\n"
                "- money flow cards (import/export/net/savings)\n"
                "- stale indicators and as_of surfaced in header"
            ),
        ),
        SlideSpec(
            title="Operational behavior",
            body=(
                "Live simulation job:\n"
                "- run_simulation_live.py every 5 minutes\n"
                "- cache-first writes to SQLite simulation tables\n"
                "\n"
                "API behavior:\n"
                "- always includes as_of and stale flags\n"
                "- supports offline dashboard reads\n"
                "- avoids blocking UI when upstream APIs are unavailable"
            ),
        ),
        SlideSpec(
            title="Recommended next upgrades",
            body=(
                "1. Deterministic weather fallback (clear-sky + cached blend)\n"
                "2. Optional LP/MILP optimization backend\n"
                "3. Network tariff and feed-in asymmetry modeling\n"
                "4. EV/V2H coupling scenarios\n"
                "5. Automated reconciliation report to validate savings confidence"
            ),
        ),
        SlideSpec(
            title="Reproducibility commands",
            body=(
                ".venv/bin/python scripts/run_scenario_simulation.py --mode backtest --controller optimizer --site-id 01J061Q7Q883JF26YMGZVVTMV9 --start 2025-12-28T00:00:00Z --end 2025-12-31T00:00:00Z\n"
                "\n"
                ".venv/bin/python scripts/run_scenario_simulation.py --mode backtest --controller rule --site-id 01J061Q7Q883JF26YMGZVVTMV9 --start 2025-12-28T00:00:00Z --end 2025-12-31T00:00:00Z\n"
                "\n"
                "MPLBACKEND=Agg MPLCONFIGDIR=/tmp .venv/bin/python scripts/generate_simulation_presentation_pngs.py\n"
                ".venv/bin/python scripts/generate_flow_mockup_pngs.py\n"
                ".venv/bin/python scripts/export_simulation_pptx_with_keynote.py"
            ),
        ),
    ]

    _init_doc(
        title="Home Energy Digital Twin",
        body="Professional walkthrough: model, results, UX, and operational flow\nDate: 2026-02-08",
    )

    for spec in slides:
        _add_slide(spec)

    _export_and_close(OUT_PPTX)
    print(f"Exported {OUT_PPTX}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
