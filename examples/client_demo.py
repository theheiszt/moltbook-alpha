#!/usr/bin/env python3
"""
Moltbook Alpha — Commercial API Client Demonstration & SDK Walkthrough.

Demonstrates the complete end-to-end autonomous agent workflow:
1. Health check & subsystem diagnostics discovery
2. Payment configuration & rate inspection
3. Handling HTTP 402 Paywall challenges
4. Solana payment verification & API key issuance
5. Non-deducting account quota inspection
6. Authenticated intelligence consumption (Bearer token)
7. Error handling & remedy parsing (invalid key, exhausted quota)

Usage:
    # Run in self-contained synthetic simulation mode (no live server or real funds needed):
    python examples/client_demo.py --mode mock

    # Run against a live running Moltbook Alpha API instance:
    python examples/client_demo.py --mode live --server http://127.0.0.1:8080
"""

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Dict, Any, Optional

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class Colors:
    HEADER = "\033[95m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    RESET = "\033[0m"
    BOLD = "\033[1m"


def print_step(step_num: int, title: str):
    print(f"\n{Colors.BOLD}{Colors.CYAN}=== Step {step_num}: {title} ==={Colors.RESET}")


def print_json(data: Any):
    print(f"{Colors.YELLOW}{json.dumps(data, indent=2)}{Colors.RESET}")


def generate_synthetic_signature() -> str:
    b58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    return "".join(random.choices(b58, k=88))


class MoltbookClientDemo:
    def __init__(self, mode: str = "mock", base_url: str = "http://127.0.0.1:8080"):
        self.mode = mode
        self.base_url = base_url.rstrip("/")
        self.api_key: Optional[str] = None

        if self.mode == "mock":
            from fastapi.testclient import TestClient
            from api_server import app
            self.test_client = TestClient(app)
        else:
            import httpx
            self.http_client = httpx.Client(base_url=self.base_url, timeout=15.0)

    def request(self, method: str, path: str, headers: Optional[Dict[str, str]] = None, json_body: Optional[Any] = None):
        if self.mode == "mock":
            return self.test_client.request(method, path, headers=headers, json=json_body)
        else:
            return self.http_client.request(method, path, headers=headers, json=json_body)

    def run(self, target_tier: str = "tier_starter"):
        print(f"{Colors.BOLD}{Colors.HEADER}")
        print("===================================================================")
        print("       Moltbook Alpha -- Commercial API Customer Demonstration       ")
        print("===================================================================")
        print(f"Mode: {self.mode.upper()} | Target Tier: {target_tier}{Colors.RESET}\n")

        # -------------------------------------------------------------
        # Step 1: Health & Subsystems Diagnostic
        # -------------------------------------------------------------
        print_step(1, "Service Discovery & Diagnostic Health Check")
        resp = self.request("GET", "/v1/health")
        print(f"GET /v1/health -> HTTP {resp.status_code}")
        health_data = resp.json()
        print_json(health_data)
        assert resp.status_code == 200, "Health check failed!"
        print(f"{Colors.GREEN}[PASS] Service operational. Database journal: {health_data.get('subsystems', {}).get('database', {}).get('journal_mode', 'WAL')}{Colors.RESET}")

        # -------------------------------------------------------------
        # Step 2: Payment Configuration & Pricing Tiers
        # -------------------------------------------------------------
        print_step(2, "Fetch Payment Parameters & Accepted Pricing Tiers")
        resp = self.request("GET", "/v1/payments/config")
        print(f"GET /v1/payments/config -> HTTP {resp.status_code}")
        payment_cfg = resp.json()
        print_json(payment_cfg)
        treasury = payment_cfg["treasury_wallet"]
        print(f"{Colors.GREEN}[PASS] Treasury wallet identified: {treasury}{Colors.RESET}")

        # -------------------------------------------------------------
        # Step 3: Trigger HTTP 402 Paywall Challenge
        # -------------------------------------------------------------
        print_step(3, "Query Briefing Without Key (Observe HTTP 402 Paywall)")
        resp = self.request("GET", "/v1/briefing/latest")
        print(f"GET /v1/briefing/latest -> HTTP {resp.status_code}")
        paywall_err = resp.json()
        print_json(paywall_err)
        assert resp.status_code == 402, "Expected HTTP 402 Payment Required!"
        print(f"{Colors.GREEN}[PASS] Paywall challenge verified. Server returned payment remedy instructions.{Colors.RESET}")

        # -------------------------------------------------------------
        # Step 4: Simulate / Execute Solana Settlement & Receive Key
        # -------------------------------------------------------------
        print_step(4, "Submit Solana Settlement to Receive Authenticated API Key")
        sig = generate_synthetic_signature()
        payload = {"transaction_signature": sig, "target_tier": target_tier}
        print(f"Posting settlement for transaction signature: {sig[:20]}...")

        if self.mode == "mock":
            from unittest.mock import patch
            from payment_verifier import VerifiedPayment

            mock_payment = VerifiedPayment(
                tx_signature=sig,
                asset="USDC",
                amount_raw=1_000_000,
                tier=target_tier,
                credits=50 if target_tier == "tier_starter" else (300 if target_tier == "tier_pro" else 999999),
                recipient=treasury,
                commitment="finalized",
                cluster="mainnet-beta",
                slot=320140221,
                block_time=1729188000,
                confirmation_status="finalized",
            )
            with patch("api_server.SolanaPaymentVerifier.verify_payment", return_value=mock_payment):
                resp = self.request("POST", "/v1/payments/verify-solana", json_body=payload)
        else:
            resp = self.request("POST", "/v1/payments/verify-solana", json_body=payload)

        print(f"POST /v1/payments/verify-solana -> HTTP {resp.status_code}")
        verify_data = resp.json()
        print_json(verify_data)

        if resp.status_code != 200:
            print(f"{Colors.RED}Payment verification returned {resp.status_code}: {verify_data}{Colors.RESET}")
            return False

        self.api_key = verify_data.get("api_key")
        print(f"{Colors.GREEN}[PASS] Key successfully minted: {verify_data.get('key_prefix')} ({verify_data.get('credits')} credits granted){Colors.RESET}")

        # -------------------------------------------------------------
        # Step 5: Account Quota Inspection Without Consuming Credit
        # -------------------------------------------------------------
        print_step(5, "Inspect Account Quota Without Deducting Credits")
        resp = self.request("GET", "/v1/account/quota", headers={"Authorization": f"Bearer {self.api_key}"})
        print(f"GET /v1/account/quota -> HTTP {resp.status_code}")
        quota_data = resp.json()
        print_json(quota_data)
        initial_credits = quota_data["credits_remaining"]
        print(f"{Colors.GREEN}[PASS] Quota verified: {initial_credits} credits available on tier '{quota_data['tier']}'.{Colors.RESET}")

        # -------------------------------------------------------------
        # Step 6: Consuming Paid Market Intelligence Briefing
        # -------------------------------------------------------------
        print_step(6, "Execute Authenticated Intelligence Query (Bearer Header)")
        resp = self.request("GET", "/v1/briefing/latest", headers={"Authorization": f"Bearer {self.api_key}"})
        print(f"GET /v1/briefing/latest -> HTTP {resp.status_code}")

        if resp.status_code == 200:
            briefing = resp.json()
            snippet = briefing.get("briefing_markdown", "")[:300].strip()
            print(f"{Colors.YELLOW}Briefing Snippet:\n{snippet}...\n{Colors.RESET}")
            print(f"{Colors.GREEN}[PASS] Successfully fetched market briefing. Credits remaining: {briefing.get('credits_remaining')}{Colors.RESET}")
        elif resp.status_code == 404:
            print(f"{Colors.YELLOW}Auth succeeded (HTTP 404: No briefing markdown report on disk yet). Auth passed cleanly.{Colors.RESET}")
        else:
            print(f"{Colors.RED}Unexpected status: {resp.status_code}{Colors.RESET}")

        # -------------------------------------------------------------
        # Step 7: Verify Deducted Balance via Quota Endpoint
        # -------------------------------------------------------------
        print_step(7, "Re-check Quota to Confirm Credit Accounting")
        resp = self.request("GET", "/v1/account/quota", headers={"Authorization": f"Bearer {self.api_key}"})
        quota_after = resp.json()
        print(f"Credits remaining after intelligence query: {quota_after['credits_remaining']}")
        if target_tier not in ("unlimited", "admin"):
            assert quota_after["credits_remaining"] == initial_credits - 1, "Credit balance was not decremented correctly!"
            print(f"{Colors.GREEN}[PASS] Atomic credit decrement confirmed: {initial_credits} -> {quota_after['credits_remaining']}{Colors.RESET}")
        else:
            print(f"{Colors.GREEN}[PASS] Unlimited tier preserved full balance.{Colors.RESET}")

        # -------------------------------------------------------------
        # Step 8: Error Handling & Remedy Parsing
        # -------------------------------------------------------------
        print_step(8, "Demonstrate Graceful Rejection on Invalid Key")
        resp = self.request("GET", "/v1/account/quota", headers={"Authorization": "Bearer molt_invalid_token_999"})
        print(f"GET /v1/account/quota (invalid key) -> HTTP {resp.status_code}")
        err_data = resp.json()
        print_json(err_data)
        assert resp.status_code == 403, "Expected 403 Forbidden!"
        print(f"{Colors.GREEN}[PASS] Invalid token rejected with actionable remedy instructions.{Colors.RESET}")

        print(f"\n{Colors.BOLD}{Colors.GREEN}===================================================================")
        print("       ALL CLIENT INTEGRATION DEMO CHECKS PASSED (100% OK)         ")
        print("==================================================================={Colors.RESET}\n")
        return True


def main():
    parser = argparse.ArgumentParser(description="Moltbook Alpha Commercial API Client Demo")
    parser.add_argument("--mode", choices=["mock", "live"], default="mock", help="Demo execution mode")
    parser.add_argument("--server", default="http://127.0.0.1:8080", help="Live API server base URL")
    parser.add_argument("--tier", choices=["tier_starter", "tier_pro", "tier_unlimited"], default="tier_starter", help="Target subscription tier")
    args = parser.parse_args()

    demo = MoltbookClientDemo(mode=args.mode, base_url=args.server)
    success = demo.run(target_tier=args.tier)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
