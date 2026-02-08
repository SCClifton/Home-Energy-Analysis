#!/usr/bin/env python3
"""Generate polished PNG charts for the digital twin presentation."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data_local" / "cache.sqlite"
OUT = PROJECT_ROOT / "docs" / "presentations" / "assets"
SCENARIO_ID = "house_twin_10kw_10kwh"
START = "2025-12-28T00:00:00Z"
END = "2025-12-31T00:00:00Z"

COLORS = {
    "bg": "#081225",
    "ax": "#0e1a33",
    "grid": "#3e557f",
    "ink": "#eaf1ff",
    "ink_dim": "#9eb2d8",
    "optimizer": "#49d7a2",
    "rule": "#ffb35d",
    "baseline": "#8bb6ff",
    "scenario": "#55e0ab",
    "positive": "#6ce6b9",
    "negative": "#ff8a7f",
}


def _load() -> pd.DataFrame:
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
                battery_soc_kwh,
                export_kwh,
                pv_generation_kwh
            FROM simulation_intervals
            WHERE scenario_id = ?
              AND interval_start >= ?
              AND interval_start < ?
            ORDER BY interval_start
            """,
            conn,
            params=(SCENARIO_ID, START, END),
        )
    finally:
        conn.close()

    if df.empty:
        raise RuntimeError("No simulation data for chart generation")

    df["interval_start"] = pd.to_datetime(df["interval_start"], utc=True)
    return df


def _setup_ax(ax: plt.Axes, title: str | None = None) -> None:
    ax.set_facecolor(COLORS["ax"])
    for spine in ax.spines.values():
        spine.set_color(COLORS["grid"])
    ax.tick_params(colors=COLORS["ink_dim"])
    ax.grid(True, color=COLORS["grid"], alpha=0.25, linewidth=0.8)
    if title:
        ax.set_title(title, color=COLORS["ink"], fontsize=14, weight="bold")


def _save(fig: plt.Figure, filename: str) -> None:
    fig.patch.set_facecolor(COLORS["bg"])
    fig.savefig(OUT / filename, facecolor=COLORS["bg"], dpi=150)
    plt.close(fig)


def _safe_series(df: pd.DataFrame, mode: str, col: str) -> pd.Series:
    subset = df[df["controller_mode"] == mode]
    if subset.empty:
        return pd.Series(dtype=float)
    return subset[col].astype(float)


def chart_daily_savings(df: pd.DataFrame) -> None:
    sydney = ZoneInfo("Australia/Sydney")
    work = df.copy()
    work["day"] = work["interval_start"].dt.tz_convert(sydney).dt.date
    agg = work.groupby(["day", "controller_mode"], as_index=False)["savings_aud"].sum()
    pivot = agg.pivot(index="day", columns="controller_mode", values="savings_aud").fillna(0.0)

    fig, ax = plt.subplots(figsize=(14, 8))
    _setup_ax(ax, "Daily savings by controller (Sydney day)")

    x = np.arange(len(pivot.index))
    width = 0.35
    opt = pivot.get("optimizer", pd.Series(np.zeros(len(x)), index=pivot.index)).to_numpy()
    rule = pivot.get("rule", pd.Series(np.zeros(len(x)), index=pivot.index)).to_numpy()

    bars_opt = ax.bar(x - width / 2, opt, width=width, color=COLORS["optimizer"], label="Optimizer")
    bars_rule = ax.bar(x + width / 2, rule, width=width, color=COLORS["rule"], label="Rule")

    ax.axhline(0, color=COLORS["ink_dim"], linewidth=1.2)
    ax.set_xticks(x)
    ax.set_xticklabels([str(day) for day in pivot.index], color=COLORS["ink_dim"])
    ax.set_ylabel("Savings (AUD/day)", color=COLORS["ink"])
    ax.legend(frameon=False, labelcolor=COLORS["ink"]) 

    for bars in (bars_opt, bars_rule):
        for bar in bars:
            v = bar.get_height()
            y = v + (0.01 if v >= 0 else -0.02)
            va = "bottom" if v >= 0 else "top"
            ax.text(bar.get_x() + bar.get_width() / 2, y, f"{v:+.3f}", ha="center", va=va, color=COLORS["ink"], fontsize=10)

    fig.tight_layout()
    _save(fig, "chart_daily_savings.png")


def chart_cumulative(df: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(14, 8))
    _setup_ax(ax, "Cumulative savings trajectory")

    for mode, color in (("optimizer", COLORS["optimizer"]), ("rule", COLORS["rule"])):
        mode_df = df[df["controller_mode"] == mode].copy().sort_values("interval_start")
        if mode_df.empty:
            continue
        mode_df["cum_savings"] = mode_df["savings_aud"].cumsum()
        final_val = float(mode_df["cum_savings"].iloc[-1])
        ax.plot(
            mode_df["interval_start"],
            mode_df["cum_savings"],
            linewidth=2.7,
            color=color,
            label=f"{mode.capitalize()} ({final_val:+.3f} AUD)",
        )

    ax.set_xlabel("Time (UTC)", color=COLORS["ink"])
    ax.set_ylabel("Cumulative savings (AUD)", color=COLORS["ink"])
    ax.legend(frameon=False, labelcolor=COLORS["ink"])
    fig.autofmt_xdate()
    fig.tight_layout()
    _save(fig, "chart_cumulative_savings.png")


def chart_energy_totals(df: pd.DataFrame) -> None:
    agg = (
        df.groupby("controller_mode", as_index=False)
        .agg(
            baseline_import_kwh=("baseline_import_kwh", "sum"),
            scenario_import_kwh=("scenario_import_kwh", "sum"),
            battery_charge_kwh=("battery_charge_kwh", "sum"),
            battery_discharge_kwh=("battery_discharge_kwh", "sum"),
            export_kwh=("export_kwh", "sum"),
            pv_generation_kwh=("pv_generation_kwh", "sum"),
        )
        .sort_values("controller_mode")
    )

    metrics: Iterable[tuple[str, str]] = (
        ("baseline_import_kwh", "Baseline import"),
        ("scenario_import_kwh", "Scenario import"),
        ("battery_charge_kwh", "Battery charge"),
        ("battery_discharge_kwh", "Battery discharge"),
        ("export_kwh", "Export"),
        ("pv_generation_kwh", "PV generation"),
    )

    fig, axes = plt.subplots(2, 3, figsize=(14, 8))

    for ax, (key, title) in zip(axes.flatten(), metrics):
        _setup_ax(ax, title)
        labels = []
        vals = []
        cols = []
        for mode, color in (("optimizer", COLORS["optimizer"]), ("rule", COLORS["rule"])):
            row = agg[agg["controller_mode"] == mode]
            if row.empty:
                continue
            labels.append(mode.capitalize())
            vals.append(float(row.iloc[0][key]))
            cols.append(color)

        bars = ax.bar(labels, vals, color=cols, width=0.55)
        for bar in bars:
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 0.01,
                f"{bar.get_height():.2f}",
                ha="center",
                va="bottom",
                color=COLORS["ink"],
                fontsize=10,
            )
        ax.tick_params(axis="x", colors=COLORS["ink_dim"])
        ax.set_ylabel("kWh", color=COLORS["ink_dim"])

    fig.suptitle("Energy movement totals by controller", color=COLORS["ink"], fontsize=21, weight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    _save(fig, "chart_energy_totals.png")


def chart_soc_flows(df: pd.DataFrame) -> None:
    mode_df = df[df["controller_mode"] == "optimizer"].copy().sort_values("interval_start")
    if mode_df.empty:
        return

    fig, ax = plt.subplots(figsize=(14, 8))
    _setup_ax(ax, "Optimizer battery dynamics (SoC, charge, discharge)")

    ax.plot(mode_df["interval_start"], mode_df["battery_soc_kwh"], color="#99c3ff", linewidth=2.2, label="SoC (kWh)")
    ax.set_ylabel("Battery SoC (kWh)", color="#99c3ff")
    ax.tick_params(axis="y", colors="#99c3ff")

    ax2 = ax.twinx()
    ax2.set_facecolor("none")
    ax2.plot(mode_df["interval_start"], mode_df["battery_charge_kwh"], color=COLORS["optimizer"], linewidth=1.8, label="Charge")
    ax2.plot(mode_df["interval_start"], mode_df["battery_discharge_kwh"], color=COLORS["rule"], linewidth=1.8, label="Discharge")
    ax2.set_ylabel("Energy per 5-min interval (kWh)", color=COLORS["ink_dim"])
    ax2.tick_params(axis="y", colors=COLORS["ink_dim"])

    for spine in ax2.spines.values():
        spine.set_color(COLORS["grid"])

    lines_l, labels_l = ax.get_legend_handles_labels()
    lines_r, labels_r = ax2.get_legend_handles_labels()
    ax2.legend(lines_l + lines_r, labels_l + labels_r, loc="upper right", frameon=False, labelcolor=COLORS["ink"])

    fig.autofmt_xdate()
    fig.tight_layout()
    _save(fig, "chart_optimizer_soc_flows.png")


def chart_money_breakdown(df: pd.DataFrame) -> None:
    rows = []
    for mode in ("optimizer", "rule"):
        mode_df = df[df["controller_mode"] == mode]
        if mode_df.empty:
            continue
        baseline = float(mode_df["baseline_cost_aud"].sum())
        scenario = float(mode_df["scenario_cost_aud"].sum())
        savings = float(mode_df["savings_aud"].sum())
        rows.append((mode.capitalize(), baseline, scenario, savings))

    fig, ax = plt.subplots(figsize=(14, 8))
    _setup_ax(ax, "Cost and savings breakdown")

    x = np.arange(len(rows))
    width = 0.24
    baseline_vals = [r[1] for r in rows]
    scenario_vals = [r[2] for r in rows]
    savings_vals = [r[3] for r in rows]

    b1 = ax.bar(x - width, baseline_vals, width=width, color=COLORS["baseline"], label="Baseline cost")
    b2 = ax.bar(x, scenario_vals, width=width, color=COLORS["scenario"], label="Scenario cost")
    b3 = ax.bar(
        x + width,
        savings_vals,
        width=width,
        color=[COLORS["positive"] if v >= 0 else COLORS["negative"] for v in savings_vals],
        label="Savings",
    )

    ax.axhline(0, color=COLORS["ink_dim"], linewidth=1.1)
    ax.set_xticks(x)
    ax.set_xticklabels([r[0] for r in rows], color=COLORS["ink"])
    ax.set_ylabel("AUD", color=COLORS["ink"])
    ax.legend(frameon=False, labelcolor=COLORS["ink"])

    for bars in (b1, b2, b3):
        for bar in bars:
            v = bar.get_height()
            y = v + (0.01 if v >= 0 else -0.02)
            va = "bottom" if v >= 0 else "top"
            ax.text(bar.get_x() + bar.get_width() / 2, y, f"{v:+.3f}", ha="center", va=va, color=COLORS["ink"], fontsize=10)

    fig.tight_layout()
    _save(fig, "chart_money_breakdown.png")


def chart_savings_heatmap(df: pd.DataFrame) -> None:
    mode_df = df[df["controller_mode"] == "optimizer"].copy()
    if mode_df.empty:
        return

    sydney = ZoneInfo("Australia/Sydney")
    mode_df["ts_local"] = mode_df["interval_start"].dt.tz_convert(sydney)
    mode_df["day"] = mode_df["ts_local"].dt.date
    mode_df["slot_30m"] = mode_df["ts_local"].dt.hour * 2 + (mode_df["ts_local"].dt.minute // 30)

    pivot = mode_df.pivot_table(index="day", columns="slot_30m", values="savings_aud", aggfunc="mean").fillna(0.0)
    if pivot.empty:
        return

    fig, ax = plt.subplots(figsize=(14, 8))
    _setup_ax(ax, "Optimizer interval savings heatmap (30-min Sydney slots)")

    vmax = float(np.nanmax(np.abs(pivot.values)))
    vmax = max(vmax, 0.001)
    im = ax.imshow(pivot.values, aspect="auto", cmap="coolwarm", vmin=-vmax, vmax=vmax)

    ax.set_yticks(np.arange(len(pivot.index)))
    ax.set_yticklabels([str(v) for v in pivot.index], color=COLORS["ink"])

    xticks = np.arange(0, pivot.shape[1], 4)
    ax.set_xticks(xticks)
    labels = []
    for slot in xticks:
        hour = slot // 2
        minute = 30 if slot % 2 else 0
        labels.append(f"{hour:02d}:{minute:02d}")
    ax.set_xticklabels(labels, color=COLORS["ink_dim"])
    ax.set_xlabel("Australia/Sydney time", color=COLORS["ink"])

    cbar = fig.colorbar(im, ax=ax, fraction=0.025, pad=0.02)
    cbar.set_label("Savings (AUD / 5-min interval)", color=COLORS["ink"])
    cbar.ax.yaxis.set_tick_params(color=COLORS["ink_dim"])
    plt.setp(cbar.ax.get_yticklabels(), color=COLORS["ink_dim"])

    fig.tight_layout()
    _save(fig, "chart_savings_heatmap.png")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    df = _load()

    chart_daily_savings(df)
    chart_cumulative(df)
    chart_energy_totals(df)
    chart_soc_flows(df)
    chart_money_breakdown(df)
    chart_savings_heatmap(df)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
