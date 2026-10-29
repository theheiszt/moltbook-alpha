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

echo "[$(date -u)] Starting Hourly Moltbook Intelligence Ingestion & Signal Extraction..."
"$VENV_PYTHON" "$CURRENT_DIR/intel_collector.py"
echo "[$(date -u)] Hourly collection cycle completed successfully."
