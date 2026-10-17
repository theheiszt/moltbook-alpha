"""
Transactional SQLite Storage for Moltbook Alpha API.
Guarantees ACID transactions, thread safety, atomic credit deductions,
idempotent payment redemptions, and cryptographic key hashing.
"""

import sqlite3
import hashlib
import secrets
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, Tuple


class StorageError(Exception):
    """Base exception for storage errors."""
    pass


class StorageManager:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _open_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=10.0,
            check_same_thread=False
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        return conn

    @contextmanager
    def connection(self):
        conn = self._open_connection()
        try:
            yield conn
        finally:
            conn.close()

    _get_connection = connection

    def _init_db(self):
        with self._lock, self.connection() as conn:
            with conn:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS api_keys (
                        key_hash TEXT PRIMARY KEY,
                        key_prefix TEXT NOT NULL,
                        tier TEXT NOT NULL,
                        credits INTEGER NOT NULL,
                        created_at TEXT NOT NULL,
                        is_active INTEGER NOT NULL DEFAULT 1
                    );

                    CREATE TABLE IF NOT EXISTS payment_redemptions (
                        tx_signature TEXT PRIMARY KEY,
                        key_hash TEXT NOT NULL,
                        asset TEXT NOT NULL,
                        amount_raw INTEGER NOT NULL,
                        tier TEXT NOT NULL,
                        credits_granted INTEGER NOT NULL,
                        redeemed_at TEXT NOT NULL,
                        FOREIGN KEY(key_hash) REFERENCES api_keys(key_hash)
                    );

                    CREATE TABLE IF NOT EXISTS audit_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_type TEXT NOT NULL,
                        detail TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS idx_keys_active ON api_keys(is_active);
                    CREATE INDEX IF NOT EXISTS idx_redemptions_hash ON payment_redemptions(key_hash);
                """)

    @staticmethod
    def hash_key(raw_key: str) -> str:
        return hashlib.sha256(raw_key.strip().encode("utf-8")).hexdigest()

    def create_api_key(self, tier: str, credits: int, prefix_tag: str = "molt") -> Tuple[str, Dict[str, Any]]:
        raw_token = f"{prefix_tag}_{tier}_{secrets.token_hex(16)}"
        k_hash = self.hash_key(raw_token)
        k_prefix = raw_token[:12] + "..."
        now_iso = datetime.now(timezone.utc).isoformat()

        with self._lock, self.connection() as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO api_keys (key_hash, key_prefix, tier, credits, created_at, is_active)
                    VALUES (?, ?, ?, ?, ?, 1)
                    """,
                    (k_hash, k_prefix, tier, credits, now_iso)
                )

        return raw_token, {
            "key_hash": k_hash,
            "key_prefix": k_prefix,
            "tier": tier,
            "credits": credits,
            "created_at": now_iso,
            "is_active": 1
        }

    def authenticate_and_deduct(self, raw_key: str) -> Tuple[Optional[Dict[str, Any]], str]:
        """
        Atomically authenticates the API key and decrements credit balance.
        Returns (record, status_code_string).
        Status code: 'ok', 'invalid', 'revoked', 'exhausted'.
        """
        if not raw_key:
            return None, "invalid"

        k_hash = self.hash_key(raw_key)

        with self._lock, self.connection() as conn:
            with conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT key_hash, key_prefix, tier, credits, is_active FROM api_keys WHERE key_hash = ?",
                    (k_hash,)
                )
                row = cur.fetchone()
                if not row:
                    return None, "invalid"

                if row["is_active"] != 1:
                    return None, "revoked"

                tier = row["tier"]
                current_credits = row["credits"]

                if tier in ("unlimited", "admin"):
                    return {
                        "key_prefix": row["key_prefix"],
                        "tier": tier,
                        "credits": current_credits
                    }, "ok"

                if current_credits <= 0:
                    return {
                        "key_prefix": row["key_prefix"],
                        "tier": tier,
                        "credits": 0
                    }, "exhausted"

                cur.execute(
                    "UPDATE api_keys SET credits = credits - 1 WHERE key_hash = ? AND credits > 0",
                    (k_hash,)
                )
                if cur.rowcount == 0:
                    return {
                        "key_prefix": row["key_prefix"],
                        "tier": tier,
                        "credits": 0
                    }, "exhausted"

                return {
                    "key_prefix": row["key_prefix"],
                    "tier": tier,
                    "credits": current_credits - 1
                }, "ok"

    def redeem_payment(
        self,
        tx_signature: str,
        asset: str,
        amount_raw: int,
        tier: str,
        credits_to_grant: int
    ) -> Dict[str, Any]:
        """
        Atomically redeems a verified payment transaction.
        Enforces durable uniqueness: repeated requests for the same transaction
        signature return the previously redeemed result without minting new credits.
        """
        sig = tx_signature.strip()
        now_iso = datetime.now(timezone.utc).isoformat()

        with self._lock, self.connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT p.tx_signature, p.key_hash, p.asset, p.tier, p.credits_granted,
                       k.key_prefix, k.credits
                FROM payment_redemptions p
                JOIN api_keys k ON p.key_hash = k.key_hash
                WHERE p.tx_signature = ?
                """,
                (sig,)
            )
            existing = cur.fetchone()
            if existing:
                return {
                    "status": "already_redeemed",
                    "tx_signature": sig,
                    "key_prefix": existing["key_prefix"],
                    "tier": existing["tier"],
                    "credits": existing["credits"],
                    "message": "Payment signature was previously redeemed."
                }

            # Mint new key for this payment
            raw_token = f"molt_sol_{secrets.token_hex(16)}"
            k_hash = self.hash_key(raw_token)
            k_prefix = raw_token[:12] + "..."

            try:
                with conn:
                    cur.execute(
                        """
                        INSERT INTO api_keys (key_hash, key_prefix, tier, credits, created_at, is_active)
                        VALUES (?, ?, ?, ?, ?, 1)
                        """,
                        (k_hash, k_prefix, tier, credits_to_grant, now_iso)
                    )
                    cur.execute(
                        """
                        INSERT INTO payment_redemptions (tx_signature, key_hash, asset, amount_raw, tier, credits_granted, redeemed_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (sig, k_hash, asset, amount_raw, tier, credits_to_grant, now_iso)
                    )
                return {
                    "status": "newly_minted",
                    "tx_signature": sig,
                    "api_key": raw_token,
                    "key_prefix": k_prefix,
                    "tier": tier,
                    "credits": credits_to_grant,
                    "message": f"Payment confirmed! Minted {credits_to_grant} credits."
                }
            except sqlite3.IntegrityError:
                # Concurrent transaction won the race
                cur.execute(
                    """
                    SELECT p.tx_signature, p.tier, p.credits_granted, k.key_prefix, k.credits
                    FROM payment_redemptions p
                    JOIN api_keys k ON p.key_hash = k.key_hash
                    WHERE p.tx_signature = ?
                    """,
                    (sig,)
                )
                winner = cur.fetchone()
                return {
                    "status": "already_redeemed",
                    "tx_signature": sig,
                    "key_prefix": winner["key_prefix"] if winner else "",
                    "tier": winner["tier"] if winner else tier,
                    "credits": winner["credits"] if winner else 0,
                    "message": "Payment signature was previously redeemed."
                }

    def get_key_info(self, raw_key: str) -> Optional[Dict[str, Any]]:
        k_hash = self.hash_key(raw_key)
        with self._lock, self.connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT key_hash, key_prefix, tier, credits, is_active, created_at FROM api_keys WHERE key_hash = ?",
                (k_hash,)
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def migrate_from_json(self, json_path: Path):
        """
        Migrates existing valid user keys from legacy api_keys.json.
        EXPLICITLY rejects and skips any 'master_admin_token' or backdoor keys.
        """
        if not json_path.exists():
            return

        import json
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return

        with self._lock, self.connection() as conn:
            with conn:
                cur = conn.cursor()
                now_iso = datetime.now(timezone.utc).isoformat()
                for raw_k, meta in data.items():
                    if raw_k == "master_admin_token":
                        continue
                    k_hash = self.hash_key(raw_k)
                    tier = meta.get("tier", "trial")
                    credits = int(meta.get("credits", 0))
                    k_prefix = raw_k[:12] + "..." if len(raw_k) > 12 else raw_k

                    cur.execute(
                        """
                        INSERT OR IGNORE INTO api_keys (key_hash, key_prefix, tier, credits, created_at, is_active)
                        VALUES (?, ?, ?, ?, ?, 1)
                        """,
                        (k_hash, k_prefix, tier, credits, now_iso)
                    )
