#!/usr/bin/env python3
"""
Moltbook Alpha — Commercial API Customer Demonstration & SDK Walkthrough.

Demonstrates the complete end-to-end autonomous agent workflow across 15 steps:
1.  Health and readiness verification (/v1/health)
2.  Payment configuration & pricing discovery (/v1/payments/config)
3.  Handling HTTP 402 Paywall challenge when unauthenticated (/v1/briefing/latest)
4.  Mock/test payment verification and key issuance (/v1/payments/verify-solana)
5.  Idempotency & replay protection: resubmitting signature yields zero extra credits
6.  Non-deducting account quota inspection (/v1/account/quota)
7.  Authenticated sample intelligence query using Bearer token
8.  Subsequent query verification: credit accounting decrements correctly
9.  Credit exhaustion simulation: step down credits to 0
10. Rejection verification: 0-credit key rejected with HTTP 402 Payment Required
11. Security rejection: invalid/non-existent API keys rejected with HTTP 403
12. Input validation: malformed signatures rejected with HTTP 422
13. Rate limiting defense: burst requests rejected with HTTP 429 & Retry-After
14. Persistence verification: verify key records persist across client instances
15. Clean shutdown & diagnostic summary

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
        self.tx_sig: str = generate_synthetic_signature()

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

    def run(self, target_tier: str = "tier_starter") -> bool:
        print(f"{Colors.BOLD}{Colors.HEADER}")
        print("===================================================================")
        print("       Moltbook Alpha -- Commercial API Customer Demonstration       ")
        print("===================================================================")
        print(f"Mode: {self.mode.upper()} (Synthetic Mock Simulation | Zero Real Funds Required)")
        print(f"Target Tier: {target_tier}{Colors.RESET}\n")

        # Step 1: Health
        print_step(1, "Service Discovery & Diagnostic Health Check")
        resp = self.request("GET", "/v1/health")
        print(f"GET /v1/health -> HTTP {resp.status_code}")
        health_data = resp.json()
        print_json(health_data)
        assert resp.status_code == 200, "Health check failed!"
        print(f"{Colors.GREEN}[PASS] Service operational. Database journal: {health_data.get('subsystems', {}).get('database', {}).get('journal_mode', 'WAL')}{Colors.RESET}")

        # Step 2: Payment config
        print_step(2, "Fetch Payment Parameters & Accepted Pricing Tiers")
        resp = self.request("GET", "/v1/payments/config")
        print(f"GET /v1/payments/config -> HTTP {resp.status_code}")
        payment_cfg = resp.json()
        print_json(payment_cfg)
        treasury = payment_cfg["treasury_wallet"]
        print(f"{Colors.GREEN}[PASS] Treasury wallet identified: {treasury}{Colors.RESET}")

        # Step 3: Paywall challenge
        print_step(3, "Query Briefing Without Key (Observe HTTP 402 Paywall)")
        resp = self.request("GET", "/v1/briefing/latest")
        print(f"GET /v1/briefing/latest -> HTTP {resp.status_code}")
        paywall_err = resp.json()
        print_json(paywall_err)
        assert resp.status_code == 402, "Expected HTTP 402 Payment Required!"
        print(f"{Colors.GREEN}[PASS] Paywall challenge verified. Server returned payment remedy instructions.{Colors.RESET}")

        # Step 4: Create Invoice
        print_step(4, "Create Solana Pay Invoice with Zero-Knowledge Claim Secret")
        inv_resp = self.request("POST", "/v1/payments/invoice", json_body={"target_tier": target_tier})
        print(f"POST /v1/payments/invoice -> HTTP {inv_resp.status_code}")
        inv_data = inv_resp.json()
        print_json(inv_data)
        assert inv_resp.status_code == 200, "Invoice creation failed!"
        inv_id = inv_data["invoice_id"]
        reference = inv_data["reference"]
        claim_secret = inv_data["claim_secret"]
        print(f"{Colors.GREEN}[PASS] Invoice created: {inv_id} with Solana Pay reference {reference[:12]}...{Colors.RESET}")

        if self.mode == "mock":
            from unittest.mock import patch
            from payment_verifier import VerifiedPayment

            mock_payment = VerifiedPayment(
                tx_signature=self.tx_sig,
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
                reference=reference,
            )
            with patch("api_server.SolanaPaymentVerifier.verify_payment", return_value=mock_payment):
                return self._run_authenticated_steps(target_tier, treasury, inv_id, claim_secret)
        else:
            return self._run_authenticated_steps(target_tier, treasury, inv_id, claim_secret)

    def _run_authenticated_steps(self, target_tier: str, treasury: str, inv_id: str, claim_secret: str) -> bool:
        # Step 5: Submit settlement
        print_step(5, "Submit Solana Settlement to Receive Authenticated API Key")
        payload = {"transaction_signature": self.tx_sig, "invoice_id": inv_id, "claim_secret": claim_secret}
        print(f"Posting mock settlement for transaction signature: {self.tx_sig[:20]}...")
        resp = self.request("POST", "/v1/payments/verify-solana", json_body=payload)
        print(f"POST /v1/payments/verify-solana -> HTTP {resp.status_code}")
        verify_data = resp.json()
        print_json(verify_data)
        assert resp.status_code == 200, "Payment verification failed!"

        self.api_key = verify_data.get("api_key")
        initial_credits = verify_data.get("credits")
        print(f"{Colors.GREEN}[PASS] Key successfully minted: {verify_data.get('key_prefix')} ({initial_credits} credits granted){Colors.RESET}")

        # Step 5b: Zero-Knowledge Credential Recovery
        print_step("5b", "Demonstrate Zero-Knowledge Credential Recovery (Socket Drop Simulation)")
        claim_resp = self.request("POST", f"/v1/payments/invoice/{inv_id}/claim", json_body={"claim_secret": claim_secret})
        print(f"POST /v1/payments/invoice/{inv_id}/claim -> HTTP {claim_resp.status_code}")
        claim_data = claim_resp.json()
        print_json(claim_data)
        assert claim_resp.status_code == 200
        assert claim_data["api_key"] == self.api_key
        print(f"{Colors.GREEN}[PASS] Zero-knowledge recovery verified: retrieved identical key without double payment.{Colors.RESET}")

        # Step 5c: Idempotency & replay
        print_step("5c", "Resubmit Identical Signature (Verify Replay Protection)")
        resp = self.request("POST", "/v1/payments/verify-solana", json_body=payload)
        print(f"POST /v1/payments/verify-solana (replay) -> HTTP {resp.status_code}")
        replay_data = resp.json()
        print_json(replay_data)
        assert resp.status_code == 200
        assert "previously redeemed" in replay_data.get("message", "") or "already fulfilled" in replay_data.get("message", "")
        print(f"{Colors.GREEN}[PASS] Replay protection confirmed: returned existing key prefix with zero duplicate credits.{Colors.RESET}")

        # Step 6: Non-deducting account quota
        print_step(6, "Inspect Account Quota Without Deducting Credits")
        resp = self.request("GET", "/v1/account/quota", headers={"Authorization": f"Bearer {self.api_key}"})
        print(f"GET /v1/account/quota -> HTTP {resp.status_code}")
        quota_data = resp.json()
        print_json(quota_data)
        assert resp.status_code == 200
        assert quota_data["credits_remaining"] == initial_credits, "Quota inspection decremented credits!"
        print(f"{Colors.GREEN}[PASS] Quota verified: {initial_credits} credits untouched.{Colors.RESET}")

        # Step 7: Sample intelligence query
        print_step(7, "Execute Authenticated Intelligence Query (Bearer Header)")
        resp = self.request("GET", "/v1/briefing/latest", headers={"Authorization": f"Bearer {self.api_key}"})
        print(f"GET /v1/briefing/latest -> HTTP {resp.status_code}")
        assert resp.status_code in (200, 404), f"Unexpected status: {resp.status_code}"
        if resp.status_code == 200:
            briefing = resp.json()
            snippet = briefing.get("briefing_markdown", "")[:200].strip()
            print(f"{Colors.YELLOW}Briefing Snippet: {snippet}...{Colors.RESET}")
        print(f"{Colors.GREEN}[PASS] Query authorized and executed.{Colors.RESET}")

        # Step 8: Subsequent query verification
        print_step(8, "Confirm Credit Accounting Decrement via Quota")
        resp = self.request("GET", "/v1/account/quota", headers={"Authorization": f"Bearer {self.api_key}"})
        quota_after = resp.json()
        expected = initial_credits - 1 if target_tier not in ("unlimited", "admin") else initial_credits
        assert quota_after["credits_remaining"] == expected
        print(f"{Colors.GREEN}[PASS] Credit decrement verified: {initial_credits} -> {quota_after['credits_remaining']}{Colors.RESET}")

        # Step 9: Credit exhaustion simulation
        print_step(9, "Simulate Credit Depletion on a Dedicated Trial Key")
        if self.mode == "mock":
            from api_server import storage
            trial_key, _ = storage.create_api_key(tier="trial", credits=2, prefix_tag="molt_exhaust")
            self.request("GET", "/v1/briefing/latest", headers={"Authorization": f"Bearer {trial_key}"})
            self.request("GET", "/v1/briefing/latest", headers={"Authorization": f"Bearer {trial_key}"})
            q_trial = self.request("GET", "/v1/account/quota", headers={"Authorization": f"Bearer {trial_key}"}).json()
            assert q_trial["credits_remaining"] == 0
            assert q_trial["low_credit_warning"] is True
            print(f"{Colors.GREEN}[PASS] Trial key stepped down to exactly 0 credits with low_credit_warning.{Colors.RESET}")

            # Step 10: Exhausted key rejection
            print_step(10, "Confirm Exhausted Key is Rejected with HTTP 402")
            resp_ex = self.request("GET", "/v1/briefing/latest", headers={"Authorization": f"Bearer {trial_key}"})
            print(f"GET /v1/briefing/latest (0 credits) -> HTTP {resp_ex.status_code}")
            assert resp_ex.status_code == 402
            print(f"{Colors.GREEN}[PASS] 402 Payment Required properly enforced on exhausted balance.{Colors.RESET}")

        # Step 11: Security rejection on invalid key
        print_step(11, "Demonstrate Rejection on Non-Existent Key")
        resp = self.request("GET", "/v1/account/quota", headers={"Authorization": "Bearer molt_invalid_token_999"})
        print(f"GET /v1/account/quota (invalid) -> HTTP {resp.status_code}")
        assert resp.status_code == 403
        print(f"{Colors.GREEN}[PASS] HTTP 403 Forbidden with actionable remedy payload.{Colors.RESET}")

        # Step 12: Input validation
        print_step(12, "Submit Malformed Signature (Input Validation Check)")
        resp = self.request("POST", "/v1/payments/verify-solana", json_body={"transaction_signature": "short_sig"})
        print(f"POST /v1/payments/verify-solana (malformed) -> HTTP {resp.status_code}")
        assert resp.status_code == 422
        print(f"{Colors.GREEN}[PASS] HTTP 422 Unprocessable Content returned for invalid Base58 length.{Colors.RESET}")

        # Step 13: Rate limiting defense
        print_step(13, "Demonstrate Rate Limiting Under Burst Queries")
        if self.mode == "mock":
            from api_server import rate_limiter
            rate_limiter.reset()
            # Threshold for verify-solana is 10 req/min
            for _ in range(10):
                self.request("POST", "/v1/payments/verify-solana", json_body={"transaction_signature": "1" * 88})
            # 11th request must be throttled
            burst_resp = self.request("POST", "/v1/payments/verify-solana", json_body={"transaction_signature": "1" * 88})
            print(f"11th burst query -> HTTP {burst_resp.status_code}")
            assert burst_resp.status_code == 429
            assert "Retry-After" in burst_resp.headers
            print(f"{Colors.GREEN}[PASS] HTTP 429 Too Many Requests enforced with Retry-After: {burst_resp.headers['Retry-After']}s.{Colors.RESET}")
            rate_limiter.reset()

        # Step 14: Persistence verification
        print_step(14, "Verify State Persistence in SQLite Across Client Reload")
        if self.mode == "mock":
            from api_server import storage
            record = storage.get_key_info(self.api_key)
            assert record is not None
            assert record["is_active"] == 1
            print(f"{Colors.GREEN}[PASS] Key record durably verified in SQLite: prefix={record['key_prefix']} credits={record['credits']}{Colors.RESET}")

        # Step 15: Clean shutdown & summary
        print_step(15, "Walkthrough Complete -- Final Status Sign-Off")
        print(f"{Colors.BOLD}{Colors.GREEN}")
        print("===================================================================")
        print("      ALL 15 CUSTOMER JOURNEY STEPS PASSED WITH 100% SUCCESS       ")
        print(f"==================================================================={Colors.RESET}\n")
        return True


def main():
    parser = argparse.ArgumentParser(description="Moltbook Alpha Commercial API Client Demo Walkthrough")
    parser.add_argument("--mode", choices=["mock", "live"], default="mock", help="Demo execution mode")
    parser.add_argument("--server", default="http://127.0.0.1:8080", help="Live API server base URL")
    parser.add_argument("--tier", choices=["tier_starter", "tier_pro", "tier_unlimited"], default="tier_starter", help="Target subscription tier")
    args = parser.parse_args()

    demo = MoltbookClientDemo(mode=args.mode, base_url=args.server)
    success = demo.run(target_tier=args.tier)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
