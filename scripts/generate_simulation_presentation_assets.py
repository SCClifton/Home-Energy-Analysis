#!/usr/bin/env python3
"""Generate SVG visual assets for the digital twin presentation."""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Tuple
from zoneinfo import ZoneInfo

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data_local" / "cache.sqlite"
OUT_DIR = PROJECT_ROOT / "docs" / "presentations" / "assets"
SCENARIO_ID = "house_twin_10kw_10kwh"
WINDOW_START = "2025-12-28T00:00:00Z"
WINDOW_END = "2025-12-31T00:00:00Z"

CANVAS_W = 1400
CANVAS_H = 780

COLOR_BG = "#0b1020"
COLOR_PANEL = "#101a33"
COLOR_GRID = "#24324f"
COLOR_TEXT = "#eaf1ff"
COLOR_MUTED = "#9db0d8"
COLOR_OPT = "#2ec4b6"
COLOR_RULE = "#ff9f43"
COLOR_POS = "#22c55e"
COLOR_NEG = "#f97316"


def ensure_out_dir() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)


def write_svg(name: str, body: str) -> None:
    path = OUT_DIR / name
    path.write_text(body, encoding="utf-8")
    print(f"Wrote {path}")


def load_intervals() -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    try:
        df = pd.read_sql_query(
            """
            SELECT
                controller_mode,
                interval_start,
                savings_aud,
                baseline_cost_aud,
                scenario_cost_aud,
                baseline_import_kwh,
                scenario_import_kwh,
                battery_charge_kwh,
                battery_discharge_kwh,
                export_kwh,
                pv_generation_kwh,
                battery_soc_kwh
            FROM simulation_intervals
            WHERE scenario_id = ?
              AND interval_start >= ?
              AND interval_start < ?
            ORDER BY interval_start ASC
            """,
            conn,
            params=(SCENARIO_ID, WINDOW_START, WINDOW_END),
        )
    finally:
        conn.close()

    if df.empty:
        raise RuntimeError("No simulation_intervals found for target window")

    df["interval_start"] = pd.to_datetime(df["interval_start"], utc=True)
    return df


def _header(title: str, subtitle: str) -> List[str]:
    return [
        f'<rect x="0" y="0" width="{CANVAS_W}" height="{CANVAS_H}" fill="{COLOR_BG}"/>',
        f'<text x="48" y="54" font-size="34" fill="{COLOR_TEXT}" font-family="Inter,Segoe UI,sans-serif" font-weight="700">{title}</text>',
        f'<text x="48" y="88" font-size="20" fill="{COLOR_MUTED}" font-family="Inter,Segoe UI,sans-serif">{subtitle}</text>',
    ]


def _svg_wrap(elements: Iterable[str]) -> str:
    defs = """
<defs>
  <style>
    .axis { fill: none; stroke: #5d7096; stroke-width: 1.3; }
    .grid { fill: none; stroke: #24324f; stroke-width: 1; }
    .tick { fill: #9db0d8; font-size: 15px; font-family: Inter,Segoe UI,sans-serif; }
    .legend { fill: #eaf1ff; font-size: 16px; font-family: Inter,Segoe UI,sans-serif; }
    .value { fill: #eaf1ff; font-size: 14px; font-family: Inter,Segoe UI,sans-serif; }
  </style>
  <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">
    <path d="M 0 0 L 10 5 L 0 10 z" fill="#8fb3ff"/>
  </marker>
  <marker id="arrowGreen" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">
    <path d="M 0 0 L 10 5 L 0 10 z" fill="#2ec4b6"/>
  </marker>
  <marker id="arrowOrange" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">
    <path d="M 0 0 L 10 5 L 0 10 z" fill="#ff9f43"/>
  </marker>
</defs>
"""
    content = "\n".join(elements)
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{CANVAS_W}" height="{CANVAS_H}" viewBox="0 0 {CANVAS_W} {CANVAS_H}">\n{defs}\n{content}\n</svg>\n'


def _scale(value: float, vmin: float, vmax: float, out_min: float, out_max: float) -> float:
    if math.isclose(vmax, vmin):
        return (out_min + out_max) / 2.0
    ratio = (value - vmin) / (vmax - vmin)
    return out_min + ratio * (out_max - out_min)


def chart_daily_savings(df: pd.DataFrame) -> None:
    work = df.copy()
    work["date_sydney"] = work["interval_start"].dt.tz_convert(ZoneInfo("Australia/Sydney")).dt.date.astype(str)
    agg = (
        work.groupby(["date_sydney", "controller_mode"], as_index=False)["savings_aud"]
        .sum()
        .sort_values(["date_sydney", "controller_mode"])
    )

    dates = sorted(agg["date_sydney"].unique())
    modes = ["optimizer", "rule"]

    plot_x, plot_y = 110, 140
    plot_w, plot_h = 1210, 540

    vmin = min(float(agg["savings_aud"].min()), -0.05)
    vmax = max(float(agg["savings_aud"].max()), 0.05)
    pad = (vmax - vmin) * 0.15 if vmax > vmin else 0.1
    vmin -= pad
    vmax += pad

    elems = _header("Daily Savings by Controller", "Sydney-local days, backtest window 2025-12-28 to 2025-12-31 UTC")
    elems.append(f'<rect x="{plot_x}" y="{plot_y}" width="{plot_w}" height="{plot_h}" fill="{COLOR_PANEL}" rx="16"/>')

    # Grid + y ticks
    for i in range(6):
        frac = i / 5
        y = plot_y + frac * plot_h
        val = vmax - frac * (vmax - vmin)
        elems.append(f'<line class="grid" x1="{plot_x}" y1="{y:.1f}" x2="{plot_x + plot_w}" y2="{y:.1f}"/>')
        elems.append(f'<text class="tick" x="{plot_x - 14}" y="{y + 5:.1f}" text-anchor="end">{val:+.2f}</text>')

    # Zero line
    y_zero = _scale(0, vmin, vmax, plot_y + plot_h, plot_y)
    elems.append(f'<line x1="{plot_x}" y1="{y_zero:.1f}" x2="{plot_x + plot_w}" y2="{y_zero:.1f}" stroke="#8ba3d8" stroke-width="1.6"/>')

    group_w = plot_w / len(dates)
    bar_w = group_w * 0.28

    for i, day in enumerate(dates):
        gx = plot_x + i * group_w
        elems.append(f'<text class="tick" x="{gx + group_w / 2:.1f}" y="{plot_y + plot_h + 34}" text-anchor="middle">{day}</text>')

        for j, mode in enumerate(modes):
            row = agg[(agg["date_sydney"] == day) & (agg["controller_mode"] == mode)]
            val = float(row["savings_aud"].iloc[0]) if not row.empty else 0.0
            x = gx + group_w * 0.2 + j * (bar_w + group_w * 0.08)
            y_val = _scale(val, vmin, vmax, plot_y + plot_h, plot_y)
            y_top = min(y_zero, y_val)
            h = abs(y_val - y_zero)
            color = COLOR_OPT if mode == "optimizer" else COLOR_RULE
            elems.append(f'<rect x="{x:.1f}" y="{y_top:.1f}" width="{bar_w:.1f}" height="{h:.1f}" fill="{color}" rx="4"/>')
            label_y = y_top - 8 if val >= 0 else y_top + h + 18
            elems.append(f'<text class="value" x="{x + bar_w/2:.1f}" y="{label_y:.1f}" text-anchor="middle">{val:+.3f}</text>')

    # Legend
    lx, ly = plot_x + plot_w - 230, plot_y + 36
    elems.append(f'<rect x="{lx}" y="{ly}" width="16" height="16" fill="{COLOR_OPT}" rx="3"/>')
    elems.append(f'<text class="legend" x="{lx + 24}" y="{ly + 13}">Optimizer</text>')
    elems.append(f'<rect x="{lx}" y="{ly + 28}" width="16" height="16" fill="{COLOR_RULE}" rx="3"/>')
    elems.append(f'<text class="legend" x="{lx + 24}" y="{ly + 41}">Rule</text>')

    write_svg("chart_daily_savings.svg", _svg_wrap(elems))


def chart_cumulative_savings(df: pd.DataFrame) -> None:
    modes = ["optimizer", "rule"]
    plot_x, plot_y = 110, 140
    plot_w, plot_h = 1210, 540

    elems = _header("Cumulative Savings Through Time", "Each point is cumulative sum of interval savings (AUD)")
    elems.append(f'<rect x="{plot_x}" y="{plot_y}" width="{plot_w}" height="{plot_h}" fill="{COLOR_PANEL}" rx="16"/>')

    cumulative = {}
    y_min, y_max = 0.0, 0.0
    for mode in modes:
        mode_df = df[df["controller_mode"] == mode].copy().sort_values("interval_start")
        mode_df["cum"] = mode_df["savings_aud"].cumsum()
        mode_df = mode_df.reset_index(drop=True)
        if mode_df.empty:
            continue
        cumulative[mode] = mode_df
        y_min = min(y_min, float(mode_df["cum"].min()))
        y_max = max(y_max, float(mode_df["cum"].max()))

    pad = (y_max - y_min) * 0.15 if y_max > y_min else 0.1
    y_min -= pad
    y_max += pad

    # Grid
    for i in range(6):
        frac = i / 5
        y = plot_y + frac * plot_h
        val = y_max - frac * (y_max - y_min)
        elems.append(f'<line class="grid" x1="{plot_x}" y1="{y:.1f}" x2="{plot_x + plot_w}" y2="{y:.1f}"/>')
        elems.append(f'<text class="tick" x="{plot_x - 14}" y="{y + 5:.1f}" text-anchor="end">{val:+.2f}</text>')

    max_len = max(len(v) for v in cumulative.values()) if cumulative else 1

    for mode in modes:
        mode_df = cumulative.get(mode)
        if mode_df is None or mode_df.empty:
            continue
        color = COLOR_OPT if mode == "optimizer" else COLOR_RULE
        points = []
        step = max(1, len(mode_df) // 300)
        sampled = mode_df.iloc[::step]
        if sampled.index[-1] != mode_df.index[-1]:
            sampled = pd.concat([sampled, mode_df.tail(1)])

        for idx, row in sampled.iterrows():
            x = _scale(float(idx), 0, max_len - 1, plot_x, plot_x + plot_w)
            y = _scale(float(row["cum"]), y_min, y_max, plot_y + plot_h, plot_y)
            points.append(f"{x:.2f},{y:.2f}")
        elems.append(f'<polyline points="{" ".join(points)}" fill="none" stroke="{color}" stroke-width="3.0"/>')

        end_row = mode_df.iloc[-1]
        x_end = _scale(float(len(mode_df) - 1), 0, max_len - 1, plot_x, plot_x + plot_w)
        y_end = _scale(float(end_row["cum"]), y_min, y_max, plot_y + plot_h, plot_y)
        elems.append(f'<circle cx="{x_end:.2f}" cy="{y_end:.2f}" r="5" fill="{color}"/>')
        elems.append(f'<text class="value" x="{x_end + 10:.1f}" y="{y_end - 10:.1f}" fill="{color}">{mode}: {float(end_row["cum"]):+.3f}</text>')

    # X ticks by date
    all_times = pd.concat([v[["interval_start"]] for v in cumulative.values()]) if cumulative else pd.DataFrame({"interval_start": []})
    if not all_times.empty:
        t_min = all_times["interval_start"].min()
        t_max = all_times["interval_start"].max()
        for i in range(5):
            frac = i / 4
            t = t_min + (t_max - t_min) * frac
            label = t.tz_convert(ZoneInfo("Australia/Sydney")).strftime("%d %b %H:%M")
            x = plot_x + frac * plot_w
            elems.append(f'<text class="tick" x="{x:.1f}" y="{plot_y + plot_h + 34}" text-anchor="middle">{label}</text>')

    write_svg("chart_cumulative_savings.svg", _svg_wrap(elems))


def chart_key_totals(df: pd.DataFrame) -> None:
    summary = (
        df.groupby("controller_mode", as_index=False)
        .agg(
            baseline_import_kwh=("baseline_import_kwh", "sum"),
            scenario_import_kwh=("scenario_import_kwh", "sum"),
            battery_charge_kwh=("battery_charge_kwh", "sum"),
            battery_discharge_kwh=("battery_discharge_kwh", "sum"),
            savings_aud=("savings_aud", "sum"),
        )
        .set_index("controller_mode")
    )

    metrics = [
        ("baseline_import_kwh", "Baseline import"),
        ("scenario_import_kwh", "Scenario import"),
        ("battery_charge_kwh", "Battery charge"),
        ("battery_discharge_kwh", "Battery discharge"),
    ]

    plot_x, plot_y = 110, 140
    plot_w, plot_h = 1210, 540
    elems = _header("Energy Totals by Controller", "kWh totals in backtest window")
    elems.append(f'<rect x="{plot_x}" y="{plot_y}" width="{plot_w}" height="{plot_h}" fill="{COLOR_PANEL}" rx="16"/>')

    max_val = max(float(summary.loc[mode, key]) for mode in summary.index for key, _ in metrics)
    ymax = max_val * 1.2

    for i in range(6):
        frac = i / 5
        y = plot_y + frac * plot_h
        val = ymax - frac * ymax
        elems.append(f'<line class="grid" x1="{plot_x}" y1="{y:.1f}" x2="{plot_x + plot_w}" y2="{y:.1f}"/>')
        elems.append(f'<text class="tick" x="{plot_x - 14}" y="{y + 5:.1f}" text-anchor="end">{val:.1f}</text>')

    group_w = plot_w / len(metrics)
    bar_w = group_w * 0.28

    for i, (key, label) in enumerate(metrics):
        gx = plot_x + i * group_w
        elems.append(f'<text class="tick" x="{gx + group_w / 2:.1f}" y="{plot_y + plot_h + 34}" text-anchor="middle">{label}</text>')
        for j, mode in enumerate(["optimizer", "rule"]):
            val = float(summary.loc[mode, key])
            x = gx + group_w * 0.2 + j * (bar_w + group_w * 0.08)
            y = _scale(val, 0, ymax, plot_y + plot_h, plot_y)
            h = plot_y + plot_h - y
            color = COLOR_OPT if mode == "optimizer" else COLOR_RULE
            elems.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{h:.1f}" fill="{color}" rx="4"/>')
            elems.append(f'<text class="value" x="{x + bar_w/2:.1f}" y="{y - 8:.1f}" text-anchor="middle">{val:.2f}</text>')

    # Savings badges
    opt_s = float(summary.loc["optimizer", "savings_aud"])
    rule_s = float(summary.loc["rule", "savings_aud"])
    elems.append(f'<rect x="960" y="42" width="340" height="70" fill="#102843" rx="12"/>')
    elems.append(f'<text class="legend" x="980" y="72">Savings (AUD): optimizer {opt_s:+.3f}, rule {rule_s:+.3f}</text>')

    write_svg("chart_energy_totals.svg", _svg_wrap(elems))


@dataclass
class MockFlow:
    src: str
    dst: str
    label: str
    color: str


def _mockup_svg(title: str, subtitle: str, flows: List[MockFlow], money_rows: List[Tuple[str, str, str]], out_name: str, accent: str) -> None:
    node_pos = {
        "solar": (250, 250),
        "battery": (460, 520),
        "home": (720, 250),
        "grid": (1100, 250),
    }
    node_color = {
        "solar": "#2ec4b6",
        "battery": "#8b5cf6",
        "home": "#f59e0b",
        "grid": "#60a5fa",
    }

    elems: List[str] = []
    elems.append(f'<rect x="0" y="0" width="{CANVAS_W}" height="{CANVAS_H}" fill="{COLOR_BG}"/>')
    elems.append(f'<rect x="70" y="40" width="1260" height="700" fill="#0f172a" rx="40" stroke="#1f2b44" stroke-width="3"/>')
    elems.append(f'<rect x="100" y="90" width="1200" height="460" fill="#111d37" rx="28"/>')
    elems.append(f'<text x="130" y="138" font-size="36" fill="{COLOR_TEXT}" font-family="Inter,Segoe UI,sans-serif" font-weight="700">{title}</text>')
    elems.append(f'<text x="130" y="174" font-size="22" fill="{COLOR_MUTED}" font-family="Inter,Segoe UI,sans-serif">{subtitle}</text>')
    elems.append(f'<rect x="1090" y="118" width="170" height="36" fill="{accent}" rx="14"/>')
    elems.append(f'<text x="1175" y="142" text-anchor="middle" font-size="16" fill="#071021" font-family="Inter,Segoe UI,sans-serif" font-weight="700">Tesla-style mockup</text>')

    # Nodes
    labels = {
        "solar": "Solar",
        "battery": "Battery",
        "home": "Home",
        "grid": "Grid",
    }
    for key, (x, y) in node_pos.items():
        elems.append(f'<circle cx="{x}" cy="{y}" r="56" fill="{node_color[key]}" opacity="0.95"/>')
        elems.append(f'<text x="{x}" y="{y + 6}" text-anchor="middle" font-size="20" fill="#081124" font-family="Inter,Segoe UI,sans-serif" font-weight="700">{labels[key]}</text>')

    # Flows
    for flow in flows:
        x1, y1 = node_pos[flow.src]
        x2, y2 = node_pos[flow.dst]
        dx = x2 - x1
        dy = y2 - y1
        dist = math.hypot(dx, dy)
        ux, uy = dx / dist, dy / dist
        start_x = x1 + ux * 62
        start_y = y1 + uy * 62
        end_x = x2 - ux * 62
        end_y = y2 - uy * 62
        marker = "arrowGreen" if flow.color == "green" else "arrowOrange" if flow.color == "orange" else "arrow"
        stroke = "#2ec4b6" if flow.color == "green" else "#ff9f43" if flow.color == "orange" else "#8fb3ff"
        elems.append(
            f'<line x1="{start_x:.1f}" y1="{start_y:.1f}" x2="{end_x:.1f}" y2="{end_y:.1f}" '
            f'stroke="{stroke}" stroke-width="7" marker-end="url(#{marker})"/>'
        )
        mx, my = (start_x + end_x) / 2, (start_y + end_y) / 2
        elems.append(
            f'<rect x="{mx - 68:.1f}" y="{my - 21:.1f}" width="136" height="30" rx="12" fill="#081426" opacity="0.92"/>'
        )
        elems.append(
            f'<text x="{mx:.1f}" y="{my + 0:.1f}" text-anchor="middle" font-size="16" fill="#dbeafe" font-family="Inter,Segoe UI,sans-serif">{flow.label}</text>'
        )

    # Money panel
    elems.append(f'<rect x="100" y="574" width="1200" height="130" fill="#0f223f" rx="20"/>')
    elems.append(f'<text x="130" y="614" font-size="26" fill="#dbeafe" font-family="Inter,Segoe UI,sans-serif" font-weight="700">Money Flow (AUD/hour)</text>')
    col_x = [130, 530, 900]
    for (label, value, hint), x in zip(money_rows, col_x):
        elems.append(f'<text x="{x}" y="652" font-size="18" fill="#9db0d8" font-family="Inter,Segoe UI,sans-serif">{label}</text>')
        elems.append(f'<text x="{x}" y="681" font-size="26" fill="#eaf1ff" font-family="Inter,Segoe UI,sans-serif" font-weight="700">{value}</text>')
        elems.append(f'<text x="{x}" y="703" font-size="14" fill="#8fb3ff" font-family="Inter,Segoe UI,sans-serif">{hint}</text>')

    write_svg(out_name, _svg_wrap(elems))


def money_flow_overview() -> None:
    rows = [
        ("Midday solar surplus", 0.0, 0.23),
        ("Evening peak", 0.17, 0.00),
        ("Overnight charge", 0.21, 0.00),
    ]
    net = [(name, imp - exp) for name, imp, exp in rows]

    plot_x, plot_y = 120, 170
    plot_w, plot_h = 1180, 520
    elems = _header("Money Flow by Operating Condition", "Import cost, export revenue, and net spend per hour")
    elems.append(f'<rect x="{plot_x}" y="{plot_y}" width="{plot_w}" height="{plot_h}" fill="{COLOR_PANEL}" rx="16"/>')

    vmin, vmax = -0.30, 0.40
    y_zero = _scale(0.0, vmin, vmax, plot_y + plot_h, plot_y)

    for i in range(8):
        frac = i / 7
        y = plot_y + frac * plot_h
        val = vmax - frac * (vmax - vmin)
        elems.append(f'<line class="grid" x1="{plot_x}" y1="{y:.1f}" x2="{plot_x + plot_w}" y2="{y:.1f}"/>')
        elems.append(f'<text class="tick" x="{plot_x - 15}" y="{y + 5:.1f}" text-anchor="end">{val:+.2f}</text>')

    elems.append(f'<line x1="{plot_x}" y1="{y_zero:.1f}" x2="{plot_x + plot_w}" y2="{y_zero:.1f}" stroke="#8ba3d8" stroke-width="1.6"/>')

    group_w = plot_w / len(rows)
    bar_w = group_w * 0.2
    for i, (name, imp, exp) in enumerate(rows):
        gx = plot_x + i * group_w
        x1 = gx + group_w * 0.22
        x2 = x1 + bar_w + group_w * 0.06
        x3 = x2 + bar_w + group_w * 0.06

        # import (positive)
        y_imp = _scale(imp, vmin, vmax, plot_y + plot_h, plot_y)
        elems.append(f'<rect x="{x1:.1f}" y="{y_imp:.1f}" width="{bar_w:.1f}" height="{y_zero - y_imp:.1f}" fill="#ff9f43" rx="4"/>')

        # export revenue (negative cost)
        y_exp = _scale(-exp, vmin, vmax, plot_y + plot_h, plot_y)
        h_exp = abs(y_exp - y_zero)
        y_top = min(y_zero, y_exp)
        elems.append(f'<rect x="{x2:.1f}" y="{y_top:.1f}" width="{bar_w:.1f}" height="{h_exp:.1f}" fill="#2ec4b6" rx="4"/>')

        # net
        net_val = imp - exp
        y_net = _scale(net_val, vmin, vmax, plot_y + plot_h, plot_y)
        h_net = abs(y_net - y_zero)
        y_net_top = min(y_zero, y_net)
        net_color = COLOR_NEG if net_val > 0 else COLOR_POS
        elems.append(f'<rect x="{x3:.1f}" y="{y_net_top:.1f}" width="{bar_w:.1f}" height="{h_net:.1f}" fill="{net_color}" rx="4"/>')

        elems.append(f'<text class="tick" x="{gx + group_w/2:.1f}" y="{plot_y + plot_h + 36}" text-anchor="middle">{name}</text>')
        elems.append(f'<text class="value" x="{x3 + bar_w/2:.1f}" y="{y_net_top - 8:.1f}" text-anchor="middle">{net_val:+.2f}</text>')

    # legend
    lx, ly = plot_x + plot_w - 300, plot_y + 30
    legends = [("Import cost", "#ff9f43"), ("Export revenue", "#2ec4b6"), ("Net", "#22c55e")]
    for idx, (name, color) in enumerate(legends):
        y = ly + idx * 28
        elems.append(f'<rect x="{lx}" y="{y}" width="15" height="15" fill="{color}" rx="3"/>')
        elems.append(f'<text class="legend" x="{lx + 24}" y="{y + 13}">{name}</text>')

    write_svg("chart_money_flow_conditions.svg", _svg_wrap(elems))


def make_mockups() -> None:
    _mockup_svg(
        title="Midday: Solar Surplus",
        subtitle="Sunny period, moderate house load, battery charging, export active",
        flows=[
            MockFlow("solar", "home", "1.8 kW", "green"),
            MockFlow("solar", "battery", "2.5 kW", "green"),
            MockFlow("solar", "grid", "1.9 kW", "green"),
        ],
        money_rows=[
            ("Import cost", "$0.00/h", "Grid import = 0.0 kW"),
            ("Export revenue", "$0.23/h", "1.9 kW x $0.12"),
            ("Net energy cashflow", "-$0.23/h", "Revenue exceeds import"),
        ],
        out_name="mockup_flow_midday_solar.svg",
        accent="#4ade80",
    )

    _mockup_svg(
        title="Evening Peak: Battery Discharging",
        subtitle="No solar, high tariff period, battery offsets expensive import",
        flows=[
            MockFlow("battery", "home", "3.0 kW", "orange"),
            MockFlow("grid", "home", "0.4 kW", "orange"),
        ],
        money_rows=[
            ("Import cost", "$0.17/h", "0.4 kW x $0.42"),
            ("Avoided import value", "$1.26/h", "3.0 kW supplied by battery"),
            ("Net spend", "$0.17/h", "Before degradation term"),
        ],
        out_name="mockup_flow_evening_peak.svg",
        accent="#fbbf24",
    )

    _mockup_svg(
        title="Overnight: Grid Charging",
        subtitle="Cheap tariff period, charge battery for next-day high-price windows",
        flows=[
            MockFlow("grid", "home", "0.8 kW", "orange"),
            MockFlow("grid", "battery", "2.7 kW", "orange"),
        ],
        money_rows=[
            ("Import cost", "$0.21/h", "3.5 kW x $0.06"),
            ("Expected arbitrage value", "$0.35/h", "Future spread capture"),
            ("Net strategy", "Charge now", "Use later in peak periods"),
        ],
        out_name="mockup_flow_overnight_charge.svg",
        accent="#93c5fd",
    )


def main() -> int:
    ensure_out_dir()
    intervals = load_intervals()
    chart_daily_savings(intervals)
    chart_cumulative_savings(intervals)
    chart_key_totals(intervals)
    money_flow_overview()
    make_mockups()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
