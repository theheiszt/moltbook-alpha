"""
Tests for transactional SQLite storage, concurrency safety, and replay protection.
"""

import tempfile
import threading
from pathlib import Path
from storage import StorageManager


def test_storage_initialization():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        storage = StorageManager(db_path)
        assert db_path.exists()

        # Create key
        raw_key, record = storage.create_api_key(tier="starter", credits=10)
        assert raw_key.startswith("molt_starter_")
        assert record["credits"] == 10

        # Query info
        info = storage.get_key_info(raw_key)
        assert info is not None
        assert info["credits"] == 10
        assert info["tier"] == "starter"


def test_concurrent_credit_deductions_never_go_negative():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        storage = StorageManager(db_path)

        # 5 credits available
        raw_key, _ = storage.create_api_key(tier="starter", credits=5)

        successful_deductions = []
        exhausted_deductions = []

        def worker():
            _, state = storage.authenticate_and_deduct(raw_key)
            if state == "ok":
                successful_deductions.append(1)
            elif state == "exhausted":
                exhausted_deductions.append(1)

        # 25 concurrent threads racing for 5 credits
        threads = [threading.Thread(target=worker) for _ in range(25)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(successful_deductions) == 5
        assert len(exhausted_deductions) == 20

        # Final balance must be exactly 0
        info = storage.get_key_info(raw_key)
        assert info["credits"] == 0


def test_concurrent_payment_redemption_idempotency():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        storage = StorageManager(db_path)

        sig = "5wHu1qwLq7Xg5WpS1Gv7nJ8cK3L9bM2rT4vN6pQ8sY1xZ3aB5cD7eF9gH2jK4mN6pQ8sY1xZ3aB5cD7eF9gH2jK4"

        minted_results = []
        replayed_results = []

        def worker():
            res = storage.redeem_payment(
                tx_signature=sig,
                asset="USDC",
                amount_raw=1_000_000,
                tier="tier_starter",
                credits_to_grant=50
            )
            if res["status"] == "newly_minted":
                minted_results.append(res)
            elif res["status"] == "already_redeemed":
                replayed_results.append(res)

        threads = [threading.Thread(target=worker) for _ in range(15)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Exactly 1 thread successfully minted
        assert len(minted_results) == 1
        # The remaining 14 got idempotent already_redeemed
        assert len(replayed_results) == 14

        # Total keys in DB for this payment is exactly 1
        with storage._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM payment_redemptions WHERE tx_signature = ?", (sig,))
            count = cur.fetchone()[0]
            assert count == 1


def test_legacy_migration_never_imports_master_admin_backdoor():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        json_path = Path(tmpdir) / "legacy_keys.json"

        # Simulate legacy json with backdoor and user keys
        import json
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump({
                "master_admin_token": {"credits": 999999, "tier": "unlimited"},
                "legitimate_user_key": {"credits": 42, "tier": "pro"},
            }, f)

        storage = StorageManager(db_path)
        storage.migrate_from_json(json_path)

        # Backdoor MUST NOT be imported
        admin_info = storage.get_key_info("master_admin_token")
        assert admin_info is None

        # Legitimate key IS imported
        user_info = storage.get_key_info("legitimate_user_key")
        assert user_info is not None
        assert user_info["credits"] == 42
        assert user_info["tier"] == "pro"
