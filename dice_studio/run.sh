#!/usr/bin/env sh
# Tides Dice Studio launcher for macOS / Linux.
set -e
cd "$(dirname "$0")"
if [ ! -f .venv/installed.ok ]; then
  python3 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements-dev.txt
  touch .venv/installed.ok
fi
exec .venv/bin/python -m dicestudio "$@"
