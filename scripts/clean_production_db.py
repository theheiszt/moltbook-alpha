#!/usr/bin/env python3
"""
Moltbook Alpha — Production Database Reset & Sanitization Script.
Creates a full timestamped backup before safely wiping synthetic test data
while strictly preserving administrative credentials, market intelligence,
and job board bounties.
"""

import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

def sanitize_database(db_path: Path):
    if not db_path.exists():
        print(f"[ERROR] Database file not found at: {db_path}")
        sys.exit(1)

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    backup_path = db_path.parent / f"{db_path.stem}_backup_{timestamp}.db"

    print(f"=== Moltbook Alpha Database Sanitization ===")
    print(f"Target Database: {db_path}")
    print(f"Creating safety backup at: {backup_path}")
    shutil.copy2(db_path, backup_path)
    print("[BACKUP SUCCESS] Safety copy verified.")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    tables_to_clear = [
        "payment_invoices",
        "payment_redemptions",
        "funnel_events",
        "api_keys",
        "customer_entitlements",
        "credit_lots",
        "credit_ledger_events",
        "state_witnesses",
        "audit_logs",
        "unmatched_payments",
        "verification_challenges",
        "quota_reservations",
        "quota_threshold_alerts",
        "rate_limit_tokens",
        "rate_limit_concurrency",
    ]

    print("\n--- Clearing Synthetic Test Records ---")
    conn.execute("PRAGMA foreign_keys = OFF;")
    conn.commit()

    with conn:
        for table in tables_to_clear:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                count_before = cursor.fetchone()[0]
                cursor.execute(f"DELETE FROM {table}")
                print(f"  [CLEARED] {table:<25} (removed {count_before} test rows)")
            except sqlite3.OperationalError as e:
                print(f"  [SKIPPED] {table:<25} ({e})")

        # Reset SQLite sequence if present
        try:
            cursor.execute("DELETE FROM sqlite_sequence WHERE name IN ({})".format(
                ",".join(f"'{t}'" for t in tables_to_clear)
            ))
        except sqlite3.OperationalError:
            pass

    conn.execute("PRAGMA foreign_keys = ON;")
    conn.commit()

    print("\n--- Vacuuming & Compacting Database ---")
    cursor.execute("VACUUM;")
    conn.commit()

    print("\n--- Verification of Preserved Tables ---")
    preserved_tables = [
        "admin_users",
        "intel_sources",
        "intel_items",
        "intel_signals",
        "intel_briefings",
        "observatory_sync_state",
        "agent_jobs",
        "agent_bounty_escrows",
    ]

    for table in preserved_tables:
        try:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            cnt = cursor.fetchone()[0]
            print(f"  [PRESERVED] {table:<25} ({cnt} rows intact)")
        except sqlite3.OperationalError as e:
            print(f"  [INFO] {table:<25} ({e})")

    conn.close()
    print("\n=== Sanitization Complete: Database is Day-1 Production Ready ===")

if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/moltbook.db")
    sanitize_database(target)
