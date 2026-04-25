#!/usr/bin/env bash
set -euo pipefail

# Home Energy Analysis Raspberry Pi update helper
# Usage on Pi: run from anywhere inside the repo:
#   ./pi/update.sh

echo "=== Home Energy Analysis - Raspberry Pi update helper ==="

# Confirm we're in a git repo and jump to repo root
if ! repo_root="$(git rev-parse --show-toplevel 2>/dev/null)"; then
  echo "ERROR: Not inside a git repository. Please run this from within the Home-Energy-Analysis repo." >&2
  exit 1
fi
cd "$repo_root"
echo "Repo root: $repo_root"

current_branch="$(git rev-parse --abbrev-ref HEAD)"
current_commit="$(git rev-parse --short HEAD)"

echo "Current branch: $current_branch"
echo "Current commit:  $current_commit"

if [[ "$current_branch" != "main" ]]; then
  echo "ERROR: This script must be run on the 'main' branch. Current branch is '$current_branch'." >&2
  exit 1
fi

# Refuse to pull if there are local changes
if [[ -n "$(git status --porcelain)" ]]; then
  echo "ERROR: Working tree is not clean. Commit/stash local changes before updating." >&2
  git status --porcelain
  exit 1
fi

echo "=== Fetching latest changes from remote ==="
git fetch --all --prune

echo "=== Pulling latest commits (fast-forward only) ==="
git pull --ff-only

updated_commit="$(git rev-parse --short HEAD)"
echo "Updated commit:  $updated_commit"

venv_python="$repo_root/.venv/bin/python"
venv_pip="$repo_root/.venv/bin/pip"

if [[ ! -x "$venv_python" ]]; then
  echo "ERROR: Python virtual environment not found at '$venv_python'." >&2
  echo "Create it first: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && pip install -e ." >&2
  exit 1
fi

echo "=== Upgrading pip ==="
"$venv_python" -m pip install --upgrade pip

echo "=== Installing Python dependencies from requirements.txt ==="
"$venv_pip" install -r requirements.txt

echo "=== Installing project in editable mode ==="
"$venv_pip" install -e .

echo "=== Restarting services (requires sudo) ==="
if [[ -f "$repo_root/pi/systemd/home-energy-supabase-forward-sync.service" ]]; then
  sudo cp "$repo_root/pi/systemd/home-energy-supabase-forward-sync.service" /etc/systemd/system/
  sudo cp "$repo_root/pi/systemd/home-energy-supabase-forward-sync.timer" /etc/systemd/system/
  sudo systemctl daemon-reload
  sudo systemctl enable --now home-energy-supabase-forward-sync.timer
fi
if [[ -f "$repo_root/pi/systemd/home-energy-supabase-keepalive.service" ]]; then
  sudo cp "$repo_root/pi/systemd/home-energy-supabase-keepalive.service" /etc/systemd/system/
  sudo cp "$repo_root/pi/systemd/home-energy-supabase-keepalive.timer" /etc/systemd/system/
  sudo systemctl daemon-reload
  sudo systemctl enable --now home-energy-supabase-keepalive.timer
fi
if [[ -f "$repo_root/pi/systemd/home-energy-simulation.service" ]]; then
  sudo cp "$repo_root/pi/systemd/home-energy-simulation.service" /etc/systemd/system/
  sudo cp "$repo_root/pi/systemd/home-energy-simulation.timer" /etc/systemd/system/
  sudo systemctl daemon-reload
  sudo systemctl enable --now home-energy-simulation.timer
fi
if [[ -f "$repo_root/pi/systemd/home-energy-annual-analysis.service" ]]; then
  sudo cp "$repo_root/pi/systemd/home-energy-annual-analysis.service" /etc/systemd/system/
  sudo cp "$repo_root/pi/systemd/home-energy-annual-analysis.timer" /etc/systemd/system/
  sudo systemctl daemon-reload
  sudo systemctl enable --now home-energy-annual-analysis.timer
fi
if [[ -f "$repo_root/pi/systemd/home-energy-powerpal-refresh.service" ]]; then
  sudo cp "$repo_root/pi/systemd/home-energy-powerpal-refresh.service" /etc/systemd/system/
  sudo cp "$repo_root/pi/systemd/home-energy-powerpal-refresh.timer" /etc/systemd/system/
  sudo systemctl daemon-reload
  sudo systemctl enable --now home-energy-powerpal-refresh.timer
fi
sudo systemctl restart home-energy-dashboard.service
sudo systemctl restart home-energy-sync-cache.timer

echo "=== Triggering immediate cache refresh ==="
sudo systemctl start home-energy-sync-cache.service
if systemctl list-unit-files home-energy-annual-analysis.service --no-legend | grep -q home-energy-annual-analysis.service; then
  echo "=== Triggering annual analysis refresh ==="
  sudo systemctl start home-energy-annual-analysis.service || true
fi
if systemctl list-unit-files home-energy-powerpal-refresh.service --no-legend | grep -q home-energy-powerpal-refresh.service; then
  echo "=== Triggering Powerpal refresh if configured ==="
  sudo systemctl start home-energy-powerpal-refresh.service || true
fi

echo "=== Service status ==="
echo -n "home-energy-dashboard.service: "
systemctl is-active home-energy-dashboard.service || true
echo -n "home-energy-sync-cache.timer: "
systemctl is-active home-energy-sync-cache.timer || true
echo -n "home-energy-supabase-forward-sync.timer: "
systemctl is-active home-energy-supabase-forward-sync.timer || true
echo -n "home-energy-supabase-keepalive.timer: "
systemctl is-active home-energy-supabase-keepalive.timer || true
echo -n "home-energy-simulation.timer: "
systemctl is-active home-energy-simulation.timer || true
echo -n "home-energy-annual-analysis.timer: "
systemctl is-active home-energy-annual-analysis.timer || true
echo -n "home-energy-powerpal-refresh.timer: "
systemctl is-active home-energy-powerpal-refresh.timer || true

echo "=== Health check ==="
curl -fsS http://localhost:5050/api/health || true

echo "=== Done ==="
