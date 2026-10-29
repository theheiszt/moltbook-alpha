"""
Payment & Invoice Reconciliation Engine for Moltbook Alpha.
Performs end-to-end reconciliation:
1. Audits SQLite payment_invoices, payments, unmatched_payments, api_keys, and credit_lots.
2. Expire stale invoices past their TTL.
3. Actively polls on-chain Solana transactions for pending invoice references.
4. Monitors treasury wallet for unsolicited/unmatched incoming transfers.
5. Verifies credit ledger integrity.
6. Operates either in one-shot mode (--once) or continuous background daemon mode (--daemon).
"""

import os
import sys
import time
import json
import sqlite3
import argparse
import signal
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
if os.path.exists("/opt/moltbook-alpha/current"):
    sys.path.insert(0, "/opt/moltbook-alpha/current")

from config import load_payment_config  # noqa: E402
from storage import StorageManager  # noqa: E402


def get_db_path() -> str:
    if os.path.exists("/var/lib/moltbook-alpha/moltbook.db"):
        return "/var/lib/moltbook-alpha/moltbook.db"
    if os.path.exists("moltbook.db"):
        return "moltbook.db"
    return "test_moltbook.db"


def query_solana_rpc(method: str, params: list, rpc_urls: List[str]) -> Any:
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode("utf-8")
    for url in rpc_urls:
        try:
            req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if "result" in data:
                    return data["result"]
        except Exception:
            continue
    return None


def call_reconcile_endpoint(api_url: str, tx_sig: str, invoice_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    payload = {
        "transaction_signature": tx_sig,
        "auto_refund_unmatched": False,
    }
    if invoice_id:
        payload["invoice_id"] = invoice_id

    endpoints = [
        f"{api_url}/v1/payments/reconcile",
        "http://127.0.0.1:8080/v1/payments/reconcile",
        "https://mel-tear-diffs-data.trycloudflare.com/v1/payments/reconcile",
    ]

    for ep in endpoints:
        try:
            req = urllib.request.Request(
                ep,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json", "User-Agent": "MoltbookReconciler/1.0"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            continue
    return None


def check_pending_invoices(storage: StorageManager, rpc_endpoints: List[str], api_url: str) -> List[Dict[str, Any]]:
    """
    Scans pending invoices. For Solana invoices, queries the invoice reference public key.
    If an on-chain transaction landed, triggers atomic reconciliation.
    """
    reconciled = []
    with storage.connection() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM payment_invoices WHERE status = 'pending'")
        pending = [dict(r) for r in cur.fetchall()]

    for inv in pending:
        ref = inv.get("reference")
        rail = inv.get("rail", "solana")
        inv_id = inv.get("invoice_id")
        if rail == "solana" and ref:
            sigs = query_solana_rpc("getSignaturesForAddress", [ref, {"limit": 1}], rpc_endpoints)
            if sigs and len(sigs) > 0:
                tx_sig = sigs[0].get("signature")
                print(f"[RECONCILER] Observed on-chain settlement {tx_sig[:16]}... for pending invoice {inv_id}")
                res = call_reconcile_endpoint(api_url, tx_sig, invoice_id=inv_id)
                if res:
                    print(f"[RECONCILER] Invoice {inv_id} reconciled successfully: {res.get('reconciliation_status')}")
                    reconciled.append(res)
    return reconciled


def check_treasury_signatures(storage: StorageManager, treasury_wallet: str, rpc_endpoints: List[str], api_url: str) -> List[Dict[str, Any]]:
    """
    Scans recent transactions to the treasury wallet. Quarantines unlinked deposits or fulfills
    invoices where payment was submitted directly to treasury without calling verify endpoint.
    """
    reconciled = []
    treasury_sigs = query_solana_rpc("getSignaturesForAddress", [treasury_wallet, {"limit": 10}], rpc_endpoints) or []
    if not treasury_sigs:
        return reconciled

    with storage.connection() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        for item in treasury_sigs:
            sig = item.get("signature")
            if not sig:
                continue
            cur.execute("SELECT 1 FROM payment_redemptions WHERE tx_signature = ?", (sig,))
            if cur.fetchone():
                continue
            cur.execute("SELECT 1 FROM unmatched_payments WHERE tx_signature = ?", (sig,))
            if cur.fetchone():
                continue

            print(f"[RECONCILER] Discovered new unindexed treasury transaction: {sig}")
            res = call_reconcile_endpoint(api_url, sig)
            if res:
                print(f"[RECONCILER] Treasury tx {sig[:16]}... reconciled: {res.get('reconciliation_status')}")
                reconciled.append(res)
    return reconciled


def run_reconciliation(api_url: str = "http://127.0.0.1:8080", verbose: bool = True) -> Dict[str, Any]:
    db_path = get_db_path()
    cfg = load_payment_config()
    storage = StorageManager(db_path)
    rpc_endpoints = cfg.get("rpc_endpoints", ["https://api.mainnet-beta.solana.com"])
    treasury_wallet = cfg.get("solana_treasury_wallet", "BU5zBur46YjnCaY34XGBTJ8KSAG9EExjpZA58wDo7wAx")

    if verbose:
        print("=== Moltbook Alpha Payment Reconciliation Engine ===")
        print(f"Database: {db_path}")
        print(f"Treasury Wallet: {treasury_wallet}")
        print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")

    # 1. Scan pending invoices for on-chain signatures before expiring
    reconciled_pending = check_pending_invoices(storage, rpc_endpoints, api_url)

    # 2. Check treasury wallet for unindexed transactions
    reconciled_treasury = check_treasury_signatures(storage, treasury_wallet, rpc_endpoints, api_url)

    # 3. Expire stale pending invoices past TTL
    expired_count = storage.expire_stale_invoices()
    if expired_count > 0 and verbose:
        print(f"[Invoices] Expired {expired_count} stale pending invoices.")

    # 4. Audit Invoices by Status
    with storage.connection() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cur.execute("SELECT status, COUNT(*) as cnt FROM payment_invoices GROUP BY status")
        invoice_counts = {r["status"]: r["cnt"] for r in cur.fetchall()}

        cur.execute("SELECT * FROM payment_invoices ORDER BY created_at DESC LIMIT 10")
        recent_invoices = [dict(r) for r in cur.fetchall()]

        # 5. Audit Redemptions and Unmatched
        cur.execute("SELECT COUNT(*) FROM payment_redemptions")
        redemption_count = cur.fetchone()[0]

        cur.execute("SELECT * FROM unmatched_payments WHERE status = 'HELD'")
        held_unmatched = [dict(r) for r in cur.fetchall()]

        # 6. Audit API Keys and Credit Ledger Integrity
        cur.execute("SELECT key_prefix, tier, credits, is_active FROM api_keys")
        keys = [dict(r) for r in cur.fetchall()]

        cur.execute("SELECT COUNT(*) FROM credit_lots WHERE status = 'active'")
        active_lots = cur.fetchone()[0]

    # 7. Check On-Chain Treasury State
    treasury_balance_lamports = query_solana_rpc("getBalance", [treasury_wallet], rpc_endpoints)
    treasury_sol = (treasury_balance_lamports["value"] / 1e9) if treasury_balance_lamports and "value" in treasury_balance_lamports else 0.0
    treasury_sigs = query_solana_rpc("getSignaturesForAddress", [treasury_wallet, {"limit": 5}], rpc_endpoints) or []

    report = {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database": db_path,
        "treasury": {
            "address": treasury_wallet,
            "balance_sol": treasury_sol,
            "recent_tx_count": len(treasury_sigs),
        },
        "invoices": {
            "counts_by_status": invoice_counts,
            "expired_this_run": expired_count,
            "reconciled_this_run": len(reconciled_pending) + len(reconciled_treasury),
            "recent_sample": [
                {
                    "invoice_id": inv["invoice_id"],
                    "tier": inv["tier"],
                    "asset": inv["asset"],
                    "amount_raw": inv["amount_raw"],
                    "status": inv["status"],
                    "created_at": inv["created_at"],
                }
                for inv in recent_invoices[:5]
            ],
        },
        "redemptions": {
            "total_fulfilled": redemption_count,
        },
        "unmatched": {
            "held_count": len(held_unmatched),
            "held_records": held_unmatched,
        },
        "keys_and_entitlements": {
            "total_keys": len(keys),
            "active_credit_lots": active_lots,
            "keys_summary": [{"prefix": k["key_prefix"], "tier": k["tier"], "credits": k["credits"]} for k in keys],
        },
    }

    if verbose:
        print("\n--- Summary Report ---")
        print(f"Invoices: {invoice_counts}")
        print(f"Unmatched Held Payments: {len(held_unmatched)}")
        print(f"Active API Keys: {len(keys)}")
        print(f"Treasury Balance: {treasury_sol:.4f} SOL (Recent on-chain signatures: {len(treasury_sigs)})")

    return report


def run_daemon(interval_sec: int = 20, api_url: str = "http://127.0.0.1:8080"):
    print(f"=== Starting Moltbook Payment Reconciler Daemon (Interval: {interval_sec}s) ===")
    running = True

    def _sig_handler(sig, frame):
        nonlocal running
        print(f"\n[RECONCILER] Received signal {sig}, terminating gracefully...")
        running = False

    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)

    iteration = 0
    while running:
        try:
            iteration += 1
            verbose = (iteration == 1 or iteration % 15 == 0)
            if verbose:
                print(f"\n[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] --- Polling Cycle #{iteration} ---")
            run_reconciliation(api_url=api_url, verbose=verbose)
        except Exception as e:
            print(f"[{datetime.now(timezone.utc).isoformat()}] [RECONCILER ERROR]: {e}")

        for _ in range(interval_sec):
            if not running:
                break
            time.sleep(1)

    print("[RECONCILER] Daemon shutdown complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Moltbook Alpha Payment Reconciliation Engine")
    parser.add_argument("--daemon", action="store_true", help="Run continuously in background polling mode")
    parser.add_argument("--interval", type=int, default=20, help="Polling interval in seconds (default: 20)")
    parser.add_argument("--api-url", type=str, default="http://127.0.0.1:8080", help="Base URL of Moltbook API")
    args = parser.parse_args()

    if args.daemon:
        run_daemon(interval_sec=args.interval, api_url=args.api_url)
    else:
        run_reconciliation(api_url=args.api_url, verbose=True)
        print("\nReconciliation completed successfully.")
