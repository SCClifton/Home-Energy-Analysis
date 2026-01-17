# Raspberry Pi deployment

This document describes how the Home Energy dashboard runs on the Raspberry Pi 5 as a small appliance:

- Boots unattended.
- Starts the dashboard on boot.
- Launches Chromium in kiosk mode on boot.
- Serves cached data when offline, and refreshes from Amber when available.

## Pi Quick Start

Find the Pi and SSH in (mDNS can be unreliable, so prefer IP):

```bash
sudo nmap -sn 192.168.4.0/22
# Look for "Raspberry Pi (Trading)" and note the IP.
ssh sam@192.168.5.210
```

Mac SSH alias (recommended for convenience):

```bash
Host home-energy-pi
  HostName 192.168.5.210
  User sam
  ServerAliveInterval 30
  ServerAliveCountMax 3
```

Then connect with:

```bash
ssh home-energy-pi
```

Note: `.local` hostname resolution can be unreliable, so prefer the IP or the SSH config alias.

## Make the IP stable

Set a DHCP reservation in your router for the Pi's MAC address. This keeps the IP stable so SSH access remains predictable and the alias above stays valid.

## Current known-good state

Verified working after reboot (2026-01-05):

- `home-energy-dashboard.service` is enabled and running (Flask app on port 5050).
- `home-energy-kiosk.service` is enabled and running (Chromium kiosk pointing to `http://127.0.0.1:5050/`).
- LightDM desktop auto-login is enabled for user `sam`.
- X11 is in use (LightDM launches `/usr/lib/xorg/Xorg :0`).
- Screen blanking is disabled via `raspi-config`.

## Repo layout on the Pi

- Repo location: `/home/sam/repos/Home-Energy-Analysis`
- Virtual environment: `/home/sam/repos/Home-Energy-Analysis/.venv`
- Dashboard entrypoint: `dashboard_app/app/main.py`
- Cache/data location (if configured): `/var/lib/home-energy-analysis`

## Where secrets live

Primary env file on the Pi (root-owned, not in git):

`/etc/home-energy-analysis/dashboard.env`

Used by these systemd services via `EnvironmentFile=`:

- `home-energy-dashboard.service`
- `home-energy-supabase-forward-sync.service`
- `home-energy-supabase-keepalive.service`

Keys:

- `AMBER_TOKEN`
- `AMBER_SITE_ID`
- `SUPABASE_DB_URL` (recommended so services can share it)
- `PORT` (5050)
- `RETENTION_DAYS`
- `SQLITE_PATH` (typically under `/var/lib/home-energy-analysis`) and other runtime flags used by the dashboard and cache logic

Example (no real secrets):

```bash
AMBER_TOKEN=...
AMBER_SITE_ID=...
SUPABASE_DB_URL=...
```

Optional local override (repo-local, not committed):

- `~/.env.local` can hold `SUPABASE_DB_URL` only if you do not put it in `dashboard.env` (chmod 600).

Notes:

- Do not commit secrets.
- Keep the env file owned by root.
- The systemd unit loads this file.

## Services

### 1) Dashboard service (system-level)

Unit: `home-energy-dashboard.service`

Purpose:

- Runs the Flask dashboard (UI and API) on port 5050.
- Restarts automatically on failure.
- Starts on boot.

Common commands:

```bash
sudo systemctl status home-energy-dashboard.service --no-pager -l
sudo systemctl restart home-energy-dashboard.service
journalctl -u home-energy-dashboard.service -n 100 --no-pager
```

Health checks:

```bash
curl -fsS http://127.0.0.1:5050/ | head
curl -fsS http://127.0.0.1:5050/api/health | python -m json.tool
```

Note on `/api/health`:

- `data_source` can be cache even when live price fetch is working (this depends on endpoint behaviour and caching rules).
- `status` may show stale if usage cache is old. This does not prevent the UI from loading.

### 2) Kiosk service (user-level)

This is what makes the Pi boot straight into the dashboard display.

Files:

- Script: `~/bin/home-energy-kiosk.sh`
- Systemd user unit: `~/.config/systemd/user/home-energy-kiosk.service`
- Optional log file: `~/logs/kiosk.log`

Purpose:

- Waits for `/api/health` to respond.
- Launches Chromium in kiosk mode to `http://127.0.0.1:5050/`.
- Prevents keyring prompts (important for kiosk).
- Disables extensions and background component extensions (stability).
- Forces X11 (`--ozone-platform=x11`) and software rendering flags (prevents white screen issues).

Enable and start:

```bash
systemctl --user daemon-reload
systemctl --user enable --now home-energy-kiosk.service
systemctl --user status home-energy-kiosk.service --no-pager -l
```

### 3) Supabase keepalive (system-level)

Optional daily ping to keep Supabase free-tier active.

Uses `EnvironmentFile=/etc/home-energy-analysis/dashboard.env`.

Schedule:

- Daily at 01:45
- `Persistent=true` (runs on boot if missed)

Install:

```bash
sudo cp ~/repos/Home-Energy-Analysis/pi/systemd/home-energy-supabase-keepalive.service /etc/systemd/system/
sudo cp ~/repos/Home-Energy-Analysis/pi/systemd/home-energy-supabase-keepalive.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now home-energy-supabase-keepalive.timer
```

Check logs:

```bash
sudo systemctl status home-energy-supabase-keepalive.service --no-pager -l
sudo systemctl status home-energy-supabase-keepalive.timer --no-pager -l
journalctl -u home-energy-supabase-keepalive.service -n 50 --no-pager
```

Run now:

```bash
sudo systemctl start home-energy-supabase-keepalive.service
```

### 4) Supabase forward sync (system-level)

Daily sync of recent Amber prices and usage into Supabase (idempotent).

Uses `EnvironmentFile=/etc/home-energy-analysis/dashboard.env`.

Schedule:

- Daily at 02:15
- `Persistent=true` (runs on boot if missed)

Install:

```bash
sudo cp ~/repos/Home-Energy-Analysis/pi/systemd/home-energy-supabase-forward-sync.service /etc/systemd/system/
sudo cp ~/repos/Home-Energy-Analysis/pi/systemd/home-energy-supabase-forward-sync.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now home-energy-supabase-forward-sync.timer
```

Check logs:

```bash
sudo systemctl status home-energy-supabase-forward-sync.service --no-pager -l
sudo systemctl status home-energy-supabase-forward-sync.timer --no-pager -l
journalctl -u home-energy-supabase-forward-sync.service -n 50 --no-pager
```

Run now:

```bash
sudo systemctl start home-energy-supabase-forward-sync.service
```

## Verify it's working

```bash
sudo systemctl status home-energy-dashboard.service --no-pager -l
curl -fsS http://127.0.0.1:5050/api/health | python -m json.tool
sudo systemctl list-timers --all | grep home-energy
journalctl -u home-energy-supabase-forward-sync.service -n 80 --no-pager
journalctl -u home-energy-supabase-keepalive.service -n 50 --no-pager
```

## Verify Chromium flags

Verify Chromium is running with the expected flags:

```bash
pgrep -a chromium | head -n 1
```

Expected flags include:

- `--password-store=basic`
- `--use-mock-keychain`
- `--disable-extensions`
- `--disable-component-extensions-with-background-pages`
- `--ozone-platform=x11`
- `--user-data-dir=/tmp/chromium-kiosk`

URL ends with `http://127.0.0.1:5050/`.

Notes:

- The user service includes `ExecStartPre` steps to kill any existing Chromium and clear `/tmp/chromium-kiosk`.
- `pkill` may exit with status 1 when there is no Chromium to kill, that is fine.

## Desktop and display configuration

The kiosk relies on a graphical session being available.

Current setup:

- Display manager: LightDM
- Auto-login enabled for user `sam`
- X11 in use (Xorg running on `:0`)
- Screen blanking disabled

Check LightDM and Xorg:

```bash
systemctl status lightdm --no-pager -l
```

`raspi-config` settings to confirm:

- System Options -> Boot -> Desktop
- System Options -> Auto Login -> Desktop Autologin
- Display Options -> Screen Blanking -> Disable
- Advanced Options -> X11 (or equivalent option on your image) enabled

## Update workflow

Preferred workflow:

- Develop on Mac.
- Commit and push to GitHub.
- Pull and restart services on the Pi.

On the Pi:

```bash
cd ~/repos/Home-Energy-Analysis
./pi/update.sh
```

After updating, verify:

```bash
sudo systemctl status home-energy-dashboard.service --no-pager -l
systemctl --user status home-energy-kiosk.service --no-pager -l
curl -fsS http://127.0.0.1:5050/api/health | python -m json.tool
```

## Troubleshooting

### Journal logs

- Old journal entries can show earlier failures; check recent entries with `--since "10 min ago"`.
- Check `ExecMainStatus` in `systemctl status` to confirm the most recent exit code.

### SSH or hostname issues

- `.local` hostname resolution can fail on macOS; use the IP from `nmap`.
- `ipconfig getifaddr en0` can occasionally return a broadcast address like `192.168.4.255`; use `nmap` or router leases instead.
- If the IP changed, rerun:

```bash
sudo nmap -sn 192.168.4.0/22
```

### Dashboard not loading

Check service:

```bash
sudo systemctl status home-energy-dashboard.service --no-pager -l
journalctl -u home-energy-dashboard.service -n 200 --no-pager
```

Check health endpoint:

```bash
curl -fsS http://127.0.0.1:5050/api/health | python -m json.tool
```

### Missing AMBER_TOKEN or SUPABASE_DB_URL

- Confirm `/etc/home-energy-analysis/dashboard.env` includes `AMBER_TOKEN` and `AMBER_SITE_ID`.
- If Supabase jobs fail, ensure `SUPABASE_DB_URL` is set in `dashboard.env` or `.env.local`.
- The forward-sync service reads `dashboard.env`, so missing keys will show up in its journal logs.

### Common failures

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `SUPABASE_DB_URL` missing | Not set in `dashboard.env` | Add it to `/etc/home-energy-analysis/dashboard.env` and retry the job. |
| `AMBER_TOKEN` missing | Not set in `dashboard.env` | Add it to `/etc/home-energy-analysis/dashboard.env` and restart the service. |
| Forward sync shows “0 usage rows” | Amber returned no usage for that window | Retry the next day; confirm `AMBER_SITE_ID` and channel type settings. |

### Kiosk shows a white screen or prompts for a keyring

This was fixed by running Chromium with:

- `--password-store=basic --use-mock-keychain`
- `--disable-extensions --disable-component-extensions-with-background-pages`
- `--ozone-platform=x11` and software rendering flags

Check running Chromium flags:

```bash
pgrep -a chromium | head -n 1
```

Restart kiosk:

```bash
systemctl --user restart home-energy-kiosk.service
tail -n 200 ~/logs/kiosk.log || true
```

### Kiosk does not start after reboot

Confirm LightDM auto-login is working:

```bash
systemctl status lightdm --no-pager -l
```

Confirm kiosk service is enabled:

```bash
systemctl --user is-enabled home-energy-kiosk.service
systemctl --user status home-energy-kiosk.service --no-pager -l
```

Manually restart:

```bash
systemctl --user restart home-energy-kiosk.service
```

## Recovery behaviour

If the Pi loses power:

- It reboots.
- LightDM auto-logs in `sam`.
- The dashboard service restarts automatically.
- Chromium kiosk restarts automatically and loads the dashboard.
