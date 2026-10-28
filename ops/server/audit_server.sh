#!/usr/bin/env bash
# ==============================================================================
# ops/server/audit_server.sh
# Read-only, safe-to-rerun server inventory and security audit script.
# Captures system configuration, listening ports, services, containers,
# storage, and packages without revealing secrets.
# ==============================================================================
set -euo pipefail

LOG_DIR="/var/log/moltbook-alpha"
FALLBACK_LOG_DIR="/tmp/moltbook-audit"
TIMESTAMP=$(date -u +%Y%m%d_%H%M%S)

if [ -w "$LOG_DIR" ] || [ "$EUID" -eq 0 ]; then
    mkdir -p "$LOG_DIR"
    AUDIT_LOG="${LOG_DIR}/audit_${TIMESTAMP}.log"
else
    mkdir -p "$FALLBACK_LOG_DIR"
    AUDIT_LOG="${FALLBACK_LOG_DIR}/audit_${TIMESTAMP}.log"
fi

# Secret redaction filter
redact_secrets() {
    sed -E \
        -e 's/(password|passwd|secret|token|api_key|private_key)[=:].*/\1=[REDACTED]/gI' \
        -e 's/([A-Fa-f0-9]{32,64})/[REDACTED_HEX_TOKEN]/g' \
        -e 's/Bearer [A-Za-z0-9._~+/-]+/Bearer [REDACTED]/g'
}

log_section() {
    local title="$1"
    echo "" | tee -a "$AUDIT_LOG"
    echo "================================================================================" | tee -a "$AUDIT_LOG"
    echo "=== ${title}" | tee -a "$AUDIT_LOG"
    echo "================================================================================" | tee -a "$AUDIT_LOG"
}

run_check() {
    local desc="$1"
    shift
    echo "--- ${desc} ---" | tee -a "$AUDIT_LOG"
    if command -v "$1" >/dev/null 2>&1; then
        "$@" 2>&1 | redact_secrets | tee -a "$AUDIT_LOG" || echo "[WARN] Command failed with exit code $?" | tee -a "$AUDIT_LOG"
    else
        echo "[SKIP] Command not found: $1" | tee -a "$AUDIT_LOG"
    fi
}

echo "=== Moltbook Alpha Server Audit Started at ${TIMESTAMP} UTC ===" | tee "$AUDIT_LOG"

# 1. System Identity & OS
log_section "1. System Identity and OS Version"
run_check "Hostname & Architecture" hostnamectl
run_check "LSB Release" lsb_release -a
run_check "Kernel Information" uname -a
run_check "System Uptime & Load" uptime
run_check "Current User / Group Identity" id

# 2. Resource Utilization & Storage
log_section "2. Resource Utilization and Filesystems"
run_check "Filesystem Free Space" df -h
run_check "Memory & Swap Utilization" free -h
run_check "Block Devices" lsblk

# 3. Network Interfaces & Firewall
log_section "3. Network Interfaces, Firewall, and Ports"
run_check "Network Interfaces" ip -brief address
if [ "$EUID" -eq 0 ]; then
    run_check "Listening TCP/UDP Sockets (sudo ss -lntup)" ss -lntup
    run_check "UFW Firewall Status (sudo ufw status verbose)" ufw status verbose
else
    run_check "Listening TCP/UDP Sockets (unprivileged)" ss -lntu
    echo "[INFO] Run with sudo or as root to inspect process ownership on all listening sockets and UFW." | tee -a "$AUDIT_LOG"
fi

# 4. Running & Enabled Services
log_section "4. Services and Background Tasks"
run_check "Running Services" systemctl --type=service --state=running --no-pager
run_check "Enabled Services" systemctl list-unit-files --type=service --state=enabled --no-pager
run_check "Active Timers" systemctl list-timers --all --no-pager
run_check "Crontabs (System & User)" crontab -l || true

# 5. Application Processes
log_section "5. Process Inventory (Python, Node, Docker, Web)"
run_check "Relevant Application Processes" ps -eo pid,user,args | grep -E 'python|node|docker|gunicorn|uvicorn|fastapi|solana|moltbook' | grep -v grep || true

# 6. Docker & Container Environments
log_section "6. Docker Containers, Images, and Volumes"
if command -v docker >/dev/null 2>&1; then
    run_check "Docker Containers" docker ps -a
    run_check "Docker Images" docker images
    run_check "Docker Volumes" docker volume ls
else
    echo "[INFO] Docker binary not present on host." | tee -a "$AUDIT_LOG"
fi

# 7. Application & Deployment Directories
log_section "7. Candidate Application & Legacy Directories"
for target_dir in /opt /var/lib/moltbook-alpha /var/www /home/user/apps /home/user/test /home/user/moltbook*; do
    if [ -e "$target_dir" ]; then
        echo "Found directory/file: $target_dir" | tee -a "$AUDIT_LOG"
        ls -la "$target_dir" | head -n 30 | tee -a "$AUDIT_LOG"
    fi
done

# 8. Package Manager Health & Updates
log_section "8. Package Health and Pending Updates"
if [ -f /var/run/reboot-required ]; then
    echo "[STATUS] REBOOT REQUIRED: /var/run/reboot-required exists." | tee -a "$AUDIT_LOG"
    if [ -f /var/run/reboot-required.pkgs ]; then
        echo "Packages requiring reboot:" | tee -a "$AUDIT_LOG"
        cat /var/run/reboot-required.pkgs | tee -a "$AUDIT_LOG"
    fi
else
    echo "[STATUS] No reboot currently required." | tee -a "$AUDIT_LOG"
fi
run_check "Upgradable Packages" apt list --upgradable

# 9. Obsolete Test Installation Detection
log_section "9. Identification of Potential Obsolete Test Workloads"
echo "Scanning for test repositories, unused venvs, or standalone scripts..." | tee -a "$AUDIT_LOG"
find /home/user -maxdepth 3 \( -name "test*" -o -name "*tmp*" -o -name "*.old" -o -name "venv*" \) 2>/dev/null | head -n 50 | tee -a "$AUDIT_LOG" || true

log_section "Audit Complete"
echo "Audit report saved to: ${AUDIT_LOG}" | tee -a "$AUDIT_LOG"
echo "=== Audit Finished Successfully at $(date -u +%Y%m%d_%H%M%S) UTC ===" | tee -a "$AUDIT_LOG"
