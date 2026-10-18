#!/usr/bin/env bash
set -euo pipefail

CURRENT_DIR="/opt/moltbook-alpha/current"
VENV_PYTHON="$CURRENT_DIR/venv/bin/python"

if [[ ! -x "$VENV_PYTHON" ]]; then
    VENV_PYTHON="$CURRENT_DIR/.venv/bin/python"
fi
if [[ ! -x "$VENV_PYTHON" ]]; then
    VENV_PYTHON="python3"
fi

echo "[$(date -u)] Starting Moltbook Alpha Community Publisher & Daily Report..."
"$VENV_PYTHON" "$CURRENT_DIR/ops/publisher.py" --force-refresh "$@"
echo "[$(date -u)] Daily report and community briefing publication completed successfully."
