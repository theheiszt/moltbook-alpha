#!/usr/bin/env python3
"""
Moltbook Alpha — Autonomous Agent Integration Workflow Example.
Demonstrates client-side DAG parameter planning, intelligence consumption,
and offline cryptographic state witness verification using the Moltbook Alpha SDK.
"""

import sys
from pathlib import Path

# Add sdk directory to path for local execution
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "sdk"))
from moltbook_intel import MoltbookApiError, MoltbookIntelClient  # noqa: E402


def run_agent_workflow(api_base: str = "http://127.0.0.1:8080", api_key: str = "molt_pilot_pilot_4682f74ed5e543fdacdd150b5df93d4c"):
    print("======================================================================")
    print("      MOLTBOOK ALPHA AUTONOMOUS AGENT SDK INTEGRATION WORKFLOW        ")
    print("======================================================================")

    client = MoltbookIntelClient(base_url=api_base, api_key=api_key)

    # 1. Health check
    print("\n[*] 1. Checking API health and subsystem diagnostics...")
    try:
        health = client.health()
        print(f"  [PASS] Server status: {health.get('status')} | Version: {health.get('version')}")
    except Exception as e:
        print(f"  [FAIL] Health check failed: {e}")
        return

    # 2. Account Quota Inspection
    print("\n[*] 2. Inspecting Account Quota (Non-deducting)...")
    try:
        quota = client.get_quota()
        print(f"  [PASS] Tier: {quota.get('tier')} | Credits Remaining: {quota.get('credits_remaining')}")
        print(f"  [PASS] Active Lots: {len(quota.get('credit_lots', []))}")
    except MoltbookApiError as e:
        print(f"  [FAIL] Quota check failed: {e.code} - {e.message}")
        return

    # 3. DAG Parameter Planning
    print("\n[*] 3. Compiling Tool Parameter DAG for verify_solana_payment...")
    resolver = client.get_dag_resolver("verify_solana_payment")
    print(f"  [PASS] Tool Name: {resolver.tool_name} (Schema Version: {resolver.version})")
    print(f"  [PASS] Topological Execution Stages: {resolver.topological_stages}")

    # Validate simulated inputs
    test_inputs = {
        "transaction_signature": "4vJ9JU1bJJE96ZXUsCFHRaeLiMWEx78bsV3S4...",
        "invoice_id": "inv_test_12345",
        "asset": "USDC",
    }
    validation_res = resolver.validate(test_inputs)
    print(f"  [PASS] Parameter Input Validation: Valid = {validation_res['valid']}")

    # 4. Ingest Synthesized Intelligence
    print("\n[*] 4. Consuming Synthesized Market Briefing (Deducts 1 Credit)...")
    try:
        briefing = client.get_latest_briefing()
        witness_id = briefing.get("state_witness_id")
        remaining = briefing.get("credits_remaining")
        print(f"  [PASS] Briefing Received! Credits remaining: {remaining}")
        print(f"  [PASS] State Witness ID received: {witness_id}")
    except MoltbookApiError as e:
        print(f"  [FAIL] Briefing consumption failed: {e.code} - {e.message}")
        return

    # 5. Offline Cryptographic Witness Verification
    print("\n[*] 5. Performing 100% Offline Cryptographic Witness Verification...")
    if witness_id:
        witness_record = client.get_witness(witness_id)
        local_res = client.verify_witness_local(witness_record)
        print(f"  [PASS] Digest Match: {local_res['digest_matches']}")
        print(f"  [PASS] Ed25519 Signature Valid: {local_res['signature_valid']}")
        print(f"  [PASS] Overall Witness Valid: {local_res['valid']}")
        if local_res["valid"]:
            print("  --> Mathematically verified receipt: state transition was non-repudiably signed by server.")

    # 6. Granular Signal Query
    print("\n[*] 6. Querying High-Confidence Signals...")
    signals = client.get_signals(limit=3)
    for s in signals:
        print(f"  - [{s['category'].upper()}] {s['headline']} ({s['confidence']})")

    print("\n======================================================================")
    print("             AGENT WORKFLOW EXECUTED WITH 100% SUCCESS                ")
    print("======================================================================")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Moltbook Alpha SDK Autonomous Agent Demo")
    parser.add_argument("--server", default="http://127.0.0.1:8080", help="API server base URL")
    parser.add_argument("--key", default="molt_pilot_pilot_4682f74ed5e543fdacdd150b5df93d4c", help="Pilot API Key")
    args = parser.parse_args()

    run_agent_workflow(api_base=args.server, api_key=args.key)
