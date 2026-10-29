#!/bin/bash
# BlindSpot — one-click UI launcher (Linux / macOS / Git Bash)
# First time setup: see README "First Time Setup"
# Everyday use: bash start_ui.sh  or  ./start_ui.sh
# Ctrl+C stops the services; press q/cd as you would in any shell.
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/.venv/bin/python" ]; then
  exec "$SCRIPT_DIR/.venv/bin/python" "$SCRIPT_DIR/start_ui.py" "$@"
else
  exec python3 "$SCRIPT_DIR/start_ui.py" "$@"
fi
