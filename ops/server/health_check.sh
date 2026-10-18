#!/usr/bin/env bash
# ==============================================================================
# ops/server/health_check.sh
# Comprehensive health and readiness check for Moltbook Alpha API.
# Evaluates service state, HTTP readiness, database integrity, disk headroom,
# and recent error rates. Returns 0 on healthy, non-zero on degraded/failed.
# ==============================================================================
set -euo pipefail

PORT="${MOLTBOOK_PORT:-8080}"
HOST="${MOLTBOOK_HOST:-127.0.0.1}"
SERVICE_NAME="moltbook-alpha"
DATA_DIR="/var/lib/moltbook-alpha"
DB_FILE="${DATA_DIR}/moltbook.db"

HEALTH_URL="http://${HOST}:${PORT}/v1/health"
METRICS_URL="http://${HOST}:${PORT}/metrics"

EXIT_CODE=0

echo "=== Moltbook Alpha Health Check [$(date -u +%Y-%m-%dT%H:%M:%SZ)] ==="

# 1. Systemd Service State
if command -v systemctl >/dev/null 2>&1; then
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        echo "[PASS] Systemd service '${SERVICE_NAME}' is active and running."
    else
        echo "[FAIL] Systemd service '${SERVICE_NAME}' is NOT active (status: $(systemctl is-active "$SERVICE_NAME" 2>/dev/null || echo "unknown"))."
        EXIT_CODE=1
    fi
fi

# 2. HTTP /v1/health Probe
if command -v curl >/dev/null 2>&1; then
    HTTP_RESPONSE=$(curl -s -w "\n%{http_code}" --max-time 5 "$HEALTH_URL" || true)
    HTTP_BODY=$(echo "$HTTP_RESPONSE" | sed '$d')
    HTTP_STATUS=$(echo "$HTTP_RESPONSE" | tail -n 1)

    if [ "$HTTP_STATUS" = "200" ]; then
        if echo "$HTTP_BODY" | grep -q '"status"[[:space:]]*:[[:space:]]*"ok"'; then
            echo "[PASS] HTTP GET ${HEALTH_URL} returned 200 OK with status: ok"
        else
            echo "[WARN] HTTP GET ${HEALTH_URL} returned 200 but payload missing status: ok"
            EXIT_CODE=1
        fi
    else
        echo "[FAIL] HTTP GET ${HEALTH_URL} probe failed (HTTP Status: ${HTTP_STATUS:-unreachable})"
        EXIT_CODE=1
    fi

    # Probe /metrics
    METRICS_STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$METRICS_URL" || true)
    if [ "$METRICS_STATUS" = "200" ]; then
        echo "[PASS] HTTP GET ${METRICS_URL} returned 200 OK"
    else
        echo "[WARN] HTTP GET ${METRICS_URL} returned status: ${METRICS_STATUS:-unreachable}"
    fi
else
    echo "[WARN] curl not installed. Skipping HTTP probe."
fi

# 3. Database File & Integrity Check
if [ -f "$DB_FILE" ]; then
    if command -v sqlite3 >/dev/null 2>&1; then
        INTEGRITY_CHECK=$(sqlite3 "$DB_FILE" "PRAGMA integrity_check;" 2>&1 || true)
        if [ "$INTEGRITY_CHECK" = "ok" ]; then
            echo "[PASS] SQLite integrity check passed for ${DB_FILE}."
        else
            echo "[FAIL] SQLite integrity check failed: ${INTEGRITY_CHECK}"
            EXIT_CODE=1
        fi
    elif command -v python3 >/dev/null 2>&1; then
        INTEGRITY_CHECK=$(python3 -c "
import sqlite3
con = sqlite3.connect('$DB_FILE')
res = con.execute('PRAGMA integrity_check;').fetchone()[0]
print(res)
con.close()
" 2>&1 || true)
        if [ "$INTEGRITY_CHECK" = "ok" ]; then
            echo "[PASS] SQLite integrity check passed for ${DB_FILE} (via python3)."
        else
            echo "[FAIL] SQLite integrity check failed: ${INTEGRITY_CHECK}"
            EXIT_CODE=1
        fi
    fi
else
    echo "[INFO] SQLite database ${DB_FILE} does not exist yet (normal prior to first transaction)."
fi

# 4. Storage / Disk Space Headroom
ROOT_AVAIL_KB=$(df -k / | awk 'NR==2 {print $4}')
# Require at least 500MB (512000 KB) free
if [ "$ROOT_AVAIL_KB" -lt 512000 ]; then
    echo "[FAIL] Low disk space on /: only ${ROOT_AVAIL_KB} KB available."
    EXIT_CODE=1
else
    echo "[PASS] Sufficient disk space on /: $(( ROOT_AVAIL_KB / 1024 )) MB available."
fi

# 5. Recent Critical Log Errors
if command -v journalctl >/dev/null 2>&1 && [ "$EUID" -eq 0 ]; then
    RECENT_ERRORS=$(journalctl -u "$SERVICE_NAME" -p err --since "5 minutes ago" --no-pager 2>/dev/null | grep -v "\-\- Logs begin" | wc -l || true)
    if [ "$RECENT_ERRORS" -gt 0 ]; then
        echo "[WARN] Detected ${RECENT_ERRORS} error-level log entries in journald in last 5 minutes."
    else
        echo "[PASS] Zero error-level journald log entries in last 5 minutes."
    fi
fi

if [ "$EXIT_CODE" -eq 0 ]; then
    echo "[RESULT] Health check status: ALL SYSTEMS HEALTHY (0)"
else
    echo "[RESULT] Health check status: DEGRADED OR UNHEALTHY (${EXIT_CODE})"
fi

exit "$EXIT_CODE"
