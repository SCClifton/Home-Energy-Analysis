#!/usr/bin/env python3
"""Convenience wrapper for 5-minute live simulation runs."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[1]
    cmd = [
        sys.executable,
        str(project_root / "scripts" / "run_scenario_simulation.py"),
        "--mode",
        "live",
        "--controller",
        os.getenv("SIM_CONTROLLER", "optimizer"),
        "--history-hours",
        os.getenv("SIM_HISTORY_HOURS", "48"),
        "--forecast-hours",
        os.getenv("SIM_FORECAST_HOURS", "24"),
    ]

    if os.getenv("SIM_REFRESH_WEATHER", "1") == "1":
        cmd.append("--refresh-weather")

    raise SystemExit(subprocess.call(cmd, cwd=project_root))
