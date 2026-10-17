"""
Administrative CLI for Moltbook Alpha API.
Provides explicit, documented key provisioning and operations without backdoors.
"""

import sys
import argparse
from config import DB_PATH, load_payment_config
from storage import StorageManager


def create_admin_key(credits: int = 999999):
    storage = StorageManager(DB_PATH)
    raw_key, record = storage.create_api_key(tier="admin", credits=credits, prefix_tag="molt_admin")
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


def list_keys():
    storage = StorageManager(DB_PATH)
    with storage._get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT key_prefix, tier, credits, is_active, created_at FROM api_keys")
        rows = cur.fetchall()
        print(f"{'Prefix':<16} {'Tier':<12} {'Credits':<10} {'Active':<8} {'Created At'}")
        print("-" * 65)
        for r in rows:
            print(f"{r['key_prefix']:<16} {r['tier']:<12} {r['credits']:<10} {r['is_active']:<8} {r['created_at']}")


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

    subparsers.add_parser("list-keys", help="List provisioned keys (redacted prefixes)")
    subparsers.add_parser("show-config", help="Display active payment and RPC configuration")

    args = parser.parse_args()
    if args.command == "create-admin-key":
        create_admin_key(args.credits)
    elif args.command == "list-keys":
        list_keys()
    elif args.command == "show-config":
        show_config()
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
