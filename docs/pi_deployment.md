# Raspberry Pi Deployment – Home Energy Analysis

This document describes how the Home Energy Analysis dashboard is deployed and operated on a Raspberry Pi 5.

The Pi runs as a small, self-healing appliance:
- boots unattended
- refreshes Amber data on a schedule
- serves cached data offline
- optionally runs in fullscreen kiosk mode for a kitchen display

---

## Overview

The Raspberry Pi runs two core components:

1. Dashboard service
   - Flask-based web app
   - Serves UI and API endpoints on port 5050
   - Starts automatically on boot via systemd

2. Cache refresh job
   - Periodically fetches Amber prices and usage
   - Writes to a local SQLite cache
   - Runs every 5 minutes via systemd timer

The dashboard is designed to be offline-first. If the internet is unavailable, cached data is served.

---

## System layout

Repository location on Pi:
    /home/sam/repos/Home-Energy-Analysis

Python virtual environment:
    /home/sam/repos/Home-Energy-Analysis/.venv

Project installed in editable mode:
    pip install -e .

SQLite cache location:
    /var/lib/home-energy-analysis/cache.sqlite

Environment file (not committed to Git):
    /etc/home-energy-analysis/dashboard.env

Environment variables:
- AMBER_TOKEN
- AMBER_SITE_ID
- PORT
- SQLITE_PATH
- RETENTION_DAYS
- DEBUG

Permissions:
- owned by root
- readable by group homeenergy
- dashboard runs as user sam (member of homeenergy)

---

## Services

Dashboard service
Unit name:
    home-energy-dashboard.service

Purpose:
- runs the Flask dashboard
- restarts automatically on failure
- starts on boot

Common commands:
    systemctl status home-energy-dashboard.service
    sudo systemctl restart home-energy-dashboard.service
    journalctl -u home-energy-dashboard.service -n 50 --no-pager

---

Cache refresh service
Unit name:
    home-energy-sync-cache.service

Purpose:
- one-shot job to refresh SQLite cache from Amber

Manual run:
    sudo systemctl start home-energy-sync-cache.service
    journalctl -u home-energy-sync-cache.service -n 50 --no-pager

---

Cache refresh timer
Unit name:
    home-energy-sync-cache.timer

Schedule:
- runs every 5 minutes
- includes small randomised delay

Status:
    systemctl status home-energy-sync-cache.timer
    systemctl list-timers --all | grep home-energy

---

## Health checks

Dashboard:
    http://localhost:5050/

Health endpoint:
    http://localhost:5050/api/health

Returns JSON including:
- data source (live or cache)
- cache age
- status (ok, stale, or unknown)

---

## Update workflow

All development happens on a Mac and is pushed to GitHub.

To update the Pi:
    ssh sam@<pi-ip>
    cd ~/repos/Home-Energy-Analysis
    ./pi/update.sh

The update script:
- verifies clean main branch
- pulls latest commits
- reinstalls Python dependencies
- restarts services
- triggers an immediate cache refresh
- prints service status and health output

---

## Kiosk mode (optional)

Kiosk launch script:
    /home/sam/bin/home-energy-kiosk.sh

Autostart entry:
    ~/.config/autostart/home-energy-kiosk.desktop

Behaviour:
- waits for /api/health
- launches Chromium fullscreen
- disables screen blanking
- hides mouse cursor

---

## SSH access

From another machine on the same network:
    ssh sam@<pi-ip>

The Pi is fully operable over SSH without keyboard, mouse, or monitor.

---

## Notes and cautions

- do not commit secrets (dashboard.env is outside the repo)
- avoid editing code directly on the Pi
- preferred workflow:
  - edit on Mac
  - commit and push
  - pull via ./pi/update.sh
- Flask dev server is acceptable for this appliance

---

## Recovery

If the Pi loses power:
- it will reboot
- services restart automatically
- cached data remains available
- dashboard recovers without intervention