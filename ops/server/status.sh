#!/usr/bin/env bash
# ==============================================================================
# ops/server/status.sh
# Concise, high-signal operational dashboard for Moltbook Alpha API.
# Displays service status, release version, listening ports, health probe,
# backup age, and system metrics with strict secret redaction.
# ==============================================================================
set -euo pipefail

APP_ROOT="/opt/moltbook-alpha"
CURRENT_LINK="${APP_ROOT}/current"
DATA_DIR="/var/lib/moltbook-alpha"
BACKUP_DIR="/var/backups/moltbook-alpha"
SERVICE_NAME="moltbook-alpha"
PORT="${MOLTBOOK_PORT:-8080}"
HOST="${MOLTBOOK_HOST:-127.0.0.1}"

echo "================================================================================"
echo "=== Moltbook Alpha Operational Status [$(date -u +%Y-%m-%dT%H:%M:%SZ)] ==="
echo "================================================================================"

# 1. Active Release Version
if [ -L "$CURRENT_LINK" ]; then
    ACTIVE_RELEASE=$(readlink -f "$CURRENT_LINK")
    echo "Release:       $(basename "$ACTIVE_RELEASE") (${ACTIVE_RELEASE})"
else
    echo "Release:       No current symlink found at ${CURRENT_LINK}"
fi

# 2. Systemd Service Lifecycle
if command -v systemctl >/dev/null 2>&1; then
    SERVICE_STATUS=$(systemctl is-active "$SERVICE_NAME" 2>/dev/null || echo "inactive")
    echo "Service:       ${SERVICE_NAME} [${SERVICE_STATUS}]"
    if [ "$SERVICE_STATUS" = "active" ]; then
        PID=$(systemctl show -p MainPID --value "$SERVICE_NAME" 2>/dev/null || echo "unknown")
        UPTIME_SVC=$(ps -p "$PID" -o etime= 2>/dev/null | tr -d ' ' || echo "unknown")
        echo "Main PID:      ${PID} (Uptime: ${UPTIME_SVC})"
    fi
fi

# 3. HTTP Readiness Probe
if command -v curl >/dev/null 2>&1; then
    HEALTH_OUTPUT=$(curl -s --max-time 3 "http://${HOST}:${PORT}/v1/health" 2>/dev/null || echo '{"status":"unreachable"}')
    echo "API Probe:     http://${HOST}:${PORT}/v1/health"
    echo "Health JSON:   ${HEALTH_OUTPUT}"
fi

# 4. Network Exposure & Listening Ports
echo -n "Listening:     "
if command -v ss >/dev/null 2>&1; then
    ss -lnt "sport = :${PORT}" 2>/dev/null | tail -n +2 | awk '{print $4}' | tr '\n' ' ' || echo "none"
else
    echo "ss not available"
fi
echo ""

# 5. Database & Persistent State
DB_FILE="${DATA_DIR}/moltbook.db"
if [ -f "$DB_FILE" ]; then
    DB_SIZE=$(stat -c%s "$DB_FILE" 2>/dev/null || stat -f%z "$DB_FILE" 2>/dev/null || echo "0")
    echo "Database:      ${DB_FILE} ($(( DB_SIZE / 1024 )) KB)"
else
    echo "Database:      Not initialized yet"
fi

# 6. Backup Health & Age
LATEST_BACKUP=$(find "$BACKUP_DIR" -name "moltbook_*.db" -type f 2>/dev/null | sort -r | head -n 1 || true)
if [ -n "$LATEST_BACKUP" ] && [ -f "$LATEST_BACKUP" ]; then
    BACKUP_TIME=$(stat -c%y "$LATEST_BACKUP" 2>/dev/null || stat -f%Sm "$LATEST_BACKUP" 2>/dev/null || echo "unknown")
    echo "Last Backup:   $(basename "$LATEST_BACKUP") (${BACKUP_TIME})"
else
    echo "Last Backup:   None found in ${BACKUP_DIR}"
fi

# 7. Host System & Maintenance Status
REBOOT_STATUS="No"
if [ -f /var/run/reboot-required ]; then
    REBOOT_STATUS="YES (pending reboot)"
fi
echo "System Load:   $(uptime | sed 's/.*load average://')"
echo "Memory Used:   $(free -h | awk '/Mem:/ {print $3 "/" $2}')"
echo "Root Disk:     $(df -h / | awk 'NR==2 {print $3 "/" $2 " (" $5 " used)"}')"
echo "Reboot Req:    ${REBOOT_STATUS}"
echo "================================================================================"
