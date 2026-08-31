#!/usr/bin/env bash
# agnes-simple-ui launcher.
#
# Starts the Agnes backend (agnes-video-generator) if it isn't already
# running, sets up this project's own virtualenv on first run, starts this
# project's local server, and opens the UI in the browser. One command.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGNES_DIR="${AGNES_DIR:-$SCRIPT_DIR/../agnes-video-generator}"
AGNES_PORT="${AGNES_PORT:-8765}"
UI_PORT="${SIMPLE_UI_PORT:-8787}"

msg() { echo "▶ $1"; }

# 1. Start the Agnes backend if it isn't already up.
if curl -s -o /dev/null "http://localhost:$AGNES_PORT/api/config"; then
  msg "Agnes backend already running on :$AGNES_PORT"
else
  if [ ! -x "$AGNES_DIR/.venv/bin/python" ]; then
    echo "❌ Could not find $AGNES_DIR/.venv/bin/python"
    echo "   Set AGNES_DIR to the agnes-video-generator folder, and make sure"
    echo "   it has been run at least once (its own start.sh sets up the venv)."
    exit 1
  fi
  msg "Starting Agnes backend..."
  (cd "$AGNES_DIR" && nohup ./.venv/bin/python server.py > /tmp/agnes-backend.log 2>&1 &)

  msg "Waiting for it to become ready..."
  ready=false
  for _ in $(seq 1 30); do
    if curl -s -o /dev/null "http://localhost:$AGNES_PORT/api/config"; then
      ready=true
      break
    fi
    sleep 1
  done
  if [ "$ready" != "true" ]; then
    echo "❌ Agnes backend did not start in time. Check /tmp/agnes-backend.log"
    exit 1
  fi
  msg "Agnes backend ready on :$AGNES_PORT"
fi

# 2. Set up this project's own venv on first run.
cd "$SCRIPT_DIR"
if [ ! -x ".venv/bin/python" ]; then
  msg "First run: setting up this project's virtualenv..."
  python3 -m venv .venv
  ./.venv/bin/pip install -q --upgrade pip
  ./.venv/bin/pip install -q -r requirements.txt
fi

# 3. Start this project's own server.
if curl -s -o /dev/null "http://localhost:$UI_PORT/"; then
  msg "Simple UI already running on :$UI_PORT"
else
  msg "Starting Simple UI on :$UI_PORT..."
  nohup ./.venv/bin/python server.py > /tmp/simple-ui.log 2>&1 &
  for _ in $(seq 1 15); do
    if curl -s -o /dev/null "http://localhost:$UI_PORT/"; then
      break
    fi
    sleep 1
  done
fi

# 4. Open the browser.
open "http://localhost:$UI_PORT" 2>/dev/null || true

msg "Ready → http://localhost:$UI_PORT"
