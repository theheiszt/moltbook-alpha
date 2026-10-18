"""
Administrative CLI for Moltbook Alpha API.
Provides explicit, documented key provisioning, key revocation, and security audit inspection without backdoors.
"""

import sys
import argparse
from typing import Optional
from config import DB_PATH, load_payment_config
from storage import StorageManager


def create_admin_key(credits: int = 999999):
    storage = StorageManager(DB_PATH)
    raw_key, record = storage.create_api_key(tier="admin", credits=credits, prefix_tag="molt_admin")
    storage.log_audit_event("admin_key_provisioned", f"Manually provisioned admin key prefix={record['key_prefix']} credits={credits}")
    print("=" * 60)
    print("ADMINISTRATOR API KEY CREATED SUCCESSFULLY")
    print("=" * 60)
    print(f"Key:     {raw_key}")
    print(f"Prefix:  {record['key_prefix']}")
    print(f"Tier:    {record['tier']}")
    print(f"Credits: {record['credits']}")
    print("=" * 60)
    print("IMPORTANT: Store this key securely. It will not be shown again.")
    print("=" * 60)


def create_pilot_key(recipient: str, credits: int = 100) -> str:
    storage = StorageManager(DB_PATH)
    raw_key, record = storage.create_api_key(tier="pilot", credits=credits, prefix_tag="molt_pilot")
    storage.log_audit_event("pilot_key_provisioned", f"Manually provisioned pilot key for recipient='{recipient}' prefix={record['key_prefix']} credits={credits}")
    print("=" * 60)
    print("ALPHA PILOT API KEY CREATED SUCCESSFULLY")
    print("=" * 60)
    print(f"Recipient: {recipient}")
    print(f"Key:       {raw_key}")
    print(f"Prefix:    {record['key_prefix']}")
    print(f"Tier:      {record['tier']}")
    print(f"Credits:   {record['credits']}")
    print("=" * 60)
    print("IMPORTANT: Deliver this key directly to the pilot tester.")
    print("=" * 60)
    return raw_key


def inspect_key(key_target: str):
    storage = StorageManager(DB_PATH)
    with storage.connection() as conn:
        cur = conn.cursor()
        if key_target.endswith("..."):
            cur.execute("SELECT key_prefix, tier, credits, is_active, created_at FROM api_keys WHERE key_prefix = ?", (key_target,))
        else:
            k_hash = storage.hash_key(key_target)
            cur.execute("SELECT key_prefix, tier, credits, is_active, created_at FROM api_keys WHERE key_hash = ? OR key_prefix = ?", (k_hash, key_target))
        row = cur.fetchone()
        if not row:
            print(f"[-] No API key found matching target: {key_target}")
            return
        print("=" * 60)
        print("API KEY STATUS & QUOTA INSPECTION")
        print("=" * 60)
        print(f"Prefix:     {row['key_prefix']}")
        print(f"Tier:       {row['tier']}")
        print(f"Credits:    {row['credits']}")
        print(f"Active:     {bool(row['is_active'])}")
        print(f"Created At: {row['created_at']}")
        print("=" * 60)


def list_invoices(limit: int = 20):
    storage = StorageManager(DB_PATH)
    with storage.connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT invoice_id, reference, tier, credits, amount_raw, asset, status, created_at, fulfilled_at FROM payment_invoices ORDER BY created_at DESC LIMIT ?", (limit,))
        rows = cur.fetchall()
        if not rows:
            print("No payment invoices found.")
            return
        print(f"{'Invoice ID':<28} {'Tier':<14} {'Credits':<8} {'Status':<10} {'Amount':<14} {'Created At'}")
        print("-" * 95)
        for r in rows:
            divisor = 1_000_000.0 if r["asset"] == "USDC" else 1_000_000_000.0
            amt = f"{r['amount_raw'] / divisor:.2f} {r['asset']}"
            print(f"{r['invoice_id']:<28} {r['tier']:<14} {r['credits']:<8} {r['status']:<10} {amt:<14} {r['created_at']}")


def revoke_key(key_target: str):
    storage = StorageManager(DB_PATH)
    success = storage.revoke_key(key_target)
    if success:
        print(f"[+] Successfully revoked API key matching target: {key_target}")
    else:
        print(f"[-] No active API key found matching target: {key_target}")


def list_keys():
    storage = StorageManager(DB_PATH)
    with storage.connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT key_prefix, tier, credits, is_active, created_at FROM api_keys ORDER BY created_at DESC")
        rows = cur.fetchall()
        print(f"{'Prefix':<16} {'Tier':<12} {'Credits':<10} {'Active':<8} {'Created At'}")
        print("-" * 65)
        for r in rows:
            print(f"{r['key_prefix']:<16} {r['tier']:<12} {r['credits']:<10} {r['is_active']:<8} {r['created_at']}")


def view_audit_logs(limit: int = 30, event_type: Optional[str] = None):
    storage = StorageManager(DB_PATH)
    logs = storage.get_audit_logs(limit=limit, event_type=event_type)
    if not logs:
        print("No audit log events found.")
        return

    print("=" * 95)
    print(f"SECURITY AUDIT LOGS (Recent {len(logs)} events)")
    print("=" * 95)
    print(f"{'ID':<6} {'Event Type':<26} {'Created At':<28} {'Detail'}")
    print("-" * 95)
    for log in logs:
        print(f"{log['id']:<6} {log['event_type']:<26} {log['created_at']:<28} {log['detail']}")


def show_config():
    cfg = load_payment_config()
    print("=== Moltbook Alpha API Configuration ===")
    print(f"Treasury Wallet: {cfg['solana_treasury_wallet']}")
    print(f"RPC URL:         {cfg['rpc_url']}")
    print("Rates:")
    for tier, r in cfg["rates"].items():
        print(f"  - {tier}: ${r['usd']} -> {r['credits']} credits (USDC units: {r['usdc_units']}, SOL lamports: {r['sol_lamports']})")


def main():
    parser = argparse.ArgumentParser(description="Moltbook Alpha Administrative CLI")
    subparsers = parser.add_subparsers(dest="command")

    admin_parser = subparsers.add_parser("create-admin-key", help="Provision an explicit administrator key")
    admin_parser.add_argument("--credits", type=int, default=999999, help="Number of credits to allocate")

    pilot_parser = subparsers.add_parser("create-pilot-key", help="Provision an alpha pilot key for an agent")
    pilot_parser.add_argument("--recipient", type=str, required=True, help="Recipient agent or developer name")
    pilot_parser.add_argument("--credits", type=int, default=100, help="Number of pilot credits to allocate (default 100)")

    inspect_parser = subparsers.add_parser("inspect-key", help="Inspect status and quota for a key prefix or token")
    inspect_parser.add_argument("--key", type=str, required=True, help="Key prefix or raw key to inspect")

    revoke_parser = subparsers.add_parser("revoke-key", help="Deactivate an API key by prefix or hash")
    revoke_parser.add_argument("--prefix", type=str, required=True, help="Key prefix or hash to revoke")

    audit_parser = subparsers.add_parser("view-audit-logs", help="Display recent security audit log events")
    audit_parser.add_argument("--limit", type=int, default=30, help="Maximum number of events to show")
    audit_parser.add_argument("--type", type=str, default=None, help="Filter by specific event_type")

    subparsers.add_parser("list-keys", help="List provisioned keys (redacted prefixes)")
    subparsers.add_parser("list-invoices", help="List payment invoices and settlement status")
    subparsers.add_parser("show-config", help="Display active payment and RPC configuration")

    args = parser.parse_args()
    if args.command == "create-admin-key":
        create_admin_key(args.credits)
    elif args.command == "create-pilot-key":
        create_pilot_key(args.recipient, args.credits)
    elif args.command == "inspect-key":
        inspect_key(args.key)
    elif args.command == "revoke-key":
        revoke_key(args.prefix)
    elif args.command == "view-audit-logs":
        view_audit_logs(args.limit, args.type)
    elif args.command == "list-keys":
        list_keys()
    elif args.command == "list-invoices":
        list_invoices()
    elif args.command == "show-config":
        show_config()
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
