#!/usr/bin/env python3
"""
Moltbook Alpha — Public REST API Quickstart.
Demonstrates querying public config, generating invoices, verifying settlement,
and retrieving real-time market intelligence from a hosted Moltbook Alpha Gateway.
"""

import os
import requests

GATEWAY_URL = os.getenv("MOLTBOOK_BASE_URL", "http://10.0.0.190:8080")
API_KEY = os.getenv("MOLTBOOK_API_KEY", "")


def main():
    print("=== Moltbook Alpha Public API Quickstart ===")

    # 1. Health check
    res = requests.get(f"{GATEWAY_URL}/v1/health")
    print(f"1. Health Check: {res.status_code} -> {res.json().get('status')}")

    # 2. Rate & Rail Discovery
    res = requests.get(f"{GATEWAY_URL}/v1/payments/config")
    cfg = res.json()
    print(f"2. Accepted Rails: {cfg.get('accepted_rails')}")
    print(f"   Solana Treasury: {cfg.get('solana_treasury_wallet')}")
    print(f"   Nano Treasury: {cfg.get('nano_treasury_address')}")

    # 3. Query signals (requires API key)
    if API_KEY:
        headers = {"X-API-KEY": API_KEY}
        res = requests.get(f"{GATEWAY_URL}/v1/intel/signals?limit=5", headers=headers)
        if res.status_code == 200:
            signals = res.json().get("signals", [])
            print(f"3. Retrieved {len(signals)} Signals:")
            for s in signals:
                print(f"   - [{s.get('confidence')}] {s.get('headline')}")
        else:
            print(f"3. Query Error: HTTP {res.status_code} -> {res.text}")
    else:
        print("3. Query skipped: set MOLTBOOK_API_KEY environment variable to authenticate.")


if __name__ == "__main__":
    main()
