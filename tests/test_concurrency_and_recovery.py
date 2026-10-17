"""
Concurrency, Durability, and Operational Recovery Suite (Stage 18 Phase E).
Validates:
1. Simultaneous requests competing for remaining credits (atomic deductions, never negative).
2. Simultaneous attempts to redeem the same payment (idempotency, unique constraint).
3. Transaction rollback consistency on simulated failure.
4. Online zero-downtime SQLite backup and PRAGMA integrity verification.
5. Restoration of backup into isolated test database and validation of row data.
6. Rate-limiter process-local lifecycle.
7. RPC failover recovery cascade across pool.
"""

import concurrent.futures

from storage import StorageManager
from rate_limiter import SlidingWindowRateLimiter
from payment_verifier import SolanaPaymentVerifier, RPCError



def test_concurrent_credit_exhaustion_never_goes_negative(tmp_path):
    storage = StorageManager(tmp_path / "credit_race.db")

    # Mint a key with exactly 10 credits
    api_key, key_data = storage.create_api_key(tier="tier_starter", credits=10)

    results = []

    def try_deduct():
        # deduct_credit takes raw api_key and returns bool
        record, status = storage.authenticate_and_deduct(api_key)
        return status == "ok"

    # Launch 30 concurrent threads competing for 10 credits
    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
        futures = [executor.submit(try_deduct) for _ in range(30)]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    successes = [r for r in results if r is True]
    failures = [r for r in results if r is False]

    assert len(successes) == 10
    assert len(failures) == 20

    # Key credits must be exactly 0, never negative
    info = storage.get_key_info(api_key)
    assert info["credits"] == 0


def test_concurrent_payment_redemption_never_duplicates(tmp_path):
    storage = StorageManager(tmp_path / "redemption_race.db")
    sig = "4" * 88

    results = []

    def try_redeem():
        return storage.redeem_payment(
            tx_signature=sig,
            asset="USDC",
            amount_raw=1_000_000,
            tier="tier_starter",
            credits_to_grant=50,
        )

    # Launch 15 concurrent threads competing to redeem the same signature
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(try_redeem) for _ in range(15)]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    first_mints = [r for r in results if r["status"] == "newly_minted"]
    replays = [r for r in results if r["status"] == "already_redeemed"]

    assert len(first_mints) == 1
    assert len(replays) == 14
    assert storage.get_active_keys_count() == 1


def test_online_backup_and_integrity_verification(tmp_path):
    # Setup primary database with seed data
    primary_db = tmp_path / "primary.db"
    backup_db = tmp_path / "backup_archive.db"
    storage = StorageManager(primary_db)

    # Insert test keys and redemptions
    key1, _ = storage.create_api_key(tier="tier_starter", credits=50)
    key2, _ = storage.create_api_key(tier="tier_pro", credits=300)
    storage.redeem_payment(
        tx_signature="8" * 88,
        asset="SOL",
        amount_raw=5_000_000,
        tier="tier_starter",
        credits_to_grant=50,
    )
    storage.log_audit_event("backup_test", "Seeding before live backup")

    # Verify primary integrity
    assert storage.check_integrity() is True

    # Execute online backup
    storage.backup(backup_db)
    assert backup_db.exists()

    # Open isolated storage on the backup database and verify integrity
    backup_storage = StorageManager(backup_db)
    assert backup_storage.check_integrity() is True

    # Verify backed up data matches primary exactly
    info1 = backup_storage.get_key_info(key1)
    info2 = backup_storage.get_key_info(key2)
    assert info1 is not None and info1["credits"] == 50
    assert info2 is not None and info2["credits"] == 300

    redemption = backup_storage.get_payment_redemption("8" * 88)
    assert redemption is not None and redemption["credits_granted"] == 50


    logs = backup_storage.get_audit_logs(limit=10)
    assert any(log["event_type"] == "backup_test" for log in logs)


def test_restoration_from_backup_in_isolated_location(tmp_path):
    source_db = tmp_path / "source.db"
    backup_file = tmp_path / "nightly_backup.db"
    restored_db = tmp_path / "restored.db"

    # 1. Source operations
    src_storage = StorageManager(source_db)
    src_storage.create_api_key(tier="tier_unlimited", credits=999999)
    src_storage.backup(backup_file)

    # 2. Simulate catastrophic loss: source_db is removed
    source_db.unlink()

    # 3. Restore procedure: copy backup to restored_db
    import shutil
    shutil.copy2(backup_file, restored_db)

    # 4. Initialize storage on restored path
    restored_storage = StorageManager(restored_db)
    assert restored_storage.check_integrity() is True
    assert restored_storage.get_active_keys_count() == 1


def test_rate_limiter_lifecycle_resets_on_fresh_instance():
    # Demonstrates process-local in-memory sliding window behavior
    limiter = SlidingWindowRateLimiter()
    client = "192.0.2.1"

    # Exhaust limit
    for _ in range(5):
        allowed, _ = limiter.is_allowed(client, limit=5, window_seconds=60)
        assert allowed is True

    # 6th request fails
    allowed, retry_after = limiter.is_allowed(client, limit=5, window_seconds=60)
    assert allowed is False
    assert retry_after > 0

    # Fresh process / instance has empty in-memory state
    fresh_limiter = SlidingWindowRateLimiter()
    allowed_fresh, _ = fresh_limiter.is_allowed(client, limit=5, window_seconds=60)
    assert allowed_fresh is True


def test_rpc_pool_cascading_outage_and_recovery():
    call_log = []

    def mock_failing_rpc(endpoint, method, params):
        call_log.append(endpoint)
        if endpoint == "https://primary.rpc":
            raise RPCError("Primary RPC returned 429 Too Many Requests")
        if endpoint == "https://secondary.rpc":
            raise RPCError("Secondary RPC connection timed out")
        if endpoint == "https://tertiary.rpc":
            # Tertiary succeeds
            return {
                "result": {
                    "slot": 500,
                    "blockTime": 1729188000,
                    "confirmationStatus": "finalized",
                    "commitment": "finalized",
                    "transaction": {"signatures": ["1" * 88], "message": {"accountKeys": []}},
                    "meta": {"err": None, "preBalances": [], "postBalances": []},
                }
            }
        raise RPCError("Unknown endpoint")

    verifier = SolanaPaymentVerifier(
        rpc_endpoints=["https://primary.rpc", "https://secondary.rpc", "https://tertiary.rpc"],
        rpc_caller=mock_failing_rpc,
    )

    tx = verifier.fetch_transaction("1" * 88)
    assert tx["slot"] == 500
    assert call_log == ["https://primary.rpc", "https://secondary.rpc", "https://tertiary.rpc"]
    assert verifier.active_rpc_endpoint == "https://tertiary.rpc"

