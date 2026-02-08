#!/usr/bin/env python3
"""Generate high-fidelity Tesla-style energy and money flow mockup PNGs."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT = PROJECT_ROOT / "docs" / "presentations" / "assets"

PALETTE = {
    "bg": "#070f1f",
    "panel": "#101d36",
    "panel2": "#132642",
    "ink": "#edf3ff",
    "ink_dim": "#9fb4da",
    "solar": "#4be4a9",
    "battery": "#ffb05d",
    "grid": "#84b7ff",
    "home": "#d8e6ff",
    "good": "#61e1b0",
    "bad": "#ff8f86",
}


def _add_card(ax, x, y, w, h, radius=24, face="#101d36", edge="#25395f", lw=1.4):
    patch = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle=f"round,pad=0.012,rounding_size={radius}",
        linewidth=lw,
        edgecolor=edge,
        facecolor=face,
    )
    ax.add_patch(patch)
    return patch


def _draw_node(ax, x, y, label, value, fill, edge="none"):
    circle = Circle((x, y), 58, facecolor=fill, edgecolor=edge, linewidth=1.4, alpha=0.96)
    ax.add_patch(circle)
    ax.text(x, y - 8, label, ha="center", va="center", color="#081124", fontsize=14, fontweight="bold")
    ax.text(x, y + 16, value, ha="center", va="center", color="#081124", fontsize=12, fontweight="bold")


def _draw_flow(ax, start, end, label, color, width, rad, label_xy):
    arrow = FancyArrowPatch(
        start,
        end,
        connectionstyle=f"arc3,rad={rad}",
        arrowstyle="-|>",
        mutation_scale=17,
        linewidth=width,
        color=color,
        alpha=0.96,
        shrinkA=8,
        shrinkB=8,
    )
    ax.add_patch(arrow)

    lx, ly = label_xy
    label_box = FancyBboxPatch(
        (lx - 66, ly - 14),
        132,
        26,
        boxstyle="round,pad=0.02,rounding_size=9",
        linewidth=0.9,
        edgecolor="#2a3e65",
        facecolor="#0b172d",
        alpha=0.95,
    )
    ax.add_patch(label_box)
    ax.text(lx, ly - 1, label, ha="center", va="center", color=PALETTE["ink"], fontsize=11, fontweight="bold")


def draw_mockup(title, subtitle, scenario_chip, flows, money_rows, out_name):
    fig = plt.figure(figsize=(14, 8), dpi=160)
    ax = fig.add_subplot(111)
    ax.set_xlim(0, 1400)
    ax.set_ylim(0, 800)
    ax.axis("off")

    fig.patch.set_facecolor(PALETTE["bg"])
    ax.set_facecolor(PALETTE["bg"])

    _add_card(ax, 40, 34, 1320, 732, radius=30, face="#0c1730", edge="#203256", lw=2.0)
    _add_card(ax, 84, 212, 1232, 370, radius=24, face=PALETTE["panel"], edge="#273b63", lw=1.2)
    _add_card(ax, 84, 602, 1232, 124, radius=20, face=PALETTE["panel2"], edge="#2f4775", lw=1.2)

    ax.text(110, 124, "Home Energy Twin", color=PALETTE["ink_dim"], fontsize=12, fontweight="bold")
    ax.text(110, 162, title, color=PALETTE["ink"], fontsize=30, fontweight="bold")
    ax.text(110, 195, subtitle, color=PALETTE["ink_dim"], fontsize=14)

    chip = _add_card(ax, 1040, 118, 250, 38, radius=12, face="#2d8cff", edge="#2d8cff", lw=0)
    chip.set_alpha(0.92)
    ax.text(1165, 137, scenario_chip, color="#041025", fontsize=11, ha="center", va="center", fontweight="bold")

    node = {
        "solar": {"c": (220, 410), "ports": {"right_top": (278, 390), "right_mid": (278, 410), "right_bot": (278, 430)}},
        "battery": {"c": (220, 290), "ports": {"right_top": (278, 270), "right_mid": (278, 290), "right_bot": (278, 310)}},
        "home": {"c": (590, 350), "ports": {"left_top": (532, 330), "left_mid": (532, 350), "left_bot": (532, 370), "right_mid": (648, 350)}},
        "grid": {"c": (940, 350), "ports": {"left_top": (882, 330), "left_mid": (882, 350), "left_bot": (882, 370)}},
    }

    _draw_node(ax, *node["solar"]["c"], "SOLAR", "Live", PALETTE["solar"])
    _draw_node(ax, *node["battery"]["c"], "BATTERY", "SoC", PALETTE["battery"])
    _draw_node(ax, *node["home"]["c"], "HOME", "Load", PALETTE["home"], edge="#9db9ea")
    _draw_node(ax, *node["grid"]["c"], "GRID", "Net", PALETTE["grid"])

    for item in flows:
        _draw_flow(
            ax,
            start=node[item["src"]]["ports"][item["src_port"]],
            end=node[item["dst"]]["ports"][item["dst_port"]],
            label=item["label"],
            color=item["color"],
            width=item["width"],
            rad=item["rad"],
            label_xy=item["label_xy"],
        )

    ax.text(110, 632, "Money Flow (AUD/hour)", color=PALETTE["ink"], fontsize=20, fontweight="bold")
    card_w = 286
    for i, (label, value, detail, polarity) in enumerate(money_rows):
        x = 110 + i * (card_w + 12)
        color = PALETTE["good"] if polarity == "good" else (PALETTE["bad"] if polarity == "bad" else PALETTE["ink"])
        _add_card(ax, x, 650, card_w, 62, radius=12, face="#102244", edge="#2d4370", lw=1.0)
        ax.text(x + 12, 671, label, color=PALETTE["ink_dim"], fontsize=10, ha="left")
        ax.text(x + 12, 695, value, color=color, fontsize=16, ha="left", fontweight="bold")
        ax.text(x + card_w - 10, 695, detail, color=PALETTE["ink_dim"], fontsize=9, ha="right")

    fig.tight_layout(pad=0)
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / out_name, facecolor=PALETTE["bg"])
    plt.close(fig)


def main() -> int:
    draw_mockup(
        title="Midday Solar Surplus",
        subtitle="Solar serves home first, charges battery second, exports remaining surplus",
        scenario_chip="Scenario A - Solar Peak",
        flows=[
            {
                "src": "solar",
                "src_port": "right_top",
                "dst": "home",
                "dst_port": "left_top",
                "label": "Solar to home 1.8 kW",
                "color": PALETTE["solar"],
                "width": 4.6,
                "rad": 0.08,
                "label_xy": (410, 398),
            },
            {
                "src": "solar",
                "src_port": "right_bot",
                "dst": "battery",
                "dst_port": "right_top",
                "label": "Solar to battery 2.5 kW",
                "color": PALETTE["solar"],
                "width": 5.2,
                "rad": 0.34,
                "label_xy": (380, 338),
            },
            {
                "src": "solar",
                "src_port": "right_mid",
                "dst": "grid",
                "dst_port": "left_top",
                "label": "Solar export 1.9 kW",
                "color": PALETTE["solar"],
                "width": 4.3,
                "rad": -0.2,
                "label_xy": (600, 436),
            },
        ],
        money_rows=[
            ("Import cost", "$0.00", "grid import 0.0 kW", "neutral"),
            ("Export revenue", "$0.23", "1.9 kW x $0.12", "good"),
            ("Battery value", "$0.30", "stored for peak", "good"),
            ("Net cashflow", "-$0.53", "revenue positive", "good"),
        ],
        out_name="mockup_flow_midday_solar.png",
    )

    draw_mockup(
        title="Evening Peak Discharge",
        subtitle="Battery discharges into home load while limiting expensive grid import",
        scenario_chip="Scenario B - Peak Support",
        flows=[
            {
                "src": "battery",
                "src_port": "right_mid",
                "dst": "home",
                "dst_port": "left_bot",
                "label": "Battery to home 3.0 kW",
                "color": PALETTE["battery"],
                "width": 6.0,
                "rad": 0.14,
                "label_xy": (410, 314),
            },
            {
                "src": "grid",
                "src_port": "left_mid",
                "dst": "home",
                "dst_port": "right_mid",
                "label": "Grid to home 0.4 kW",
                "color": PALETTE["grid"],
                "width": 3.2,
                "rad": 0.0,
                "label_xy": (770, 338),
            },
        ],
        money_rows=[
            ("Import cost", "$0.17", "0.4 kW x $0.42", "bad"),
            ("Avoided import", "$1.26", "3.0 kW displaced", "good"),
            ("Degradation", "$0.07", "throughput wear", "bad"),
            ("Net spend", "$0.24", "vs baseline $1.50", "good"),
        ],
        out_name="mockup_flow_evening_peak.png",
    )

    draw_mockup(
        title="Overnight Arbitrage Charge",
        subtitle="Grid charges battery in low-price windows for next-day peak discharge",
        scenario_chip="Scenario C - Off-Peak Charge",
        flows=[
            {
                "src": "grid",
                "src_port": "left_mid",
                "dst": "home",
                "dst_port": "right_mid",
                "label": "Grid to home 0.8 kW",
                "color": PALETTE["grid"],
                "width": 3.0,
                "rad": 0.0,
                "label_xy": (770, 338),
            },
            {
                "src": "grid",
                "src_port": "left_bot",
                "dst": "battery",
                "dst_port": "right_bot",
                "label": "Grid to battery 2.7 kW",
                "color": PALETTE["grid"],
                "width": 5.2,
                "rad": 0.22,
                "label_xy": (610, 266),
            },
        ],
        money_rows=[
            ("Import cost", "$0.21", "3.5 kW x $0.06", "bad"),
            ("Stored value", "$0.35", "future peak offset", "good"),
            ("Cycle cost", "$0.04", "degradation reserve", "bad"),
            ("Expected gain", "+$0.10", "after cycle cost", "good"),
        ],
        out_name="mockup_flow_overnight_charge.png",
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
