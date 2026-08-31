#!/bin/zsh
# Launcher for the always-on GND server. launchd execs this.
set -e
cd "$(dirname "$0")"

export ANTHROPIC_BASE_URL="${ANTHROPIC_BASE_URL:-https://api.anthropic.com}"
export SEISMIC_CHAT_MODEL="${SEISMIC_CHAT_MODEL:-claude-sonnet-4-5}"

exec /opt/homebrew/bin/python3 -m uvicorn app:app --host 127.0.0.1 --port 8787 --log-level info
