#!/usr/bin/env bash
# ==============================================================================
# ops/server/bootstrap_server.sh
# One-time host initialization script for Moltbook Alpha API on Ubuntu.
# Designed for interactive execution by the system administrator with normal sudo.
# Establishes dedicated service account, filesystem directories, operational scripts,
# systemd service unit, and least-privilege sudo rules validated via visudo.
# ==============================================================================
set -euo pipefail

if [ "$EUID" -ne 0 ]; then
    echo "[ERROR] This bootstrap script must be run as root or with sudo:" >&2
    echo "  sudo $0" >&2
    exit 1
fi

echo "=== Moltbook Alpha Host Bootstrap Initializer ==="

# 1. Dedicated Service User & Group
SERVICE_USER="moltbook-api"
SERVICE_GROUP="moltbook-api"

if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
    echo "[1/6] Creating unprivileged system service user: ${SERVICE_USER}"
    useradd --system --no-create-home --user-group --shell /usr/sbin/nologin "$SERVICE_USER"
else
    echo "[1/6] System user ${SERVICE_USER} already exists."
fi

# 2. Directory Layout & Base Permissions
echo "[2/6] Configuring application directory hierarchy..."
mkdir -p /opt/moltbook-alpha/releases
mkdir -p /var/lib/moltbook-alpha
mkdir -p /var/log/moltbook-alpha
mkdir -p /var/backups/moltbook-alpha
mkdir -p /etc/moltbook-alpha
mkdir -p /usr/local/sbin/moltbook-ops

chown -R "${SERVICE_USER}:${SERVICE_GROUP}" /var/lib/moltbook-alpha /var/log/moltbook-alpha /var/backups/moltbook-alpha
chmod 750 /var/lib/moltbook-alpha /var/log/moltbook-alpha /var/backups/moltbook-alpha

# Config directory: owned by root, accessible only to root and service user
chown root:root /etc/moltbook-alpha
chmod 750 /etc/moltbook-alpha

# 3. Install Operational Scripts to /usr/local/sbin/moltbook-ops
echo "[3/6] Installing operational scripts to /usr/local/sbin/moltbook-ops..."
SCRIPT_SRC="/home/user/ops/server"
if [ -d "$SCRIPT_SRC" ]; then
    cp "$SCRIPT_SRC"/*.sh /usr/local/sbin/moltbook-ops/
    chown root:root /usr/local/sbin/moltbook-ops/*.sh
    chmod 755 /usr/local/sbin/moltbook-ops/*.sh
    echo "Installed: $(ls /usr/local/sbin/moltbook-ops/*.sh | tr '\n' ' ')"
else
    echo "[WARN] Source directory ${SCRIPT_SRC} not found. Skipping script copy."
fi

# 4. Install Systemd Service Unit
echo "[4/6] Installing systemd service unit..."
SYSTEMD_SRC="/home/user/ops/systemd/moltbook-alpha.service"
if [ -f "$SYSTEMD_SRC" ]; then
    cp "$SYSTEMD_SRC" /etc/systemd/system/moltbook-alpha.service
    chown root:root /etc/systemd/system/moltbook-alpha.service
    chmod 644 /etc/systemd/system/moltbook-alpha.service
    systemctl daemon-reload
    echo "Installed /etc/systemd/system/moltbook-alpha.service"
fi

# 5. Environment Template
if [ ! -f /etc/moltbook-alpha/api.env ]; then
    echo "[5/6] Creating initial protected environment file /etc/moltbook-alpha/api.env..."
    cat << 'EOF' > /etc/moltbook-alpha/api.env
# Moltbook Alpha API Production Configuration
APP_ENV=production
MOLTBOOK_DATA_DIR=/var/lib/moltbook-alpha
MOLTBOOK_HOST=127.0.0.1
MOLTBOOK_PORT=8080
SOLANA_RPC_URL=https://api.mainnet-beta.solana.com
SOLANA_TREASURY_WALLET=BU5zBur46YjnCaY34XGBTJ8KSAG9EExjpZA58wDo7wAx
ENABLE_DEMO_KEYS=false
WEBHOOK_SECRET=moltbook_staging_webhook_secret_internal
EOF
    chown root:"$SERVICE_GROUP" /etc/moltbook-alpha/api.env
    chmod 640 /etc/moltbook-alpha/api.env
else
    echo "[5/6] Environment file /etc/moltbook-alpha/api.env already exists. Preserving."
fi

# 6. Least-Privilege Sudoers Configuration
echo "[6/6] Validating least-privilege sudoers configuration for admin automation..."
SUDOERS_TMP="/tmp/moltbook-admin.sudoers.tmp"
cat << 'EOF' > "$SUDOERS_TMP"
# Least-privilege sudo permissions for Moltbook Alpha operations
# Strictly limits passwordless execution to pinned operational scripts and unit control
user ALL=(ALL) NOPASSWD: /usr/bin/systemctl status moltbook-alpha, \
                         /usr/bin/systemctl start moltbook-alpha, \
                         /usr/bin/systemctl stop moltbook-alpha, \
                         /usr/bin/systemctl restart moltbook-alpha, \
                         /usr/bin/systemctl reload moltbook-alpha, \
                         /usr/local/sbin/moltbook-ops/audit_server.sh, \
                         /usr/local/sbin/moltbook-ops/cleanup_server.sh, \
                         /usr/local/sbin/moltbook-ops/deploy.sh, \
                         /usr/local/sbin/moltbook-ops/health_check.sh, \
                         /usr/local/sbin/moltbook-ops/backup.sh, \
                         /usr/local/sbin/moltbook-ops/restore_test.sh, \
                         /usr/local/sbin/moltbook-ops/rollback.sh, \
                         /usr/local/sbin/moltbook-ops/status.sh, \
                         /usr/local/sbin/moltbook-ops/update_ubuntu.sh
EOF

# Validate syntax strictly using visudo -cf
if visudo -cf "$SUDOERS_TMP"; then
    echo "visudo syntax validation PASSED."
    cp "$SUDOERS_TMP" /etc/sudoers.d/moltbook-admin
    chmod 0440 /etc/sudoers.d/moltbook-admin
    chown root:root /etc/sudoers.d/moltbook-admin
    rm -f "$SUDOERS_TMP"
    echo "Installed: /etc/sudoers.d/moltbook-admin (mode 0440, root:root)"
else
    echo "[ERROR] visudo validation failed on candidate sudoers configuration. File NOT installed." >&2
    rm -f "$SUDOERS_TMP"
    exit 1
fi

echo "=== Bootstrap Completed Successfully ==="
