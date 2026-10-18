#!/usr/bin/env bash
# ==============================================================================
# ops/server/rollback.sh
# Safely rolls back to a previously deployed release without deleting
# persistent application state or databases.
# ==============================================================================
set -euo pipefail

APP_ROOT="/opt/moltbook-alpha"
RELEASES_DIR="${APP_ROOT}/releases"
CURRENT_LINK="${APP_ROOT}/current"
SERVICE_NAME="moltbook-alpha"
TARGET_RELEASE="${1:-}"

echo "=== Moltbook Alpha Rollback Workflow ==="

if [ ! -L "$CURRENT_LINK" ]; then
    echo "[ERROR] Current link ${CURRENT_LINK} does not exist or is not a symlink." >&2
    exit 1
fi

ACTIVE_RELEASE=$(readlink -f "$CURRENT_LINK")
echo "Currently active release: ${ACTIVE_RELEASE}"

if [ -z "$TARGET_RELEASE" ]; then
    # Find previous release (excluding currently active release)
    TARGET_RELEASE=$(find "$RELEASES_DIR" -mindepth 1 -maxdepth 1 -type d | grep -v "^${ACTIVE_RELEASE}$" | sort -r | head -n 1 || true)
fi

if [ -z "$TARGET_RELEASE" ] || [ ! -d "$TARGET_RELEASE" ]; then
    echo "[ERROR] No alternative release found in ${RELEASES_DIR} to roll back to." >&2
    exit 1
fi

echo "[ROLLBACK] Selected target release: ${TARGET_RELEASE}"

# Atomic symlink update
echo "[ROLLBACK] Atomically switching current symlink..."
ln -sfn "$TARGET_RELEASE" "${CURRENT_LINK}.tmp"
mv -Tf "${CURRENT_LINK}.tmp" "$CURRENT_LINK"

# Restart systemd service
if command -v systemctl >/dev/null 2>&1; then
    echo "[SYSTEMD] Restarting ${SERVICE_NAME}..."
    systemctl restart "$SERVICE_NAME"
    sleep 2
fi

# Run health check
if [ -f "${CURRENT_LINK}/ops/server/health_check.sh" ]; then
    echo "[VERIFY] Running post-rollback health verification..."
    "${CURRENT_LINK}/ops/server/health_check.sh"
fi

echo "=== Rollback successfully completed to: ${TARGET_RELEASE} ==="
