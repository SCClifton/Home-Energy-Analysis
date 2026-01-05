Raspberry Pi deployment

This document describes how the Home Energy dashboard runs on the Raspberry Pi 5 as a small “appliance”:

boots unattended

starts the dashboard on boot

launches Chromium in kiosk mode on boot

serves cached data when offline, and refreshes from Amber when available

Current known-good state

Verified working after reboot (2026-01-05):

home-energy-dashboard.service is enabled and running (Flask app on port 5050)

home-energy-kiosk.service is enabled and running (Chromium kiosk pointing to http://127.0.0.1:5050/)

LightDM desktop auto-login is enabled for user sam

X11 is in use (LightDM launches /usr/lib/xorg/Xorg :0)

Screen blanking is disabled via raspi-config

Repo layout on the Pi

Repo location:

/home/sam/repos/Home-Energy-Analysis

Virtual environment:

/home/sam/repos/Home-Energy-Analysis/.venv

Dashboard entrypoint:

dashboard_app/app/main.py

Secrets and environment configuration

Env file on the Pi (not committed to git):

/etc/home-energy-analysis/dashboard.env

This typically includes:

AMBER_TOKEN

AMBER_SITE_ID

PORT (default 5050)

SQLITE_PATH

RETENTION_DAYS

other runtime flags used by the dashboard and cache logic

Notes:

Do not commit secrets.

Keep the env file owned by root.

The systemd unit loads this file.

Services
1) Dashboard service (system-level)

Unit:

home-energy-dashboard.service

Purpose:

Runs the Flask dashboard (UI and API) on port 5050

Restarts automatically on failure

Starts on boot

Common commands:

sudo systemctl status home-energy-dashboard.service --no-pager -l
sudo systemctl restart home-energy-dashboard.service
journalctl -u home-energy-dashboard.service -n 100 --no-pager

Health checks:

curl -fsS http://127.0.0.1:5050/ | head
curl -fsS http://127.0.0.1:5050/api/health | python -m json.tool

Note on /api/health:

data_source can be cache even when live price fetch is working (this depends on endpoint behaviour and caching rules).

status may show stale if usage cache is old. This does not prevent the UI from loading.

2) Kiosk service (user-level)

This is what makes the Pi boot straight into the dashboard display.

Files:

Script: ~/bin/home-energy-kiosk.sh

systemd user unit: ~/.config/systemd/user/home-energy-kiosk.service

Optional log file: ~/logs/kiosk.log

Purpose:

Waits for /api/health to respond

Launches Chromium in kiosk mode to http://127.0.0.1:5050/

Prevents keyring prompts (important for kiosk)

Disables extensions and background component extensions (stability)

Forces X11 (--ozone-platform=x11) and software rendering flags (prevents white screen issues)

Enable and start:

systemctl --user daemon-reload
systemctl --user enable --now home-energy-kiosk.service
systemctl --user status home-energy-kiosk.service --no-pager -l

Verify Chromium is running with the expected flags:

pgrep -a chromium | head -n 1

Expected flags include:

--password-store=basic

--use-mock-keychain

--disable-extensions

--disable-component-extensions-with-background-pages

--ozone-platform=x11

--user-data-dir=/tmp/chromium-kiosk

URL ends with http://127.0.0.1:5050/

Notes:

The user service includes ExecStartPre steps to kill any existing Chromium and clear /tmp/chromium-kiosk.

pkill may exit with status 1 when there is no Chromium to kill, that is fine.

Desktop and display configuration

The kiosk relies on a graphical session being available.

Current setup:

Display manager: LightDM

Auto-login enabled for user sam

X11 in use (Xorg running on :0)

Screen blanking disabled

Check LightDM and Xorg:

systemctl status lightdm --no-pager -l

raspi-config settings to confirm:

System Options → Boot → Desktop

System Options → Auto Login → Desktop Autologin

Display Options → Screen Blanking → Disable

Advanced Options → X11 (or equivalent option on your image) enabled

Update workflow

Preferred workflow:

develop on Mac

commit and push to GitHub

pull and restart services on the Pi

On the Pi:

cd ~/repos/Home-Energy-Analysis
./pi/update.sh

After updating, verify:

sudo systemctl status home-energy-dashboard.service --no-pager -l
systemctl --user status home-energy-kiosk.service --no-pager -l
curl -fsS http://127.0.0.1:5050/api/health | python -m json.tool
Troubleshooting
Dashboard not loading

Check service:

sudo systemctl status home-energy-dashboard.service --no-pager -l
journalctl -u home-energy-dashboard.service -n 200 --no-pager

Check health endpoint:

curl -fsS http://127.0.0.1:5050/api/health | python -m json.tool
Kiosk shows a white screen or prompts for a keyring

This was fixed by running Chromium with:

--password-store=basic --use-mock-keychain

--disable-extensions --disable-component-extensions-with-background-pages

--ozone-platform=x11 and software rendering flags

Check running Chromium flags:

pgrep -a chromium | head -n 1

Restart kiosk:

systemctl --user restart home-energy-kiosk.service
tail -n 200 ~/logs/kiosk.log || true
Kiosk does not start after reboot

Confirm LightDM auto-login is working:

systemctl status lightdm --no-pager -l

Confirm kiosk service is enabled:

systemctl --user is-enabled home-energy-kiosk.service
systemctl --user status home-energy-kiosk.service --no-pager -l

Manually restart:

systemctl --user restart home-energy-kiosk.service
Recovery behaviour

If the Pi loses power:

it reboots

LightDM auto-logs in sam

the dashboard service restarts automatically

Chromium kiosk restarts automatically and loads the dashboard