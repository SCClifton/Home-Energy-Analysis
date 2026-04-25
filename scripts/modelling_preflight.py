#!/usr/bin/env python3
"""Read-only preflight checks for annual purchase-decision modelling."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_annual_analysis import main


if __name__ == "__main__":
    sys.argv.append("--preflight-only")
    raise SystemExit(main())
