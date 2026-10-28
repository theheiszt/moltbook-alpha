#!/usr/bin/env bash
# ops/server/tunnel_status.sh
# Inspects active Cloudflare tunnel URLs and verifies edge reachability
set -euo pipefail

GATEWAY_FILE="/var/lib/moltbook-alpha/gateway_url.txt"
LIVE_URL=""

# Check journalctl for active trycloudflare tunnel
if command -v journalctl >/dev/null 2>&1; then
    FOUND=$(journalctl --user -u cloudflared -n 100 --no-pager 2>/dev/null | grep -o 'https://[a-zA-Z0-9.-]*\.trycloudflare\.com' | tail -n 1 || true)
    if [[ -z "$FOUND" ]]; then
        FOUND=$(journalctl -u moltbook-tunnel -n 50 --no-pager 2>/dev/null | grep -o 'https://[a-zA-Z0-9.-]*\.trycloudflare\.com' | tail -n 1 || true)
    fi
    if [[ -n "$FOUND" ]]; then
        LIVE_URL="$FOUND"
    fi
fi

# Fallback: check docker logs if running in container
if [[ -z "$LIVE_URL" ]] && command -v docker >/dev/null 2>&1; then
    FOUND=$(docker logs moltbook-tunnel 2>&1 | grep -o 'https://[a-zA-Z0-9.-]*\.trycloudflare\.com' | tail -n 1 || true)
    if [[ -n "$FOUND" ]]; then
        LIVE_URL="$FOUND"
    fi
fi

if [[ -n "$LIVE_URL" ]]; then
    echo "$LIVE_URL" > "$GATEWAY_FILE"
    echo "[GATEWAY] Active Gateway URL: $LIVE_URL"
    # Verify reachability
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$LIVE_URL/v1/health" || echo "000")
    if [[ "$HTTP_CODE" == "200" ]]; then
        echo "[STATUS] Gateway Reachability: PASS (HTTP 200)"
    else
        echo "[STATUS] Gateway Reachability: WARN (HTTP $HTTP_CODE)"
    fi
else
    echo "[ERROR] No active Cloudflare tunnel URL detected."
    exit 1
fi
