#!/bin/zsh
# Start the GND server and tray icon.
# Double-click this file (or run it in terminal) after each login.
set -e
cd "$(dirname "$0")"

export ANTHROPIC_BASE_URL="${ANTHROPIC_BASE_URL:-https://api.anthropic.com}"
export SEISMIC_CHAT_MODEL="${SEISMIC_CHAT_MODEL:-claude-sonnet-4-5}"

# Launch the tray app (it manages the server process internally).
exec /opt/homebrew/bin/python3 tray.py
