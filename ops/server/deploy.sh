#!/usr/bin/env bash
# ==============================================================================
# ops/server/deploy.sh
# Verified release deployment script for Moltbook Alpha API on Ubuntu.
# Sets up versioned release in /opt/moltbook-alpha/releases/<release-id>,
# installs pinned dependencies in an isolated venv, updates the current symlink,
# manages systemd reload/restart, and triggers automatic rollback on health failure.
# ==============================================================================
set -euo pipefail

APP_ROOT="/opt/moltbook-alpha"
RELEASES_DIR="${APP_ROOT}/releases"
CURRENT_LINK="${APP_ROOT}/current"
DATA_DIR="/var/lib/moltbook-alpha"
LOG_DIR="/var/log/moltbook-alpha"
CONFIG_FILE="/etc/moltbook-alpha/api.env"
SERVICE_NAME="moltbook-alpha"
SERVICE_USER="moltbook-api"
SERVICE_GROUP="moltbook-api"

SRC_TAR=""
COMMIT_SHA=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --tar)
            SRC_TAR="$2"
            shift 2
            ;;
        --commit)
            COMMIT_SHA="$2"
            shift 2
            ;;
        *)
            echo "Usage: $0 --tar <archive.tar.gz> [--commit <sha>]" >&2
            exit 1
            ;;
    esac
done

if [ -z "$SRC_TAR" ] || [ ! -f "$SRC_TAR" ]; then
    echo "[ERROR] Valid source tarball required (--tar <path>)" >&2
    exit 1
fi

TIMESTAMP=$(date -u +%Y%m%d_%H%M%S)
SHORT_SHA=${COMMIT_SHA:-"unknown"}
RELEASE_ID="${TIMESTAMP}_${SHORT_SHA:0:7}"
RELEASE_DIR="${RELEASES_DIR}/${RELEASE_ID}"

echo "=== Moltbook Alpha Release Deployment: ${RELEASE_ID} ==="

# 1. Ensure required system users and directories exist
if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
    echo "[SYSTEM] Creating dedicated service user: ${SERVICE_USER}"
    useradd --system --no-create-home --user-group --shell /usr/sbin/nologin "$SERVICE_USER"
fi

mkdir -p "$RELEASES_DIR" "$DATA_DIR" "$LOG_DIR" "$(dirname "$CONFIG_FILE")"
chown -R "${SERVICE_USER}:${SERVICE_GROUP}" "$DATA_DIR" "$LOG_DIR"
chmod 750 "$DATA_DIR" "$LOG_DIR"

# 2. Extract release into new directory
echo "[DEPLOY] Extracting release to ${RELEASE_DIR}..."
mkdir -p "$RELEASE_DIR"
tar -xzf "$SRC_TAR" -C "$RELEASE_DIR"

# 3. Create isolated virtual environment
echo "[DEPLOY] Creating isolated Python virtual environment..."
python3 -m venv "${RELEASE_DIR}/venv"
"${RELEASE_DIR}/venv/bin/pip" install --upgrade pip setuptools wheel --no-warn-script-location

if [ -f "${RELEASE_DIR}/requirements.txt" ]; then
    echo "[DEPLOY] Installing pinned production dependencies..."
    "${RELEASE_DIR}/venv/bin/pip" install -r "${RELEASE_DIR}/requirements.txt" --no-warn-script-location
fi

# Ensure application code is owned by service user
chown -R "${SERVICE_USER}:${SERVICE_GROUP}" "$RELEASE_DIR"
# Make application code readable and directories traversable
chmod -R u=rwX,go=rX "$RELEASE_DIR"
# Ensure operational scripts in ops/server are executable
if [ -d "${RELEASE_DIR}/ops/server" ]; then
    chmod +x "${RELEASE_DIR}/ops/server"/*.sh || true
fi

# 4. Save current target for rollback if needed
PREVIOUS_RELEASE=""
if [ -L "$CURRENT_LINK" ]; then
    PREVIOUS_RELEASE=$(readlink -f "$CURRENT_LINK" || true)
fi

# 5. Atomically update 'current' symlink
echo "[DEPLOY] Updating current release symlink..."
ln -sfn "$RELEASE_DIR" "${CURRENT_LINK}.tmp"
mv -Tf "${CURRENT_LINK}.tmp" "$CURRENT_LINK"

# 6. Reload systemd and restart service
if [ -f "/etc/systemd/system/${SERVICE_NAME}.service" ]; then
    echo "[SYSTEMD] Reloading daemon and restarting ${SERVICE_NAME}..."
    systemctl daemon-reload
    systemctl restart "${SERVICE_NAME}"

    # 7. Post-deployment health verification
    echo "[VERIFY] Running post-deployment health check..."
    sleep 2
    if [ -f "${CURRENT_LINK}/ops/server/health_check.sh" ]; then
        if ! bash "${CURRENT_LINK}/ops/server/health_check.sh"; then
            echo "[ALERT] Post-deployment health check FAILED!"
            if [ -n "$PREVIOUS_RELEASE" ] && [ -d "$PREVIOUS_RELEASE" ]; then
                echo "[ROLLBACK] Reverting symlink to previous release: ${PREVIOUS_RELEASE}"
                ln -sfn "$PREVIOUS_RELEASE" "${CURRENT_LINK}.tmp"
                mv -Tf "${CURRENT_LINK}.tmp" "$CURRENT_LINK"
                systemctl restart "${SERVICE_NAME}"
                echo "[ROLLBACK] Service restored to previous release."
            fi
            exit 1
        fi
    fi
else
    echo "[WARN] Service unit /etc/systemd/system/${SERVICE_NAME}.service not yet installed."
fi

echo "=== Deployment ${RELEASE_ID} Completed Successfully ==="
