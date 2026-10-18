"""
Transactional SQLite Storage for Moltbook Alpha API.
Guarantees ACID transactions, thread safety, atomic credit deductions,
idempotent payment redemptions, and cryptographic key hashing.
"""

import sqlite3
import hashlib
import hmac
import base64
import secrets
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

from config import generate_solana_reference


class StorageError(Exception):
    """Base exception for storage errors."""
    pass


def encrypt_key_envelope(raw_token: str, secret: str) -> str:
    """
    Encrypts raw_token using an authenticated stream cipher keyed by secret.
    Uses PBKDF2-HMAC-SHA256, counter-mode HMAC keystream, and HMAC-SHA256 authentication tag.
    Zero external dependencies.
    """
    salt = b"moltbook_invoice_envelope_salt_v1"
    key = hashlib.pbkdf2_hmac("sha256", secret.strip().encode("utf-8"), salt, 10000, 32)
    nonce = secrets.token_bytes(16)

    plaintext = raw_token.strip().encode("utf-8")
    keystream = bytearray()
    counter = 0
    while len(keystream) < len(plaintext):
        block = hmac.new(key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest()
        keystream.extend(block)
        counter += 1

    ciphertext = bytes(p ^ k for p, k in zip(plaintext, keystream[:len(plaintext)]))
    tag = hmac.new(key, nonce + ciphertext, hashlib.sha256).digest()
    envelope_bytes = nonce + tag + ciphertext
    return base64.urlsafe_b64encode(envelope_bytes).decode("ascii")


def decrypt_key_envelope(envelope_b64: str, secret: str) -> str:
    """
    Decrypts and authenticates raw_token envelope using secret.
    Raises ValueError if tag verification fails or secret is invalid.
    """
    try:
        envelope_bytes = base64.urlsafe_b64decode(envelope_b64.encode("ascii"))
    except Exception as e:
        raise ValueError(f"Malformed key envelope: {e}") from e

    if len(envelope_bytes) < 48:
        raise ValueError("Corrupted key envelope: invalid length")

    nonce = envelope_bytes[:16]
    tag = envelope_bytes[16:48]
    ciphertext = envelope_bytes[48:]

    salt = b"moltbook_invoice_envelope_salt_v1"
    key = hashlib.pbkdf2_hmac("sha256", secret.strip().encode("utf-8"), salt, 10000, 32)

    expected_tag = hmac.new(key, nonce + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(tag, expected_tag):
        raise ValueError("Decryption failed: invalid claim secret or corrupted envelope")

    keystream = bytearray()
    counter = 0
    while len(keystream) < len(ciphertext):
        block = hmac.new(key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest()
        keystream.extend(block)
        counter += 1

    plaintext = bytes(c ^ k for c, k in zip(ciphertext, keystream[:len(ciphertext)]))
    return plaintext.decode("utf-8")


class StorageManager:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._cached_active_count: Optional[int] = None
        self._cached_active_count_time: float = 0.0
        self._mock_time: Optional[datetime] = None
        self._init_db()

    def get_now(self) -> datetime:
        if self._mock_time is not None:
            return self._mock_time
        return datetime.now(timezone.utc)

    def get_now_iso(self) -> str:
        return self.get_now().isoformat()

    def set_clock(self, dt: datetime) -> None:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        self._mock_time = dt

    def advance_clock(self, delta: timedelta) -> None:
        self.set_clock(self.get_now() + delta)

    def reset_clock(self) -> None:
        self._mock_time = None

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

                    CREATE TABLE IF NOT EXISTS payment_invoices (
                        invoice_id TEXT PRIMARY KEY,
                        reference TEXT UNIQUE NOT NULL,
                        tier TEXT NOT NULL,
                        credits INTEGER NOT NULL,
                        asset TEXT NOT NULL,
                        amount_raw INTEGER NOT NULL,
                        recipient TEXT NOT NULL,
                        cluster TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'pending',
                        claim_secret_hash TEXT NOT NULL,
                        encrypted_key_envelope TEXT,
                        tx_signature TEXT UNIQUE,
                        created_at TEXT NOT NULL,
                        expires_at TEXT NOT NULL,
                        fulfilled_at TEXT
                    );

                    CREATE TABLE IF NOT EXISTS audit_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_type TEXT NOT NULL,
                        detail TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS customer_entitlements (
                        entitlement_id TEXT PRIMARY KEY,
                        key_hash TEXT NOT NULL,
                        tier TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'active',
                        activated_at TEXT NOT NULL,
                        expires_at TEXT,
                        renewed_at TEXT,
                        FOREIGN KEY(key_hash) REFERENCES api_keys(key_hash)
                    );

                    CREATE TABLE IF NOT EXISTS credit_lots (
                        lot_id TEXT PRIMARY KEY,
                        key_hash TEXT NOT NULL,
                        lot_type TEXT NOT NULL,
                        credits_granted INTEGER NOT NULL,
                        credits_remaining INTEGER NOT NULL,
                        created_at TEXT NOT NULL,
                        expires_at TEXT,
                        status TEXT NOT NULL DEFAULT 'active',
                        invoice_id TEXT,
                        tx_signature TEXT,
                        FOREIGN KEY(key_hash) REFERENCES api_keys(key_hash)
                    );

                    CREATE TABLE IF NOT EXISTS credit_ledger_events (
                        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        lot_id TEXT,
                        key_hash TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        amount INTEGER NOT NULL,
                        balance_after INTEGER NOT NULL,
                        request_id TEXT,
                        detail TEXT,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY(key_hash) REFERENCES api_keys(key_hash)
                    );

                    CREATE INDEX IF NOT EXISTS idx_keys_active ON api_keys(is_active);
                    CREATE INDEX IF NOT EXISTS idx_redemptions_hash ON payment_redemptions(key_hash);
                    CREATE INDEX IF NOT EXISTS idx_invoices_ref ON payment_invoices(reference);
                    CREATE INDEX IF NOT EXISTS idx_invoices_status ON payment_invoices(status);
                    CREATE INDEX IF NOT EXISTS idx_entitlements_key ON customer_entitlements(key_hash);
                    CREATE INDEX IF NOT EXISTS idx_entitlements_status ON customer_entitlements(status);
                    CREATE INDEX IF NOT EXISTS idx_lots_key ON credit_lots(key_hash);
                    CREATE INDEX IF NOT EXISTS idx_lots_status ON credit_lots(status);
                    CREATE INDEX IF NOT EXISTS idx_lots_expires ON credit_lots(expires_at);
                    CREATE INDEX IF NOT EXISTS idx_ledger_key ON credit_ledger_events(key_hash);
                    CREATE INDEX IF NOT EXISTS idx_ledger_lot ON credit_ledger_events(lot_id);
                """)

                cur = conn.cursor()

                # Additive migration for api_keys
                cur.execute("PRAGMA table_info(api_keys)")
                key_cols = {row["name"] for row in cur.fetchall()}
                for col_name, col_type in [
                    ("entitlement_tier", "TEXT"),
                    ("entitlement_expires_at", "TEXT"),
                ]:
                    if col_name not in key_cols:
                        cur.execute(f"ALTER TABLE api_keys ADD COLUMN {col_name} {col_type}")

                # Additive migration for payment_invoices
                cur.execute("PRAGMA table_info(payment_invoices)")
                inv_cols = {row["name"] for row in cur.fetchall()}
                if "target_key_hash" not in inv_cols:
                    cur.execute("ALTER TABLE payment_invoices ADD COLUMN target_key_hash TEXT")

                # Additive migration for payment_redemptions metadata columns
                cur.execute("PRAGMA table_info(payment_redemptions)")
                existing_cols = {row["name"] for row in cur.fetchall()}
                for col_name, col_type in [
                    ("invoice_id", "TEXT"),
                    ("payer_wallet", "TEXT"),
                    ("reference", "TEXT"),
                    ("slot", "INTEGER"),
                    ("block_time", "INTEGER"),
                ]:
                    if col_name not in existing_cols:
                        cur.execute(f"ALTER TABLE payment_redemptions ADD COLUMN {col_name} {col_type}")

                conn.execute("CREATE INDEX IF NOT EXISTS idx_redemptions_invoice ON payment_redemptions(invoice_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_redemptions_ref ON payment_redemptions(reference)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_invoices_target_key ON payment_invoices(target_key_hash)")

                # Backfill legacy keys that have no records in credit_lots
                cur.execute("SELECT key_hash, key_prefix, tier, credits, created_at, is_active FROM api_keys WHERE key_hash NOT IN (SELECT DISTINCT key_hash FROM credit_lots)")
                legacy_keys = cur.fetchall()
                for lk in legacy_keys:
                    k_h = lk["key_hash"]
                    t = lk["tier"]
                    c = int(lk["credits"])
                    created = lk["created_at"]
                    is_act = int(lk["is_active"])

                    if t in ("unlimited", "premium", "tier_unlimited", "tier_premium"):
                        ent_exp = (datetime.fromisoformat(created) + timedelta(days=30)).isoformat() if created else None
                        lot_credits = 10000 if c == 999999 else c
                    else:
                        ent_exp = None
                        lot_credits = c

                    ent_id = f"ent_legacy_{k_h[:12]}"
                    cur.execute(
                        """
                        INSERT OR IGNORE INTO customer_entitlements (entitlement_id, key_hash, tier, status, activated_at, expires_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (ent_id, k_h, t, "active" if is_act == 1 else "revoked", created, ent_exp)
                    )
                    lot_id = f"lot_legacy_{k_h[:12]}"
                    lot_status = "active" if (is_act == 1 and lot_credits > 0) else "exhausted"
                    cur.execute(
                        """
                        INSERT OR IGNORE INTO credit_lots (lot_id, key_hash, lot_type, credits_granted, credits_remaining, created_at, expires_at, status)
                        VALUES (?, ?, 'legacy', ?, ?, ?, ?, ?)
                        """,
                        (lot_id, k_h, lot_credits, lot_credits, created, ent_exp, lot_status)
                    )
                    cur.execute(
                        """
                        INSERT INTO credit_ledger_events (lot_id, key_hash, event_type, amount, balance_after, detail, created_at)
                        VALUES (?, ?, 'grant', ?, ?, 'legacy_backfill', ?)
                        """,
                        (lot_id, k_h, lot_credits, lot_credits, created)
                    )

    def _expire_overdue_lots_and_entitlements(self, conn: sqlite3.Connection) -> None:
        now_iso = self.get_now_iso()
        cur = conn.cursor()

        # Expire active lots where expires_at < now_iso
        cur.execute(
            """
            SELECT lot_id, key_hash, credits_remaining, expires_at
            FROM credit_lots
            WHERE status = 'active' AND expires_at IS NOT NULL AND expires_at < ?
            """,
            (now_iso,)
        )
        expired_lots = cur.fetchall()
        for lot in expired_lots:
            l_id = lot["lot_id"]
            k_h = lot["key_hash"]
            rem = int(lot["credits_remaining"])
            cur.execute("UPDATE credit_lots SET status = 'expired', credits_remaining = 0 WHERE lot_id = ?", (l_id,))
            if rem > 0:
                cur.execute("UPDATE api_keys SET credits = MAX(0, credits - ?) WHERE key_hash = ?", (rem, k_h))
                cur.execute("SELECT credits FROM api_keys WHERE key_hash = ?", (k_h,))
                key_row = cur.fetchone()
                bal_after = key_row["credits"] if key_row else 0
                cur.execute(
                    """
                    INSERT INTO credit_ledger_events (lot_id, key_hash, event_type, amount, balance_after, detail, created_at)
                    VALUES (?, ?, 'expire', ?, ?, ?, ?)
                    """,
                    (l_id, k_h, rem, bal_after, f"lot {l_id} expired at {lot['expires_at']}", now_iso)
                )

        # Expire active entitlements where expires_at < now_iso
        cur.execute(
            """
            UPDATE customer_entitlements
            SET status = 'expired'
            WHERE status = 'active' AND expires_at IS NOT NULL AND expires_at < ?
            """,
            (now_iso,)
        )
        cur.execute(
            """
            UPDATE api_keys
            SET entitlement_expires_at = ?
            WHERE entitlement_expires_at IS NOT NULL AND entitlement_expires_at < ?
            """,
            (now_iso, now_iso)
        )

    @staticmethod
    def hash_key(raw_key: str) -> str:
        return hashlib.sha256(raw_key.strip().encode("utf-8")).hexdigest()

    def create_api_key(
        self,
        tier: str,
        credits: int,
        prefix_tag: str = "molt",
        validity_days: Optional[int] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        raw_token = f"{prefix_tag}_{tier}_{secrets.token_hex(16)}"
        k_hash = self.hash_key(raw_token)
        k_prefix = raw_token[:12] + "..."
        now = self.get_now()
        now_iso = now.isoformat()

        effective_tier = tier
        if tier in ("unlimited", "premium", "tier_unlimited", "tier_premium"):
            effective_tier = "premium"
            if validity_days is None:
                validity_days = 30
            if credits == 999999 or credits == 0:
                credits = 10000

        exp_iso = (now + timedelta(days=validity_days)).isoformat() if validity_days else None

        with self._lock, self.connection() as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO api_keys (key_hash, key_prefix, tier, credits, created_at, is_active, entitlement_tier, entitlement_expires_at)
                    VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                    """,
                    (k_hash, k_prefix, effective_tier, credits, now_iso, effective_tier, exp_iso)
                )
                ent_id = f"ent_{secrets.token_hex(12)}"
                conn.execute(
                    """
                    INSERT INTO customer_entitlements (entitlement_id, key_hash, tier, status, activated_at, expires_at)
                    VALUES (?, ?, ?, 'active', ?, ?)
                    """,
                    (ent_id, k_hash, effective_tier, now_iso, exp_iso)
                )
                lot_id = f"lot_{secrets.token_hex(12)}"
                conn.execute(
                    """
                    INSERT INTO credit_lots (lot_id, key_hash, lot_type, credits_granted, credits_remaining, created_at, expires_at, status)
                    VALUES (?, ?, 'allowance', ?, ?, ?, ?, 'active')
                    """,
                    (lot_id, k_hash, credits, credits, now_iso, exp_iso)
                )
                conn.execute(
                    """
                    INSERT INTO credit_ledger_events (lot_id, key_hash, event_type, amount, balance_after, detail, created_at)
                    VALUES (?, ?, 'grant', ?, ?, ?, ?)
                    """,
                    (lot_id, k_hash, credits, credits, f"grant_{effective_tier}_{credits}_credits", now_iso)
                )
                self._cached_active_count = None

        return raw_token, {
            "key_hash": k_hash,
            "key_prefix": k_prefix,
            "tier": effective_tier,
            "credits": credits,
            "created_at": now_iso,
            "is_active": 1,
            "expires_at": exp_iso,
        }

    def authenticate_and_deduct(
        self,
        raw_key: str,
        request_id: Optional[str] = None,
    ) -> Tuple[Optional[Dict[str, Any]], str]:
        """
        Atomically authenticates the API key and decrements credit balance using EDF/FIFO credit lots.
        Returns (record, status_code_string).
        Status code: 'ok', 'invalid', 'revoked', 'exhausted', 'entitlement_expired'.
        """
        if not raw_key:
            return None, "invalid"

        k_hash = self.hash_key(raw_key)

        with self._lock, self.connection() as conn:
            with conn:
                self._expire_overdue_lots_and_entitlements(conn)

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

                if tier in ("admin",):
                    return {
                        "key_prefix": row["key_prefix"],
                        "tier": tier,
                        "credits": current_credits,
                        "key_hash": k_hash,
                        "lot_id": None,
                        "request_id": request_id,
                    }, "ok"

                now_iso = self.get_now_iso()

                # Check customer entitlement status
                cur.execute(
                    """
                    SELECT entitlement_id, tier, status, expires_at
                    FROM customer_entitlements
                    WHERE key_hash = ?
                    ORDER BY activated_at DESC LIMIT 1
                    """,
                    (k_hash,)
                )
                ent = cur.fetchone()
                if ent:
                    if ent["status"] != "active" or (ent["expires_at"] and ent["expires_at"] < now_iso):
                        return {
                            "key_prefix": row["key_prefix"],
                            "tier": tier,
                            "credits": current_credits,
                            "key_hash": k_hash,
                        }, "entitlement_expired"
                elif tier in ("unlimited", "premium", "tier_unlimited", "tier_premium"):
                    return {
                        "key_prefix": row["key_prefix"],
                        "tier": tier,
                        "credits": current_credits,
                        "key_hash": k_hash,
                    }, "entitlement_expired"

                if current_credits <= 0:
                    return {
                        "key_prefix": row["key_prefix"],
                        "tier": tier,
                        "credits": 0,
                        "key_hash": k_hash,
                    }, "exhausted"

                # Find earliest-expiring active credit lot (EDF/FIFO)
                cur.execute(
                    """
                    SELECT lot_id, lot_type, credits_remaining, expires_at
                    FROM credit_lots
                    WHERE key_hash = ? AND status = 'active' AND credits_remaining > 0
                      AND (expires_at IS NULL OR expires_at >= ?)
                    ORDER BY
                      CASE WHEN expires_at IS NULL THEN 1 ELSE 0 END ASC,
                      expires_at ASC,
                      created_at ASC
                    LIMIT 1
                    """,
                    (k_hash, now_iso)
                )
                chosen_lot = cur.fetchone()
                if not chosen_lot:
                    return {
                        "key_prefix": row["key_prefix"],
                        "tier": tier,
                        "credits": 0,
                        "key_hash": k_hash,
                    }, "exhausted"

                lot_id = chosen_lot["lot_id"]
                new_lot_rem = chosen_lot["credits_remaining"] - 1
                lot_status = "exhausted" if new_lot_rem == 0 else "active"

                cur.execute(
                    """
                    UPDATE credit_lots
                    SET credits_remaining = ?, status = ?
                    WHERE lot_id = ? AND credits_remaining > 0
                    """,
                    (new_lot_rem, lot_status, lot_id)
                )
                if cur.rowcount == 0:
                    return {
                        "key_prefix": row["key_prefix"],
                        "tier": tier,
                        "credits": 0,
                        "key_hash": k_hash,
                    }, "exhausted"

                cur.execute(
                    "UPDATE api_keys SET credits = credits - 1 WHERE key_hash = ? AND credits > 0",
                    (k_hash,)
                )
                if cur.rowcount == 0:
                    return {
                        "key_prefix": row["key_prefix"],
                        "tier": tier,
                        "credits": 0,
                        "key_hash": k_hash,
                    }, "exhausted"

                new_total = current_credits - 1

                # Record in ledger
                cur.execute(
                    """
                    INSERT INTO credit_ledger_events (lot_id, key_hash, event_type, amount, balance_after, request_id, detail, created_at)
                    VALUES (?, ?, 'deduct', 1, ?, ?, ?, ?)
                    """,
                    (lot_id, k_hash, new_total, request_id, f"query_deduct_from_{lot_id}", now_iso)
                )

                return {
                    "key_prefix": row["key_prefix"],
                    "tier": tier,
                    "credits": new_total,
                    "key_hash": k_hash,
                    "lot_id": lot_id,
                    "request_id": request_id,
                }, "ok"

    def revoke_api_key(self, raw_key: str, reason: str = "") -> bool:
        """
        Revokes an API key by setting is_active = 0.
        Accepts raw API key.
        """
        if not raw_key:
            return False
        k_hash = self.hash_key(raw_key)
        with self._lock, self.connection() as conn:
            with conn:
                cur = conn.cursor()
                cur.execute("UPDATE api_keys SET is_active = 0 WHERE key_hash = ?", (k_hash,))
                affected = cur.rowcount > 0
                if affected:
                    self._cached_active_count = None
                return affected

    def redeem_payment(
        self,
        tx_signature: str,
        asset: str,
        amount_raw: int,
        tier: str,
        credits_to_grant: int,
        target_key_hash: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Atomically redeems a verified payment transaction.
        Enforces durable uniqueness: repeated requests for the same transaction
        signature return the previously redeemed result without minting new credits.
        """
        sig = tx_signature.strip()
        now = self.get_now()
        now_iso = now.isoformat()

        effective_tier = tier
        if tier in ("unlimited", "premium", "tier_unlimited", "tier_premium"):
            effective_tier = "premium"
            if credits_to_grant == 999999 or credits_to_grant == 0:
                credits_to_grant = 10000

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

            if target_key_hash:
                cur.execute("SELECT key_hash, key_prefix, tier, credits, is_active FROM api_keys WHERE key_hash = ?", (target_key_hash,))
                target_key = cur.fetchone()
                if not target_key:
                    raise StorageError(f"Target API key hash '{target_key_hash}' not found.")

                k_hash = target_key_hash
                k_prefix = target_key["key_prefix"]

                try:
                    with conn:
                        if effective_tier in ("topup", "credit_topup"):
                            exp_iso = (now + timedelta(days=90)).isoformat()
                            lot_id = f"lot_topup_{secrets.token_hex(12)}"
                            cur.execute(
                                """
                                INSERT INTO credit_lots (lot_id, key_hash, lot_type, credits_granted, credits_remaining, created_at, expires_at, status, tx_signature)
                                VALUES (?, ?, 'topup', ?, ?, ?, ?, 'active', ?)
                                """,
                                (lot_id, k_hash, credits_to_grant, credits_to_grant, now_iso, exp_iso, sig)
                            )
                            cur.execute("UPDATE api_keys SET credits = credits + ? WHERE key_hash = ?", (credits_to_grant, k_hash))
                            new_credits = target_key["credits"] + credits_to_grant
                            cur.execute(
                                """
                                INSERT INTO credit_ledger_events (lot_id, key_hash, event_type, amount, balance_after, detail, created_at)
                                VALUES (?, ?, 'grant', ?, ?, 'topup_redemption', ?)
                                """,
                                (lot_id, k_hash, credits_to_grant, new_credits, now_iso)
                            )
                        elif effective_tier == "premium":
                            exp_iso = (now + timedelta(days=30)).isoformat()
                            ent_id = f"ent_{secrets.token_hex(12)}"
                            lot_id = f"lot_allowance_{secrets.token_hex(12)}"
                            cur.execute("UPDATE customer_entitlements SET status = 'expired' WHERE key_hash = ? AND status = 'active'", (k_hash,))
                            cur.execute(
                                """
                                INSERT INTO customer_entitlements (entitlement_id, key_hash, tier, status, activated_at, expires_at, renewed_at)
                                VALUES (?, ?, 'premium', 'active', ?, ?, ?)
                                """,
                                (ent_id, k_hash, now_iso, exp_iso, now_iso)
                            )
                            cur.execute(
                                """
                                INSERT INTO credit_lots (lot_id, key_hash, lot_type, credits_granted, credits_remaining, created_at, expires_at, status, tx_signature)
                                VALUES (?, ?, 'allowance', ?, ?, ?, ?, 'active', ?)
                                """,
                                (lot_id, k_hash, credits_to_grant, credits_to_grant, now_iso, exp_iso, sig)
                            )
                            cur.execute("UPDATE api_keys SET tier = 'premium', entitlement_tier = 'premium', entitlement_expires_at = ?, credits = credits + ? WHERE key_hash = ?", (exp_iso, credits_to_grant, k_hash))
                            new_credits = target_key["credits"] + credits_to_grant
                            cur.execute(
                                """
                                INSERT INTO credit_ledger_events (lot_id, key_hash, event_type, amount, balance_after, detail, created_at)
                                VALUES (?, ?, 'grant', ?, ?, 'premium_renewal', ?)
                                """,
                                (lot_id, k_hash, credits_to_grant, new_credits, now_iso)
                            )
                        else:
                            lot_id = f"lot_addon_{secrets.token_hex(12)}"
                            cur.execute(
                                """
                                INSERT INTO credit_lots (lot_id, key_hash, lot_type, credits_granted, credits_remaining, created_at, expires_at, status, tx_signature)
                                VALUES (?, ?, 'allowance', ?, ?, ?, NULL, 'active', ?)
                                """,
                                (lot_id, k_hash, credits_to_grant, credits_to_grant, now_iso, sig)
                            )
                            cur.execute("UPDATE api_keys SET credits = credits + ? WHERE key_hash = ?", (credits_to_grant, k_hash))
                            new_credits = target_key["credits"] + credits_to_grant
                            cur.execute(
                                """
                                INSERT INTO credit_ledger_events (lot_id, key_hash, event_type, amount, balance_after, detail, created_at)
                                VALUES (?, ?, 'grant', ?, ?, 'addon_redemption', ?)
                                """,
                                (lot_id, k_hash, credits_to_grant, new_credits, now_iso)
                            )

                        cur.execute(
                            """
                            INSERT INTO payment_redemptions (tx_signature, key_hash, asset, amount_raw, tier, credits_granted, redeemed_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (sig, k_hash, asset, amount_raw, effective_tier, credits_to_grant, now_iso)
                        )
                        self._cached_active_count = None

                    return {
                        "status": "newly_minted",
                        "tx_signature": sig,
                        "key_prefix": k_prefix,
                        "tier": effective_tier,
                        "credits": new_credits,
                        "message": f"Payment confirmed! Added {credits_to_grant} credits."
                    }
                except sqlite3.IntegrityError:
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
                        "tier": winner["tier"] if winner else effective_tier,
                        "credits": winner["credits"] if winner else 0,
                        "message": "Payment signature was previously redeemed."
                    }

            # Mint new key for this payment
            raw_token = f"molt_sol_{secrets.token_hex(16)}"
            k_hash = self.hash_key(raw_token)
            k_prefix = raw_token[:12] + "..."
            validity_days = 30 if effective_tier == "premium" else None
            exp_iso = (now + timedelta(days=validity_days)).isoformat() if validity_days else None

            try:
                with conn:
                    cur.execute(
                        """
                        INSERT INTO api_keys (key_hash, key_prefix, tier, credits, created_at, is_active, entitlement_tier, entitlement_expires_at)
                        VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                        """,
                        (k_hash, k_prefix, effective_tier, credits_to_grant, now_iso, effective_tier, exp_iso)
                    )
                    ent_id = f"ent_{secrets.token_hex(12)}"
                    cur.execute(
                        """
                        INSERT INTO customer_entitlements (entitlement_id, key_hash, tier, status, activated_at, expires_at)
                        VALUES (?, ?, ?, 'active', ?, ?)
                        """,
                        (ent_id, k_hash, effective_tier, now_iso, exp_iso)
                    )
                    lot_id = f"lot_{secrets.token_hex(12)}"
                    cur.execute(
                        """
                        INSERT INTO credit_lots (lot_id, key_hash, lot_type, credits_granted, credits_remaining, created_at, expires_at, status, tx_signature)
                        VALUES (?, ?, 'allowance', ?, ?, ?, ?, 'active', ?)
                        """,
                        (lot_id, k_hash, credits_to_grant, credits_to_grant, now_iso, exp_iso, sig)
                    )
                    cur.execute(
                        """
                        INSERT INTO credit_ledger_events (lot_id, key_hash, event_type, amount, balance_after, detail, created_at)
                        VALUES (?, ?, 'grant', ?, ?, ?, ?)
                        """,
                        (lot_id, k_hash, credits_to_grant, credits_to_grant, f"grant_{effective_tier}_{credits_to_grant}_credits", now_iso)
                    )
                    cur.execute(
                        """
                        INSERT INTO payment_redemptions (tx_signature, key_hash, asset, amount_raw, tier, credits_granted, redeemed_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (sig, k_hash, asset, amount_raw, effective_tier, credits_to_grant, now_iso)
                    )
                    self._cached_active_count = None
                return {
                    "status": "newly_minted",
                    "tx_signature": sig,
                    "api_key": raw_token,
                    "key_prefix": k_prefix,
                    "tier": effective_tier,
                    "credits": credits_to_grant,
                    "message": f"Payment confirmed! Minted {credits_to_grant} credits."
                }
            except sqlite3.IntegrityError:
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
                    "tier": winner["tier"] if winner else effective_tier,
                    "credits": winner["credits"] if winner else 0,
                    "message": "Payment signature was previously redeemed."
                }

    def create_invoice(
        self,
        tier: str,
        credits: int,
        asset: str,
        amount_raw: int,
        recipient: str,
        cluster: str = "mainnet-beta",
        expiry_seconds: int = 1800,
        expected_payer: Optional[str] = None,
        target_key_hash: Optional[str] = None,
    ) -> Tuple[Dict[str, Any], str, str]:
        """
        Creates a stateful payment invoice with a unique Solana Pay reference address
        and a client-held claim secret for zero-knowledge credential recovery.
        Returns: (invoice_dict, claim_secret, reference)
        """
        invoice_id = f"inv_{secrets.token_hex(12)}"
        claim_secret = f"sec_{secrets.token_hex(20)}"
        reference = generate_solana_reference()
        claim_secret_hash = hashlib.sha256(claim_secret.strip().encode("utf-8")).hexdigest()

        now = self.get_now()
        created_at_iso = now.isoformat()
        expires_at_iso = (now + timedelta(seconds=expiry_seconds)).isoformat()

        effective_tier = tier
        if tier in ("unlimited", "premium", "tier_unlimited", "tier_premium"):
            effective_tier = "premium"
            if credits == 999999 or credits == 0:
                credits = 10000

        with self._lock, self.connection() as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO payment_invoices (
                        invoice_id, reference, tier, credits, asset, amount_raw,
                        recipient, cluster, status, claim_secret_hash, created_at, expires_at,
                        target_key_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)
                    """,
                    (
                        invoice_id,
                        reference,
                        effective_tier,
                        credits,
                        asset,
                        amount_raw,
                        recipient,
                        cluster,
                        claim_secret_hash,
                        created_at_iso,
                        expires_at_iso,
                        target_key_hash,
                    ),
                )

        invoice_record = {
            "invoice_id": invoice_id,
            "reference": reference,
            "tier": effective_tier,
            "credits": credits,
            "asset": asset,
            "amount_raw": amount_raw,
            "recipient": recipient,
            "cluster": cluster,
            "status": "pending",
            "created_at": created_at_iso,
            "expires_at": expires_at_iso,
            "target_key_hash": target_key_hash,
        }
        return invoice_record, claim_secret, reference

    def get_invoice(self, invoice_id: str) -> Optional[Dict[str, Any]]:
        with self._lock, self.connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT invoice_id, reference, tier, credits, asset, amount_raw,
                       recipient, cluster, status, claim_secret_hash, encrypted_key_envelope,
                       tx_signature, created_at, expires_at, fulfilled_at, target_key_hash
                FROM payment_invoices
                WHERE invoice_id = ?
                """,
                (invoice_id.strip(),),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def get_invoice_by_reference(self, reference: str) -> Optional[Dict[str, Any]]:
        with self._lock, self.connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT invoice_id, reference, tier, credits, asset, amount_raw,
                       recipient, cluster, status, claim_secret_hash, encrypted_key_envelope,
                       tx_signature, created_at, expires_at, fulfilled_at, target_key_hash
                FROM payment_invoices
                WHERE reference = ?
                """,
                (reference.strip(),),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def fulfill_invoice_and_redeem(
        self,
        invoice_id: str,
        tx_signature: str,
        asset: str,
        amount_raw: int,
        tier: str,
        credits_to_grant: int,
        claim_secret: Optional[str] = None,
        payer: Optional[str] = None,
        reference: Optional[str] = None,
        slot: Optional[int] = None,
        block_time: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Atomically transitions an invoice from 'pending' to 'fulfilled' and mints or renews an API key.
        Guarantees that:
        1. A transaction signature cannot be redeemed twice.
        2. An invoice cannot be fulfilled twice.
        3. Encrypts the raw key with claim_secret for zero-knowledge client recovery.
        4. Completely rolls back if any operation fails.
        """
        sig = tx_signature.strip()
        inv_id = invoice_id.strip()
        now = self.get_now()
        now_iso = now.isoformat()

        effective_tier = tier
        if tier in ("unlimited", "premium", "tier_unlimited", "tier_premium"):
            effective_tier = "premium"
            if credits_to_grant == 999999 or credits_to_grant == 0:
                credits_to_grant = 10000

        with self._lock, self.connection() as conn:
            cur = conn.cursor()

            # 1. Check if signature was already redeemed
            cur.execute(
                """
                SELECT p.tx_signature, p.key_hash, p.asset, p.tier, p.credits_granted,
                       k.key_prefix, k.credits
                FROM payment_redemptions p
                JOIN api_keys k ON p.key_hash = k.key_hash
                WHERE p.tx_signature = ?
                """,
                (sig,),
            )
            existing_tx = cur.fetchone()
            if existing_tx:
                return {
                    "status": "already_redeemed",
                    "tx_signature": sig,
                    "key_prefix": existing_tx["key_prefix"],
                    "tier": existing_tx["tier"],
                    "credits": existing_tx["credits"],
                    "invoice_id": inv_id,
                    "message": "Payment signature was previously redeemed.",
                }

            # 2. Check invoice state
            cur.execute(
                """
                SELECT invoice_id, reference, tier, credits, asset, amount_raw,
                       status, expires_at, claim_secret_hash, target_key_hash
                FROM payment_invoices
                WHERE invoice_id = ?
                """,
                (inv_id,),
            )
            inv = cur.fetchone()
            if not inv:
                raise StorageError(f"Invoice '{inv_id}' does not exist.")

            if inv["status"] == "fulfilled":
                cur.execute(
                    """
                    SELECT p.tx_signature, k.key_prefix, k.credits, p.tier
                    FROM payment_redemptions p
                    JOIN api_keys k ON p.key_hash = k.key_hash
                    WHERE p.invoice_id = ?
                    """,
                    (inv_id,),
                )
                winner = cur.fetchone()
                return {
                    "status": "already_redeemed",
                    "tx_signature": winner["tx_signature"] if winner else sig,
                    "key_prefix": winner["key_prefix"] if winner else "",
                    "tier": winner["tier"] if winner else effective_tier,
                    "credits": winner["credits"] if winner else 0,
                    "invoice_id": inv_id,
                    "message": "Invoice has already been fulfilled.",
                }

            if inv["status"] == "expired":
                raise StorageError(f"Invoice '{inv_id}' has expired.")

            # Check expiration against current UTC time
            if now_iso > inv["expires_at"]:
                with conn:
                    cur.execute(
                        "UPDATE payment_invoices SET status = 'expired' WHERE invoice_id = ?",
                        (inv_id,),
                    )
                raise StorageError(f"Invoice '{inv_id}' expired at {inv['expires_at']}.")

            if inv["status"] != "pending":
                raise StorageError(f"Invoice '{inv_id}' cannot be fulfilled from state '{inv['status']}'.")

            target_key_hash = inv["target_key_hash"]

            # 3. Handle fulfillment: either update existing key or mint new key
            if target_key_hash:
                cur.execute(
                    "SELECT key_hash, key_prefix, tier, credits, is_active FROM api_keys WHERE key_hash = ?",
                    (target_key_hash,)
                )
                target_key = cur.fetchone()
                if not target_key:
                    raise StorageError(f"Target key hash '{target_key_hash}' associated with invoice does not exist.")

                k_hash = target_key_hash
                k_prefix = target_key["key_prefix"]

                try:
                    with conn:
                        if effective_tier in ("topup", "credit_topup"):
                            exp_iso = (now + timedelta(days=90)).isoformat()
                            lot_id = f"lot_topup_{secrets.token_hex(12)}"
                            cur.execute(
                                """
                                INSERT INTO credit_lots (lot_id, key_hash, lot_type, credits_granted, credits_remaining, created_at, expires_at, status, invoice_id, tx_signature)
                                VALUES (?, ?, 'topup', ?, ?, ?, ?, 'active', ?, ?)
                                """,
                                (lot_id, k_hash, credits_to_grant, credits_to_grant, now_iso, exp_iso, inv_id, sig)
                            )
                            cur.execute("UPDATE api_keys SET credits = credits + ? WHERE key_hash = ?", (credits_to_grant, k_hash))
                            new_credits = target_key["credits"] + credits_to_grant
                            cur.execute(
                                """
                                INSERT INTO credit_ledger_events (lot_id, key_hash, event_type, amount, balance_after, detail, created_at)
                                VALUES (?, ?, 'grant', ?, ?, 'topup_fulfillment', ?)
                                """,
                                (lot_id, k_hash, credits_to_grant, new_credits, now_iso)
                            )
                        elif effective_tier == "premium":
                            exp_iso = (now + timedelta(days=30)).isoformat()
                            ent_id = f"ent_{secrets.token_hex(12)}"
                            lot_id = f"lot_allowance_{secrets.token_hex(12)}"
                            cur.execute("UPDATE customer_entitlements SET status = 'expired' WHERE key_hash = ? AND status = 'active'", (k_hash,))
                            cur.execute(
                                """
                                INSERT INTO customer_entitlements (entitlement_id, key_hash, tier, status, activated_at, expires_at, renewed_at)
                                VALUES (?, ?, 'premium', 'active', ?, ?, ?)
                                """,
                                (ent_id, k_hash, now_iso, exp_iso, now_iso)
                            )
                            cur.execute(
                                """
                                INSERT INTO credit_lots (lot_id, key_hash, lot_type, credits_granted, credits_remaining, created_at, expires_at, status, invoice_id, tx_signature)
                                VALUES (?, ?, 'allowance', ?, ?, ?, ?, 'active', ?, ?)
                                """,
                                (lot_id, k_hash, credits_to_grant, credits_to_grant, now_iso, exp_iso, inv_id, sig)
                            )
                            cur.execute("UPDATE api_keys SET tier = 'premium', entitlement_tier = 'premium', entitlement_expires_at = ?, credits = credits + ? WHERE key_hash = ?", (exp_iso, credits_to_grant, k_hash))
                            new_credits = target_key["credits"] + credits_to_grant
                            cur.execute(
                                """
                                INSERT INTO credit_ledger_events (lot_id, key_hash, event_type, amount, balance_after, detail, created_at)
                                VALUES (?, ?, 'grant', ?, ?, 'premium_renewal_fulfillment', ?)
                                """,
                                (lot_id, k_hash, credits_to_grant, new_credits, now_iso)
                            )
                        else:
                            lot_id = f"lot_addon_{secrets.token_hex(12)}"
                            cur.execute(
                                """
                                INSERT INTO credit_lots (lot_id, key_hash, lot_type, credits_granted, credits_remaining, created_at, expires_at, status, invoice_id, tx_signature)
                                VALUES (?, ?, 'allowance', ?, ?, ?, NULL, 'active', ?, ?)
                                """,
                                (lot_id, k_hash, credits_to_grant, credits_to_grant, now_iso, inv_id, sig)
                            )
                            cur.execute("UPDATE api_keys SET credits = credits + ? WHERE key_hash = ?", (credits_to_grant, k_hash))
                            new_credits = target_key["credits"] + credits_to_grant
                            cur.execute(
                                """
                                INSERT INTO credit_ledger_events (lot_id, key_hash, event_type, amount, balance_after, detail, created_at)
                                VALUES (?, ?, 'grant', ?, ?, 'addon_fulfillment', ?)
                                """,
                                (lot_id, k_hash, credits_to_grant, new_credits, now_iso)
                            )

                        cur.execute(
                            """
                            INSERT INTO payment_redemptions (
                                tx_signature, key_hash, asset, amount_raw, tier,
                                credits_granted, redeemed_at, invoice_id, payer_wallet,
                                reference, slot, block_time
                            )
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                sig,
                                k_hash,
                                asset,
                                amount_raw,
                                effective_tier,
                                credits_to_grant,
                                now_iso,
                                inv_id,
                                payer,
                                reference or inv["reference"],
                                slot,
                                block_time,
                            ),
                        )
                        cur.execute(
                            """
                            UPDATE payment_invoices
                            SET status = 'fulfilled',
                                tx_signature = ?,
                                fulfilled_at = ?
                            WHERE invoice_id = ? AND status = 'pending'
                            """,
                            (sig, now_iso, inv_id),
                        )
                        if cur.rowcount == 0:
                            raise sqlite3.IntegrityError("Invoice fulfillment conflict")
                        self._cached_active_count = None

                    return {
                        "status": "newly_minted",
                        "tx_signature": sig,
                        "key_prefix": k_prefix,
                        "tier": effective_tier,
                        "credits": new_credits,
                        "invoice_id": inv_id,
                        "message": f"Payment confirmed! Added {credits_to_grant} credits.",
                    }
                except sqlite3.IntegrityError:
                    cur.execute(
                        """
                        SELECT p.tx_signature, p.tier, p.credits_granted, k.key_prefix, k.credits
                        FROM payment_redemptions p
                        JOIN api_keys k ON p.key_hash = k.key_hash
                        WHERE p.tx_signature = ? OR p.invoice_id = ?
                        """,
                        (sig, inv_id),
                    )
                    winner = cur.fetchone()
                    return {
                        "status": "already_redeemed",
                        "tx_signature": winner["tx_signature"] if winner else sig,
                        "key_prefix": winner["key_prefix"] if winner else "",
                        "tier": winner["tier"] if winner else effective_tier,
                        "credits": winner["credits"] if winner else 0,
                        "invoice_id": inv_id,
                        "message": "Payment signature or invoice was already redeemed.",
                    }

            # Mint new key and prepare encrypted envelope
            raw_token = f"molt_sol_{secrets.token_hex(16)}"
            k_hash = self.hash_key(raw_token)
            k_prefix = raw_token[:12] + "..."
            validity_days = 30 if effective_tier == "premium" else None
            exp_iso = (now + timedelta(days=validity_days)).isoformat() if validity_days else None

            encrypted_envelope = None
            if claim_secret:
                try:
                    encrypted_envelope = encrypt_key_envelope(raw_token, claim_secret)
                except Exception as e:
                    raise StorageError(f"Failed to prepare key recovery envelope: {e}") from e

            # Atomic execution
            try:
                with conn:
                    cur.execute(
                        """
                        INSERT INTO api_keys (key_hash, key_prefix, tier, credits, created_at, is_active, entitlement_tier, entitlement_expires_at)
                        VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                        """,
                        (k_hash, k_prefix, effective_tier, credits_to_grant, now_iso, effective_tier, exp_iso),
                    )
                    ent_id = f"ent_{secrets.token_hex(12)}"
                    cur.execute(
                        """
                        INSERT INTO customer_entitlements (entitlement_id, key_hash, tier, status, activated_at, expires_at)
                        VALUES (?, ?, ?, 'active', ?, ?)
                        """,
                        (ent_id, k_hash, effective_tier, now_iso, exp_iso)
                    )
                    lot_id = f"lot_{secrets.token_hex(12)}"
                    cur.execute(
                        """
                        INSERT INTO credit_lots (lot_id, key_hash, lot_type, credits_granted, credits_remaining, created_at, expires_at, status, invoice_id, tx_signature)
                        VALUES (?, ?, 'allowance', ?, ?, ?, ?, 'active', ?, ?)
                        """,
                        (lot_id, k_hash, credits_to_grant, credits_to_grant, now_iso, exp_iso, inv_id, sig)
                    )
                    cur.execute(
                        """
                        INSERT INTO credit_ledger_events (lot_id, key_hash, event_type, amount, balance_after, detail, created_at)
                        VALUES (?, ?, 'grant', ?, ?, ?, ?)
                        """,
                        (lot_id, k_hash, credits_to_grant, credits_to_grant, f"grant_{effective_tier}_{credits_to_grant}_credits", now_iso)
                    )
                    cur.execute(
                        """
                        INSERT INTO payment_redemptions (
                            tx_signature, key_hash, asset, amount_raw, tier,
                            credits_granted, redeemed_at, invoice_id, payer_wallet,
                            reference, slot, block_time
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            sig,
                            k_hash,
                            asset,
                            amount_raw,
                            effective_tier,
                            credits_to_grant,
                            now_iso,
                            inv_id,
                            payer,
                            reference or inv["reference"],
                            slot,
                            block_time,
                        ),
                    )
                    cur.execute(
                        """
                        UPDATE payment_invoices
                        SET status = 'fulfilled',
                            tx_signature = ?,
                            encrypted_key_envelope = ?,
                            fulfilled_at = ?
                        WHERE invoice_id = ? AND status = 'pending'
                        """,
                        (sig, encrypted_envelope, now_iso, inv_id),
                    )

                    if cur.rowcount == 0:
                        raise sqlite3.IntegrityError("Invoice fulfillment conflict")

                    self._cached_active_count = None

                return {
                    "status": "newly_minted",
                    "tx_signature": sig,
                    "api_key": raw_token,
                    "key_prefix": k_prefix,
                    "tier": effective_tier,
                    "credits": credits_to_grant,
                    "invoice_id": inv_id,
                    "message": f"Payment confirmed! Minted {credits_to_grant} credits.",
                }

            except sqlite3.IntegrityError:
                # Concurrent transaction won the race
                cur.execute(
                    """
                    SELECT p.tx_signature, p.tier, p.credits_granted, k.key_prefix, k.credits
                    FROM payment_redemptions p
                    JOIN api_keys k ON p.key_hash = k.key_hash
                    WHERE p.tx_signature = ? OR p.invoice_id = ?
                    """,
                    (sig, inv_id),
                )
                winner = cur.fetchone()
                return {
                    "status": "already_redeemed",
                    "tx_signature": winner["tx_signature"] if winner else sig,
                    "key_prefix": winner["key_prefix"] if winner else "",
                    "tier": winner["tier"] if winner else effective_tier,
                    "credits": winner["credits"] if winner else 0,
                    "invoice_id": inv_id,
                    "message": "Payment signature or invoice was already redeemed.",
                }

    def claim_invoice_credential(self, invoice_id: str, claim_secret: str) -> Dict[str, Any]:
        """
        Recovers a previously minted API key using the invoice's claim secret.
        Guarantees zero-knowledge: only the holder of the claim secret can decrypt the key envelope.
        Checks key active/revoked status; revoked keys cannot be recovered.
        """
        inv_id = invoice_id.strip()
        sec = claim_secret.strip()

        with self._lock, self.connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT invoice_id, status, claim_secret_hash, encrypted_key_envelope,
                       tier, credits, tx_signature, fulfilled_at
                FROM payment_invoices
                WHERE invoice_id = ?
                """,
                (inv_id,),
            )
            inv = cur.fetchone()
            if not inv:
                raise StorageError(f"Invoice '{inv_id}' not found.")

            if inv["status"] == "pending":
                raise StorageError("Invoice has not been fulfilled yet. Submit payment verification first.")

            if inv["status"] != "fulfilled":
                raise StorageError(f"Invoice status is '{inv['status']}'; credentials cannot be claimed.")

            # Validate claim secret hash using constant-time comparison
            provided_hash = hashlib.sha256(sec.encode("utf-8")).hexdigest()
            if not hmac.compare_digest(inv["claim_secret_hash"], provided_hash):
                raise StorageError("Invalid claim secret for invoice.")

            envelope = inv["encrypted_key_envelope"]
            if not envelope:
                raise StorageError(
                    "No recoverable key envelope exists for this invoice. "
                    "Credential may have already been purged or claimed."
                )

            # Check if key is still active in api_keys
            cur.execute(
                """
                SELECT k.key_prefix, k.credits, k.is_active
                FROM payment_redemptions p
                JOIN api_keys k ON p.key_hash = k.key_hash
                WHERE p.tx_signature = ?
                """,
                (inv["tx_signature"],),
            )
            key_row = cur.fetchone()
            if not key_row:
                raise StorageError("Associated credential record not found in database.")

            if key_row["is_active"] != 1:
                raise StorageError("Associated API key has been revoked by administrator.")

            # Decrypt envelope with claim secret
            try:
                raw_token = decrypt_key_envelope(envelope, sec)
            except Exception as e:
                raise StorageError(f"Credential decryption failed: {e}") from e

            return {
                "status": "recovered",
                "api_key": raw_token,
                "key_prefix": key_row["key_prefix"],
                "tier": inv["tier"],
                "credits": key_row["credits"],
                "invoice_id": inv_id,
                "message": "Credential recovered successfully.",
            }

    def expire_stale_invoices(self) -> int:
        """Marks pending invoices as 'expired' if their expires_at timestamp has passed."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock, self.connection() as conn:
            with conn:
                cur = conn.execute(
                    """
                    UPDATE payment_invoices
                    SET status = 'expired'
                    WHERE status = 'pending' AND expires_at < ?
                    """,
                    (now_iso,),
                )
                return cur.rowcount

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

    def get_payment_redemption(self, tx_signature: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves public redemption status for a transaction signature.
        Never returns plaintext raw API keys.
        """
        sig = tx_signature.strip()
        with self._lock, self.connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT p.tx_signature, p.asset, p.tier, p.credits_granted, p.redeemed_at,
                       p.invoice_id, p.payer_wallet, p.reference, p.slot, p.block_time,
                       k.key_prefix, k.credits, k.is_active
                FROM payment_redemptions p
                JOIN api_keys k ON p.key_hash = k.key_hash
                WHERE p.tx_signature = ?
                """,
                (sig,)
            )
            row = cur.fetchone()
            if not row:
                return None
            keys = row.keys()
            return {
                "tx_signature": row["tx_signature"],
                "asset": row["asset"],
                "tier": row["tier"],
                "credits_granted": row["credits_granted"],
                "remaining_credits": row["credits"],
                "key_prefix": row["key_prefix"],
                "is_active": bool(row["is_active"]),
                "redeemed_at": row["redeemed_at"],
                "invoice_id": row["invoice_id"] if "invoice_id" in keys else None,
                "payer_wallet": row["payer_wallet"] if "payer_wallet" in keys else None,
                "reference": row["reference"] if "reference" in keys else None,
                "slot": row["slot"] if "slot" in keys else None,
                "block_time": row["block_time"] if "block_time" in keys else None,
            }


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
                self._cached_active_count = None

    def log_audit_event(
        self,
        event_type: str,
        detail: str,
        ip_address: Optional[str] = None
    ) -> int:
        """Records an event in the audit_logs table for security forensics."""
        now_iso = datetime.now(timezone.utc).isoformat()
        entry_detail = detail
        if ip_address:
            entry_detail = f"{detail} [client_ip: {ip_address}]"

        with self._lock, self.connection() as conn:
            with conn:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO audit_logs (event_type, detail, created_at)
                    VALUES (?, ?, ?)
                    """,
                    (event_type, entry_detail, now_iso)
                )
                return cur.lastrowid

    def get_audit_logs(
        self,
        limit: int = 50,
        event_type: Optional[str] = None
    ) -> list[Dict[str, Any]]:
        """Retrieves recent audit log events."""
        with self._lock, self.connection() as conn:
            cur = conn.cursor()
            if event_type:
                cur.execute(
                    """
                    SELECT id, event_type, detail, created_at
                    FROM audit_logs
                    WHERE event_type = ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (event_type, limit)
                )
            else:
                cur.execute(
                    """
                    SELECT id, event_type, detail, created_at
                    FROM audit_logs
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (limit,)
                )
            return [dict(r) for r in cur.fetchall()]

    def revoke_key(self, key_prefix_or_hash: str) -> bool:
        """
        Deactivates an API key by prefix match or exact hash.
        Returns True if a key was revoked, False otherwise.
        """
        target = key_prefix_or_hash.strip()
        with self._lock, self.connection() as conn:
            with conn:
                cur = conn.cursor()
                cur.execute(
                    """
                    UPDATE api_keys
                    SET is_active = 0
                    WHERE key_hash = ? OR key_prefix LIKE ?
                    """,
                    (target, f"{target}%")
                )
                revoked = cur.rowcount > 0

        if revoked:
            with self._lock:
                self._cached_active_count = None
            self.log_audit_event("key_revocation", f"Revoked API key matching target: {target}")
        return revoked

    def check_health(self) -> bool:
        """
        Verifies SQLite connectivity and write capability.
        Returns True if operational, raises StorageError or returns False on failure.
        """
        try:
            with self._lock, self.connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT 1")
                row = cur.fetchone()
                return row is not None and row[0] == 1
        except Exception as e:
            raise StorageError(f"Database health check failed: {e!s}") from e

    def get_active_keys_count(self, max_age_seconds: float = 15.0) -> int:
        """
        Returns the count of active API keys in SQLite with thread-safe TTL caching.
        Prevents repeated disk queries during high-frequency Prometheus metrics scraping.
        Freshness guarantee: at most `max_age_seconds` old (default 15s), and invalidated
        immediately on local key creations, redemptions, or revocations.
        """
        now = time.monotonic()
        with self._lock:
            if max_age_seconds > 0 and self._cached_active_count is not None:
                if (now - self._cached_active_count_time) < max_age_seconds:
                    return self._cached_active_count

            with self.connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM api_keys WHERE is_active = 1")
                row = cur.fetchone()
                count = int(row[0]) if row else 0
                self._cached_active_count = count
                self._cached_active_count_time = now
                return count

    def backup(self, dest_path: Path) -> None:
        """
        Executes online SQLite zero-downtime backup to destination path.
        Uses Python sqlite3 connection backup API (equivalent to sqlite3 .backup).
        """
        dest_path = Path(dest_path).resolve()
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as src_conn:
            dest_conn = sqlite3.connect(str(dest_path))
            try:
                src_conn.backup(dest_conn)
            finally:
                dest_conn.close()

    def check_integrity(self) -> bool:
        """
        Executes PRAGMA integrity_check on the database.
        Returns True if 'ok', raises StorageError on corruption.
        """
        with self.connection() as conn:
            cur = conn.cursor()
            cur.execute("PRAGMA integrity_check;")
            rows = cur.fetchall()
            if rows and rows[0][0] == "ok":
                return True
            errors = [r[0] for r in rows]
            raise StorageError(f"Integrity check failed: {errors}")

    def refund_credit(
        self,
        key_hash: str,
        lot_id: str,
        request_id: Optional[str] = None,
        reason: str = "request_failed"
    ) -> bool:
        """
        Atomically restores a previously deducted credit to its original lot
        and logs a 'refund' audit event in the credit ledger.
        Ensures the accounting equation balances: granted + refunded - deducted - expired = remaining.
        """
        now_iso = self.get_now_iso()
        with self._lock, self.connection() as conn:
            with conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT lot_id, credits_remaining, status FROM credit_lots WHERE lot_id = ? AND key_hash = ?",
                    (lot_id, key_hash)
                )
                lot = cur.fetchone()
                if not lot:
                    return False

                new_lot_rem = lot["credits_remaining"] + 1
                cur.execute(
                    "UPDATE credit_lots SET credits_remaining = ?, status = 'active' WHERE lot_id = ?",
                    (new_lot_rem, lot_id)
                )
                cur.execute(
                    "UPDATE api_keys SET credits = credits + 1 WHERE key_hash = ?",
                    (key_hash,)
                )
                cur.execute("SELECT credits FROM api_keys WHERE key_hash = ?", (key_hash,))
                key_row = cur.fetchone()
                new_balance = key_row["credits"] if key_row else new_lot_rem

                cur.execute(
                    """
                    INSERT INTO credit_ledger_events (lot_id, key_hash, event_type, amount, balance_after, request_id, detail, created_at)
                    VALUES (?, ?, 'refund', 1, ?, ?, ?, ?)
                    """,
                    (lot_id, key_hash, new_balance, request_id, reason, now_iso)
                )
                return True

    def grant_topup(
        self,
        key_hash: str,
        credits: int,
        validity_days: int = 90,
        invoice_id: Optional[str] = None,
        tx_signature: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Grants a discrete, auditable top-up credit lot with a 90-day shelf life.
        Top-up credits survive Premium expiration, but can only be spent when an active entitlement exists.
        """
        lot_id = f"lot_topup_{secrets.token_hex(12)}"
        now = self.get_now()
        now_iso = now.isoformat()
        exp_iso = (now + timedelta(days=validity_days)).isoformat()

        with self._lock, self.connection() as conn:
            with conn:
                cur = conn.cursor()
                cur.execute("SELECT key_hash, credits, is_active FROM api_keys WHERE key_hash = ?", (key_hash,))
                key_row = cur.fetchone()
                if not key_row:
                    raise StorageError(f"API key hash '{key_hash}' not found.")
                if key_row["is_active"] != 1:
                    raise StorageError("Cannot grant top-up to a revoked API key.")

                cur.execute(
                    """
                    INSERT INTO credit_lots (lot_id, key_hash, lot_type, credits_granted, credits_remaining, created_at, expires_at, status, invoice_id, tx_signature)
                    VALUES (?, ?, 'topup', ?, ?, ?, ?, 'active', ?, ?)
                    """,
                    (lot_id, key_hash, credits, credits, now_iso, exp_iso, invoice_id, tx_signature)
                )
                cur.execute(
                    "UPDATE api_keys SET credits = credits + ? WHERE key_hash = ?",
                    (credits, key_hash)
                )
                new_balance = key_row["credits"] + credits
                cur.execute(
                    """
                    INSERT INTO credit_ledger_events (lot_id, key_hash, event_type, amount, balance_after, detail, created_at)
                    VALUES (?, ?, 'grant', ?, ?, ?, ?)
                    """,
                    (lot_id, key_hash, credits, new_balance, f"topup_{credits}_credits_{validity_days}d", now_iso)
                )
                return {
                    "lot_id": lot_id,
                    "key_hash": key_hash,
                    "credits_granted": credits,
                    "expires_at": exp_iso,
                    "total_credits": new_balance,
                }

    def renew_entitlement(
        self,
        key_hash: str,
        tier: str = "premium",
        credits: int = 10000,
        validity_days: int = 30,
        invoice_id: Optional[str] = None,
        tx_signature: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Renews or activates a 30-day Premium entitlement with 10,000 queries.
        Preserves unexpired top-up credits and makes them spendable again.
        """
        now = self.get_now()
        now_iso = now.isoformat()
        exp_iso = (now + timedelta(days=validity_days)).isoformat()
        ent_id = f"ent_{secrets.token_hex(12)}"
        lot_id = f"lot_allowance_{secrets.token_hex(12)}"

        with self._lock, self.connection() as conn:
            with conn:
                cur = conn.cursor()
                cur.execute("SELECT key_hash, credits, is_active FROM api_keys WHERE key_hash = ?", (key_hash,))
                key_row = cur.fetchone()
                if not key_row:
                    raise StorageError(f"API key hash '{key_hash}' not found.")
                if key_row["is_active"] != 1:
                    raise StorageError("Cannot renew a revoked API key.")

                # Mark any prior active entitlements as expired
                cur.execute(
                    "UPDATE customer_entitlements SET status = 'expired' WHERE key_hash = ? AND status = 'active'",
                    (key_hash,)
                )
                cur.execute(
                    """
                    INSERT INTO customer_entitlements (entitlement_id, key_hash, tier, status, activated_at, expires_at, renewed_at)
                    VALUES (?, ?, ?, 'active', ?, ?, ?)
                    """,
                    (ent_id, key_hash, tier, now_iso, exp_iso, now_iso)
                )
                cur.execute(
                    """
                    INSERT INTO credit_lots (lot_id, key_hash, lot_type, credits_granted, credits_remaining, created_at, expires_at, status, invoice_id, tx_signature)
                    VALUES (?, ?, 'allowance', ?, ?, ?, ?, 'active', ?, ?)
                    """,
                    (lot_id, key_hash, credits, credits, now_iso, exp_iso, invoice_id, tx_signature)
                )
                cur.execute(
                    """
                    UPDATE api_keys
                    SET tier = ?, entitlement_tier = ?, entitlement_expires_at = ?, credits = credits + ?
                    WHERE key_hash = ?
                    """,
                    (tier, tier, exp_iso, credits, key_hash)
                )
                new_balance = key_row["credits"] + credits
                cur.execute(
                    """
                    INSERT INTO credit_ledger_events (lot_id, key_hash, event_type, amount, balance_after, detail, created_at)
                    VALUES (?, ?, 'grant', ?, ?, ?, ?)
                    """,
                    (lot_id, key_hash, credits, new_balance, f"renew_{tier}_{credits}_queries_{validity_days}d", now_iso)
                )
                return {
                    "entitlement_id": ent_id,
                    "lot_id": lot_id,
                    "key_hash": key_hash,
                    "tier": tier,
                    "credits_granted": credits,
                    "expires_at": exp_iso,
                    "total_credits": new_balance,
                }

    def get_key_quota_details(self, raw_key: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves detailed quota and entitlement status including active credit lots and expirations.
        """
        k_hash = self.hash_key(raw_key)
        now_iso = self.get_now_iso()
        now = self.get_now()

        with self._lock, self.connection() as conn:
            with conn:
                self._expire_overdue_lots_and_entitlements(conn)
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT key_hash, key_prefix, tier, credits, is_active, created_at,
                           entitlement_tier, entitlement_expires_at
                    FROM api_keys
                    WHERE key_hash = ?
                    """,
                    (k_hash,)
                )
                key_row = cur.fetchone()
                if not key_row:
                    return None

                # Query latest entitlement
                cur.execute(
                    """
                    SELECT entitlement_id, tier, status, activated_at, expires_at
                    FROM customer_entitlements
                    WHERE key_hash = ?
                    ORDER BY activated_at DESC LIMIT 1
                    """,
                    (k_hash,)
                )
                ent_row = cur.fetchone()
                ent_status = "active"
                ent_tier = key_row["tier"]
                ent_expires_at = None
                days_remaining = None

                if ent_row:
                    ent_tier = ent_row["tier"]
                    ent_expires_at = ent_row["expires_at"]
                    if ent_row["status"] == "active" and ent_expires_at:
                        if ent_expires_at < now_iso:
                            ent_status = "expired"
                            days_remaining = 0.0
                        else:
                            exp_dt = datetime.fromisoformat(ent_expires_at)
                            days_remaining = max(0.0, round((exp_dt - now).total_seconds() / 86400, 2))
                    elif ent_row["status"] == "active" and not ent_expires_at:
                        ent_status = "active"
                        days_remaining = None
                    else:
                        ent_status = ent_row["status"]
                        days_remaining = 0.0
                elif key_row["tier"] in ("unlimited", "premium", "tier_unlimited", "tier_premium"):
                    ent_status = "expired"
                    days_remaining = 0.0

                # Query active credit lots
                cur.execute(
                    """
                    SELECT lot_id, lot_type, credits_granted, credits_remaining, created_at, expires_at, status
                    FROM credit_lots
                    WHERE key_hash = ? AND status = 'active'
                    ORDER BY
                      CASE WHEN expires_at IS NULL THEN 1 ELSE 0 END ASC,
                      expires_at ASC,
                      created_at ASC
                    """,
                    (k_hash,)
                )
                lots = [dict(r) for r in cur.fetchall()]

                return {
                    "key_prefix": key_row["key_prefix"],
                    "key_hash": k_hash,
                    "tier": key_row["tier"],
                    "credits_remaining": key_row["credits"],
                    "is_active": bool(key_row["is_active"]),
                    "created_at": key_row["created_at"],
                    "entitlement": {
                        "tier": ent_tier,
                        "status": ent_status,
                        "expires_at": ent_expires_at,
                        "days_remaining": days_remaining,
                    },
                    "credit_lots": lots,
                }

    def get_key_lots(self, key_hash: str) -> list[Dict[str, Any]]:
        """Retrieves all credit lots (active and inactive) for a key hash."""
        with self._lock, self.connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT lot_id, key_hash, lot_type, credits_granted, credits_remaining, created_at, expires_at, status, invoice_id, tx_signature
                FROM credit_lots
                WHERE key_hash = ?
                ORDER BY created_at DESC
                """,
                (key_hash,)
            )
            return [dict(r) for r in cur.fetchall()]

    def get_credit_ledger(self, key_hash: Optional[str] = None, limit: int = 50) -> list[Dict[str, Any]]:
        """Retrieves audit trail events from credit_ledger_events."""
        with self._lock, self.connection() as conn:
            cur = conn.cursor()
            if key_hash:
                cur.execute(
                    """
                    SELECT event_id, lot_id, key_hash, event_type, amount, balance_after, request_id, detail, created_at
                    FROM credit_ledger_events
                    WHERE key_hash = ?
                    ORDER BY event_id DESC
                    LIMIT ?
                    """,
                    (key_hash, limit)
                )
            else:
                cur.execute(
                    """
                    SELECT event_id, lot_id, key_hash, event_type, amount, balance_after, request_id, detail, created_at
                    FROM credit_ledger_events
                    ORDER BY event_id DESC
                    LIMIT ?
                    """,
                    (limit,)
                )
            return [dict(r) for r in cur.fetchall()]

    def verify_ledger_balance(self, key_hash: str) -> Dict[str, Any]:
        """
        Mathematically verifies that:
        granted + refunded - deducted - expired == current active remaining balance
        """
        with self._lock, self.connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT event_type, SUM(amount) as total
                FROM credit_ledger_events
                WHERE key_hash = ?
                GROUP BY event_type
                """,
                (key_hash,)
            )
            event_sums = {row["event_type"]: int(row["total"]) for row in cur.fetchall()}
            total_granted = event_sums.get("grant", 0)
            total_refunded = event_sums.get("refund", 0)
            total_deducted = event_sums.get("deduct", 0)
            total_expired = event_sums.get("expire", 0)

            cur.execute(
                """
                SELECT SUM(credits_remaining) as total_active
                FROM credit_lots
                WHERE key_hash = ? AND status = 'active'
                """,
                (key_hash,)
            )
            row = cur.fetchone()
            actual_active = int(row["total_active"]) if row and row["total_active"] is not None else 0

            cur.execute("SELECT credits FROM api_keys WHERE key_hash = ?", (key_hash,))
            key_row = cur.fetchone()
            key_credits = int(key_row["credits"]) if key_row else 0

            expected_balance = total_granted + total_refunded - total_deducted - total_expired
            is_balanced = (expected_balance == actual_active == key_credits)

            return {
                "balanced": is_balanced,
                "expected_balance": expected_balance,
                "actual_lot_balance": actual_active,
                "api_key_balance": key_credits,
                "breakdown": {
                    "granted": total_granted,
                    "refunded": total_refunded,
                    "deducted": total_deducted,
                    "expired": total_expired,
                }
            }
