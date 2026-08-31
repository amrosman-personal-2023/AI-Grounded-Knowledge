#!/bin/zsh
# Install GND as an always-on launchd LaunchAgent (starts at login, auto-restarts).
set -e
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
LABEL="com.gnd.app"
AGENTS="$HOME/Library/LaunchAgents"
PLIST="$AGENTS/$LABEL.plist"

mkdir -p "$AGENTS"
sed "s|__APP_DIR__|$APP_DIR|g" "$APP_DIR/com.gnd.app.plist" > "$PLIST"
chmod +x "$APP_DIR/run.sh"

# Reload cleanly if already installed.
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl enable "gui/$(id -u)/$LABEL"
launchctl kickstart -k "gui/$(id -u)/$LABEL"

echo "Installed and started: http://localhost:8787"
echo "Logs:   $APP_DIR/server.log"
echo "Stop:   launchctl bootout gui/$(id -u)/$LABEL"
echo "Start:  launchctl bootstrap gui/$(id -u) $PLIST"
