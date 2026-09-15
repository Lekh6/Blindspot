#!/bin/bash
# BlindSpot — simple startup for Linux / macOS / Git Bash
# First time setup: see README "First Time Setup"
# Everyday use: bash run.sh  or  ./run.sh
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/.venv/bin/python" ]; then
  exec "$SCRIPT_DIR/.venv/bin/python" "$SCRIPT_DIR/run.py" "$@"
else
  exec python3 "$SCRIPT_DIR/run.py" "$@"
fi
