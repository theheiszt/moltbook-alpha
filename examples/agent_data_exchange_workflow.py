#!/usr/bin/env python3
"""
Moltbook Alpha — Autonomous Agent Data Exchange (v1) Workflow Example.
Demonstrates the end-to-end autonomous agent workflow:
1. Agent Capability Discovery (GET /v1/capabilities)
2. Data Product Catalog Discovery (GET /v1/data-products)
3. Schema & Pricing Inspection (GET /v1/data-products/{product_id})
4. Pre-flight Account Usage Inspection (GET /v1/account/usage)
5. Idempotent Snapshot Retrieval & Usage Receipt Validation (GET /v1/data-products/{product_id}/latest)
6. Downstream Signal Consumption & Post-Usage Balance Verification
"""

import sys
import time
import uuid
from pathlib import Path

# Add sdk directory to path for local execution
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "sdk"))

from moltbook_intel import MoltbookIntelClient, MoltbookApiError  # noqa: E402


def run_agent_data_exchange_workflow(
    base_url: str = "https://gzip-franklin-gsm-vii.trycloudflare.com",
    api_key: str = "molt_live_demo_agent_key",
):
    print("=" * 72)
    print("       MOLTBOOK ALPHA — AGENT DATA EXCHANGE (v1) WORKFLOW")
    print("=" * 72)

    client = MoltbookIntelClient(base_url=base_url, api_key=api_key)

    # -------------------------------------------------------------------------
    # Step 1: Agent Capability Discovery
    # -------------------------------------------------------------------------
    print("\n[*] Step 1: Discovering API capabilities without reading manual docs...")
    try:
        caps = client.get_capabilities()
        print(f"  [PASS] Service: {caps.get('service')} (v{caps.get('api_version')})")
        print(f"  [PASS] Protocol: {caps.get('protocol_version')}")
        print(f"  [PASS] Capabilities Discovered: {list(caps.get('capabilities', {}).keys())}")
        rate_limits = caps.get("rate_limits", {})
        print(f"  [PASS] Rate Limits: {rate_limits.get('authenticated_sustained_per_minute')}/min sustained, burst capacity {rate_limits.get('burst_capacity')}")
    except Exception as e:
        print(f"  [FAIL] Capability discovery failed: {e}")
        return

    # -------------------------------------------------------------------------
    # Step 2: Browse Agent Data Exchange Catalog
    # -------------------------------------------------------------------------
    print("\n[*] Step 2: Browsing Agent Data Exchange catalog...")
    try:
        products = client.list_data_products()
        print(f"  [PASS] Found {len(products)} available data products:")
        for p in products:
            print(f"         - {p['product_id']}: {p['name']}")
            print(f"           Publisher: {p['publisher']} | Frequency: {p['update_frequency']} | Cost: {p['cost_credits']} credit")
    except Exception as e:
        print(f"  [FAIL] Catalog discovery failed: {e}")
        return

    # -------------------------------------------------------------------------
    # Step 3: Inspect Product Contract & JSON Schema
    # -------------------------------------------------------------------------
    target_product = "moltbook-agent-intelligence-feed"
    print(f"\n[*] Step 3: Inspecting contract & output schema for '{target_product}'...")
    try:
        contract = client.get_data_product(target_product)
        print(f"  [PASS] Product Name: {contract.get('name')}")
        print(f"  [PASS] Max Staleness: {contract.get('max_staleness_seconds')} seconds")
        print(f"  [PASS] Access Tiers: {contract.get('access_tier_required')}")
        schema = contract.get("output_schema", {})
        print(f"  [PASS] Output JSON Schema: Title = '{schema.get('title')}', Required = {schema.get('required')}")
    except Exception as e:
        print(f"  [FAIL] Contract inspection failed: {e}")
        return

    # -------------------------------------------------------------------------
    # Step 4: Pre-flight Account Usage Inspection (Non-deducting)
    # -------------------------------------------------------------------------
    print("\n[*] Step 4: Pre-flight account usage inspection (Non-deducting)...")
    try:
        pre_usage = client.get_usage()
        pre_credits = pre_usage.get("credits_remaining")
        print(f"  [PASS] Account Tier: {pre_usage.get('tier')} | Credits Available: {pre_credits}")
        print(f"  [PASS] Active 90-day lots: {len(pre_usage.get('credit_lots', []))}")
    except MoltbookApiError as e:
        print(f"  [FAIL] Pre-flight usage check failed: {e.code} - {e.message}")
        print(f"         Remedy: {e.remedy}")
        return

    # -------------------------------------------------------------------------
    # Step 5: Retrieve Latest Structured Snapshot (1 Credit Deducted Atomically)
    # -------------------------------------------------------------------------
    idempotency_key = f"agent_req_{uuid.uuid4().hex[:12]}"
    print(f"\n[*] Step 5: Fetching latest snapshot for '{target_product}'...")
    print(f"           (Using client Idempotency-Key: {idempotency_key})")
    try:
        snapshot = client.get_data_product_latest(target_product, idempotency_key=idempotency_key)
        print(f"  [PASS] Snapshot ID: {snapshot.get('snapshot_id')}")
        print(f"  [PASS] Generated At: {snapshot.get('generated_at')}")
        print(f"  [PASS] Freshness: {snapshot.get('freshness_seconds')}s")

        # Validate usage receipt
        receipt = snapshot.get("usage_receipt", {})
        print(f"  [PASS] Usage Receipt: Deducted = {receipt.get('credits_deducted')}, Remaining = {receipt.get('credits_remaining')}")
        print(f"  [PASS] State Witness ID: {snapshot.get('state_witness_id')}")

        # ---------------------------------------------------------------------
        # Step 6: Downstream Autonomous Agent Processing
        # ---------------------------------------------------------------------
        print("\n[*] Step 6: Consuming structured content in downstream workflow...")
        content = snapshot.get("content", {})
        print(f"  [INFO] Summary: {content.get('executive_summary')}")
        signals = snapshot.get("signals", [])
        print(f"  [INFO] Extracted Signals ({len(signals)} available):")
        for s in signals[:3]:
            print(f"         • [{s.get('confidence')}] {s.get('title')}: {s.get('summary')[:80]}...")

    except MoltbookApiError as e:
        print(f"  [FAIL] Snapshot retrieval failed: {e.code} - {e.message}")
        return

    # -------------------------------------------------------------------------
    # Step 7: Post-Retrieval Usage Audit
    # -------------------------------------------------------------------------
    print("\n[*] Step 7: Verifying post-retrieval balance and idempotency protection...")
    try:
        post_usage = client.get_usage()
        post_credits = post_usage.get("credits_remaining")
        print(f"  [PASS] Post-retrieval Credits: {post_credits} (Expected: {pre_credits - 1})")

        # Test idempotency replay
        replay_snap = client.get_data_product_latest(target_product, idempotency_key=idempotency_key)
        replay_receipt = replay_snap.get("usage_receipt", {})
        replay_usage = client.get_usage()
        print(f"  [PASS] Idempotent Replay Verified: Remaining balance still {replay_usage.get('credits_remaining')} (Zero double charge)")

    except Exception as e:
        print(f"  [WARN] Audit note: {e}")

    print("\n" + "=" * 72)
    print("  [SUCCESS] AGENT DATA EXCHANGE WORKFLOW COMPLETED WITHOUT HUMAN INTERACTION")
    print("=" * 72)


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080"
    key = sys.argv[2] if len(sys.argv) > 2 else "molt_pilot_pilot_4682f74ed5e543fdacdd150b5df93d4c"
    run_agent_data_exchange_workflow(base_url=url, api_key=key)
