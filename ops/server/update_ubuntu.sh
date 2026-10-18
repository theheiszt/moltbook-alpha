#!/usr/bin/env bash
# ==============================================================================
# ops/server/update_ubuntu.sh
# Controlled Ubuntu package update workflow.
# Supports --audit (read-only inspection) and --apply (executes safe updates
# preserving existing configuration files and reporting reboot status).
# ==============================================================================
set -euo pipefail

MODE="${1:---audit}"

echo "=== Ubuntu System Update Manager [Mode: ${MODE}] ==="

if [ "$MODE" = "--audit" ]; then
    echo "[AUDIT] Refreshing package lists (read-only audit)..."
    if [ "$EUID" -eq 0 ]; then
        apt update -qq
    fi

    echo "[AUDIT] Checking upgradable packages:"
    UPGRADES=$(apt list --upgradable 2>/dev/null | grep -v "Listing..." || true)
    UPGRADE_COUNT=$(echo "$UPGRADES" | grep -c "/" || echo "0")
    echo "Total upgradable packages: ${UPGRADE_COUNT}"

    if [ "$UPGRADE_COUNT" -gt 0 ]; then
        echo "$UPGRADES" | sed -n '1,30p'
        if [ "$UPGRADE_COUNT" -gt 30 ]; then
            echo "... and $((UPGRADE_COUNT - 30)) more packages."
        fi
    fi

    if [ -f /var/run/reboot-required ]; then
        echo "[STATUS] REBOOT REQUIRED: /var/run/reboot-required is present."
        if [ -f /var/run/reboot-required.pkgs ]; then
            echo "Packages requiring reboot:"
            cat /var/run/reboot-required.pkgs
        fi
    else
        echo "[STATUS] No reboot pending."
    fi
    exit 0

elif [ "$MODE" = "--apply" ]; then
    if [ "$EUID" -ne 0 ]; then
        echo "[ERROR] Applying updates requires root/sudo privileges." >&2
        exit 1
    fi

    # Check free disk space before upgrading
    FREE_SPACE_MB=$(df -m / | awk 'NR==2 {print $4}')
    if [ "$FREE_SPACE_MB" -lt 1024 ]; then
        echo "[ERROR] Insufficient disk space on / (${FREE_SPACE_MB} MB free, require >= 1024 MB). Aborting update." >&2
        exit 1
    fi

    echo "[APPLY] Updating package indexes..."
    apt update

    echo "[APPLY] Upgrading packages safely (preserving custom configs)..."
    DEBIAN_FRONTEND=noninteractive apt-get upgrade -y \
        -o Dpkg::Options::="--force-confdef" \
        -o Dpkg::Options::="--force-confold"

    echo "[APPLY] Cleaning package cache..."
    apt-get autoremove -y
    apt-get autoclean

    if [ -f /var/run/reboot-required ]; then
        echo "================================================================================"
        echo "[ATTENTION] System requires a reboot to complete kernel/library updates."
        if [ -f /var/run/reboot-required.pkgs ]; then
            cat /var/run/reboot-required.pkgs
        fi
        echo "Schedule a controlled reboot with: sudo reboot"
        echo "================================================================================"
    else
        echo "[PASS] Updates completed successfully. No reboot required."
    fi
    exit 0

else
    echo "Usage: $0 [--audit | --apply]" >&2
    exit 1
fi
