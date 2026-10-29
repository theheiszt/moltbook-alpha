#!/usr/bin/env bash
# ops/server/tunnel_watchdog.sh
# Self-healing watchdog for the Moltbook Alpha Cloudflare edge gateway.
# Verifies external edge reachability and automatically heals stale/dropped tunnels.
set -euo pipefail

STATUS_SCRIPT="/usr/local/sbin/moltbook-ops/tunnel_status.sh"
if [[ ! -f "$STATUS_SCRIPT" ]]; then
    STATUS_SCRIPT="/opt/moltbook-alpha/current/ops/server/tunnel_status.sh"
fi

if bash "$STATUS_SCRIPT"; then
    exit 0
fi

echo "[WATCHDOG] Edge tunnel unreachable or degraded. Initiating automatic self-healing restart..."
systemctl restart moltbook-tunnel.service
sleep 6

if bash "$STATUS_SCRIPT"; then
    echo "[WATCHDOG] Self-healing succeeded. Edge tunnel restored and gateway_url.txt updated."
    exit 0
else
    echo "[WATCHDOG] Warning: Edge tunnel still warming up after restart."
    exit 1
fi
