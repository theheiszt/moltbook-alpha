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
import json
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List

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


def normalize_challenge_answer(ans: str) -> str:
    """
    Normalizes challenge answer string for robust deterministic comparison.
    Converts numbers to canonical two-decimal format (e.g. 46, 46.0, 46.00 -> '46.00').
    Trims whitespace and lowercases string values.
    """
    cleaned = str(ans).strip().lower()
    try:
        val = float(cleaned)
        return f"{val:.2f}"
    except (ValueError, TypeError):
        return cleaned


class StorageManager:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
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

                    CREATE TABLE IF NOT EXISTS webhook_subscriptions (
                        subscription_id TEXT PRIMARY KEY,
                        target_url TEXT NOT NULL,
                        secret_token TEXT NOT NULL,
                        subscribed_events TEXT NOT NULL,
                        min_severity TEXT NOT NULL DEFAULT 'HIGH',
                        is_active INTEGER NOT NULL DEFAULT 1,
                        created_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS unmatched_payments (
                        unmatched_id TEXT PRIMARY KEY,
                        rail TEXT NOT NULL DEFAULT 'solana',
                        tx_signature TEXT NOT NULL UNIQUE,
                        payer_wallet TEXT NOT NULL,
                        asset TEXT NOT NULL,
                        amount_raw INTEGER NOT NULL,
                        expected_amount_raw INTEGER,
                        reason TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'HELD',
                        refund_tx_sig TEXT,
                        refunded_amount_raw INTEGER,
                        created_at TEXT NOT NULL,
                        refunded_at TEXT
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

                    CREATE TABLE IF NOT EXISTS rate_limit_tokens (
                        key TEXT PRIMARY KEY,
                        tokens REAL NOT NULL,
                        last_refill REAL NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS rate_limit_concurrency (
                        slot_id TEXT PRIMARY KEY,
                        key TEXT NOT NULL,
                        acquired_at REAL NOT NULL,
                        expires_at REAL NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_concurrency_key ON rate_limit_concurrency(key);
                    CREATE INDEX IF NOT EXISTS idx_concurrency_exp ON rate_limit_concurrency(expires_at);

                    CREATE TABLE IF NOT EXISTS quota_reservations (
                        reservation_id TEXT PRIMARY KEY,
                        key_hash TEXT NOT NULL,
                        idempotency_key TEXT,
                        lot_id TEXT NOT NULL,
                        credits INTEGER NOT NULL DEFAULT 1,
                        status TEXT NOT NULL DEFAULT 'reserved',
                        request_id TEXT,
                        created_at TEXT NOT NULL,
                        expires_at TEXT NOT NULL,
                        settled_at TEXT,
                        released_at TEXT,
                        release_reason TEXT,
                        response_cache TEXT,
                        FOREIGN KEY(key_hash) REFERENCES api_keys(key_hash),
                        FOREIGN KEY(lot_id) REFERENCES credit_lots(lot_id)
                    );
                    CREATE INDEX IF NOT EXISTS idx_reservations_key ON quota_reservations(key_hash);
                    CREATE INDEX IF NOT EXISTS idx_reservations_status ON quota_reservations(status);
                    CREATE INDEX IF NOT EXISTS idx_reservations_idemp ON quota_reservations(key_hash, idempotency_key);
                    CREATE INDEX IF NOT EXISTS idx_reservations_expires ON quota_reservations(expires_at);
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_active_idemp ON quota_reservations(key_hash, idempotency_key) WHERE idempotency_key IS NOT NULL AND status IN ('reserved', 'settled');

                    CREATE TABLE IF NOT EXISTS quota_threshold_alerts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        key_hash TEXT NOT NULL,
                        threshold REAL NOT NULL,
                        triggered_at TEXT NOT NULL,
                        UNIQUE(key_hash, threshold),
                        FOREIGN KEY(key_hash) REFERENCES api_keys(key_hash)
                    );
                    CREATE INDEX IF NOT EXISTS idx_threshold_alerts_key ON quota_threshold_alerts(key_hash);

                    CREATE TABLE IF NOT EXISTS verification_challenges (
                        challenge_id TEXT PRIMARY KEY,
                        challenge_type TEXT NOT NULL,
                        challenge_text TEXT NOT NULL,
                        expected_answer_hash TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'pending',
                        attempts INTEGER NOT NULL DEFAULT 0,
                        expires_at TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        verified_at TEXT,
                        proof_token TEXT
                    );
                    CREATE INDEX IF NOT EXISTS idx_challenges_status ON verification_challenges(status);
                    CREATE INDEX IF NOT EXISTS idx_challenges_expires ON verification_challenges(expires_at);

                    CREATE TABLE IF NOT EXISTS funnel_events (
                        event_id TEXT PRIMARY KEY,
                        event_name TEXT NOT NULL,
                        timestamp_utc TEXT NOT NULL,
                        properties_json TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_funnel_events_name_time ON funnel_events(event_name, timestamp_utc);

                    CREATE TABLE IF NOT EXISTS admin_users (
                        username TEXT PRIMARY KEY,
                        password_hash TEXT NOT NULL,
                        salt TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS admin_sessions (
                        token TEXT PRIMARY KEY,
                        username TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        expires_at TEXT NOT NULL,
                        FOREIGN KEY(username) REFERENCES admin_users(username)
                    );
                    CREATE INDEX IF NOT EXISTS idx_admin_sessions_exp ON admin_sessions(expires_at);
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
                if "rail" not in inv_cols:
                    cur.execute("ALTER TABLE payment_invoices ADD COLUMN rail TEXT DEFAULT 'solana'")
                if "amount_raw_text" not in inv_cols:
                    cur.execute("ALTER TABLE payment_invoices ADD COLUMN amount_raw_text TEXT")


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
                conn.execute("CREATE INDEX IF NOT EXISTS idx_unmatched_payer ON unmatched_payments(payer_wallet)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_unmatched_status ON unmatched_payments(status)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_webhooks_active ON webhook_subscriptions(is_active)")

                # Seed initial ADMIN credentials if not present
                cur.execute("SELECT username FROM admin_users WHERE username = 'ADMIN'")
                if not cur.fetchone():
                    salt = secrets.token_hex(16)
                    default_pw = "Neverwinter#7789"
                    pw_hash = hashlib.pbkdf2_hmac("sha256", default_pw.encode("utf-8"), salt.encode("utf-8"), 100_000).hex()
                    now_iso = datetime.now(timezone.utc).isoformat()
                    cur.execute(
                        "INSERT INTO admin_users (username, password_hash, salt, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                        ("ADMIN", pw_hash, salt, now_iso, now_iso)
                    )

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

    def _authenticate_and_deduct_conn(
        self,
        conn: sqlite3.Connection,
        k_hash: str,
        request_id: Optional[str] = None,
    ) -> Tuple[Optional[Dict[str, Any]], str]:
        self._expire_overdue_lots_and_entitlements(conn)
        self._reap_expired_reservations_conn(conn)

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
        self._check_and_record_quota_thresholds_conn(conn, k_hash)

        cur.execute(
            "SELECT COUNT(*) as deduct_count FROM credit_ledger_events WHERE key_hash = ? AND event_type = 'deduct'",
            (k_hash,),
        )
        d_row = cur.fetchone()
        if d_row and d_row["deduct_count"] == 1:
            self._record_funnel_event_conn(
                conn,
                "first_query",
                {"key_hash": k_hash, "tier": tier},
            )

        if new_total == 0:
            self._record_funnel_event_conn(
                conn,
                "quota_exhausted",
                {"key_hash": k_hash, "tier": tier},
            )

        return {
            "key_prefix": row["key_prefix"],
            "tier": tier,
            "credits": new_total,
            "key_hash": k_hash,
            "lot_id": lot_id,
            "request_id": request_id,
        }, "ok"

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
                return self._authenticate_and_deduct_conn(conn, k_hash, request_id=request_id)

    def reserve_quota(
        self,
        raw_key: str,
        idempotency_key: Optional[str] = None,
        request_id: Optional[str] = None,
        ttl_seconds: int = 60,
    ) -> Tuple[Optional[Dict[str, Any]], str]:
        """
        Atomically checks remaining quota and reserves 1 credit against the earliest-expiring
        active credit lot (EDF).
        Supports idempotency: If an idempotency_key is provided:
          - If a settled reservation exists, returns (cached_info, "idempotent_replay") without burning credits.
          - If an active in-flight reservation exists, returns (info, "in_flight").
        Returns:
            Tuple[Optional[Dict[str, Any]], str]: (reservation_record, status_code)
            status_code: 'ok', 'idempotent_replay', 'in_flight', 'invalid', 'revoked', 'exhausted', 'entitlement_expired'
        """
        if not raw_key:
            return None, "invalid"

        k_hash = self.hash_key(raw_key)
        now = self.get_now()
        now_iso = now.isoformat()
        expires_at_iso = (now + timedelta(seconds=ttl_seconds)).isoformat()
        clean_idemp = idempotency_key.strip() if idempotency_key else None

        with self._lock:
            # Check existing reservations for idempotency replay or in-flight requests
            if clean_idemp:
                with self.connection() as conn:
                    with conn:
                        self._reap_expired_reservations_conn(conn)
                        cur = conn.cursor()
                        cur.execute(
                            """
                            SELECT reservation_id, lot_id, status, response_cache, created_at, expires_at
                            FROM quota_reservations
                            WHERE key_hash = ? AND idempotency_key = ?
                            ORDER BY created_at DESC LIMIT 1
                            """,
                            (k_hash, clean_idemp)
                        )
                        existing_res = cur.fetchone()
                        if existing_res:
                            st = existing_res["status"]
                            if st == "settled":
                                cached_payload = None
                                if existing_res["response_cache"]:
                                    try:
                                        cached_payload = json.loads(existing_res["response_cache"])
                                    except Exception:
                                        pass
                                return {
                                    "reservation_id": existing_res["reservation_id"],
                                    "key_hash": k_hash,
                                    "lot_id": existing_res["lot_id"],
                                    "idempotency_key": clean_idemp,
                                    "cached_response": cached_payload,
                                }, "idempotent_replay"
                            elif st == "reserved" and existing_res["expires_at"] > now_iso:
                                return {
                                    "reservation_id": existing_res["reservation_id"],
                                    "key_hash": k_hash,
                                    "lot_id": existing_res["lot_id"],
                                    "idempotency_key": clean_idemp,
                                }, "in_flight"

            # Delegate validation and atomic EDF deduction to authenticate_and_deduct
            user_info, state = self.authenticate_and_deduct(raw_key, request_id=request_id)
            if state != "ok":
                return user_info, state

            tier = user_info.get("tier")
            if tier in ("admin",):
                return {
                    "reservation_id": f"res_admin_{secrets.token_hex(8)}",
                    "idempotency_key": clean_idemp,
                    **user_info,
                }, "ok"

            reservation_id = f"res_{secrets.token_hex(12)}"
            lot_id = user_info.get("lot_id")

            try:
                with self.connection() as conn:
                    with conn:
                        cur = conn.cursor()
                        cur.execute(
                            """
                            INSERT INTO quota_reservations (
                                reservation_id, key_hash, idempotency_key, lot_id, credits,
                                status, request_id, created_at, expires_at
                            ) VALUES (?, ?, ?, ?, 1, 'reserved', ?, ?, ?)
                            """,
                            (reservation_id, k_hash, clean_idemp, lot_id, request_id, now_iso, expires_at_iso)
                        )
            except sqlite3.IntegrityError:
                # Concurrently reserved by another process with same (key_hash, idempotency_key)
                if lot_id:
                    self.refund_credit(k_hash, lot_id, request_id=request_id, reason="concurrent_idempotency_conflict")
                return {
                    "key_hash": k_hash,
                    "idempotency_key": clean_idemp,
                }, "in_flight"

            return {
                "reservation_id": reservation_id,
                "idempotency_key": clean_idemp,
                **user_info,
            }, "ok"

    def settle_quota(self, reservation_id: str, response_payload: Optional[Dict[str, Any]] = None) -> bool:
        """
        Settles an active quota reservation upon successful endpoint execution.
        Saves optional cached response payload for idempotency replay and evaluates warning thresholds.
        """
        now_iso = self.get_now_iso()
        cache_str = json.dumps(response_payload) if response_payload is not None else None

        with self._lock, self.connection() as conn:
            with conn:
                cur = conn.cursor()
                cur.execute(
                    """
                    UPDATE quota_reservations
                    SET status = 'settled', settled_at = ?, response_cache = ?
                    WHERE reservation_id = ? AND status = 'reserved'
                    """,
                    (now_iso, cache_str, reservation_id)
                )
                settled = cur.rowcount > 0
                if settled:
                    cur.execute("SELECT key_hash FROM quota_reservations WHERE reservation_id = ?", (reservation_id,))
                    row = cur.fetchone()
                    if row:
                        self._check_and_record_quota_thresholds_conn(conn, row["key_hash"])
                return settled

    def release_quota(self, reservation_id: str, reason: str = "") -> bool:
        """
        Releases an active quota reservation, restoring the credit back to the credit lot
        and API key balance. Used on request failure, cancellation, or timeout.
        """
        now_iso = self.get_now_iso()

        with self._lock, self.connection() as conn:
            with conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT reservation_id, key_hash, lot_id, credits, status, request_id FROM quota_reservations WHERE reservation_id = ?",
                    (reservation_id,)
                )
                res = cur.fetchone()
                if not res or res["status"] != "reserved":
                    return False

                k_hash = res["key_hash"]
                lot_id = res["lot_id"]
                credits_to_restore = res["credits"]
                req_id = res["request_id"]

                cur.execute(
                    """
                    UPDATE quota_reservations
                    SET status = 'released', released_at = ?, release_reason = ?
                    WHERE reservation_id = ? AND status = 'reserved'
                    """,
                    (now_iso, reason or "released_on_error", reservation_id)
                )
                if cur.rowcount == 0:
                    return False

                # Restore lot
                cur.execute(
                    """
                    UPDATE credit_lots
                    SET credits_remaining = credits_remaining + ?, status = 'active'
                    WHERE lot_id = ?
                    """,
                    (credits_to_restore, lot_id)
                )

                # Restore api_keys
                cur.execute(
                    "UPDATE api_keys SET credits = credits + ? WHERE key_hash = ?",
                    (credits_to_restore, k_hash)
                )

                cur.execute("SELECT credits FROM api_keys WHERE key_hash = ?", (k_hash,))
                new_bal = cur.fetchone()["credits"]

                # Insert refund event into ledger so balance holds
                cur.execute(
                    """
                    INSERT INTO credit_ledger_events (lot_id, key_hash, event_type, amount, balance_after, request_id, detail, created_at)
                    VALUES (?, ?, 'refund', ?, ?, ?, ?, ?)
                    """,
                    (lot_id, k_hash, credits_to_restore, new_bal, req_id, f"release_reservation_{reservation_id[:8]}_{reason}", now_iso)
                )
                return True

    def reap_expired_reservations(self) -> int:
        """
        Reaps all abandoned or timed-out reservations where expires_at < now.
        Restores credits safely to the active lot and API key.
        """
        with self._lock, self.connection() as conn:
            with conn:
                return self._reap_expired_reservations_conn(conn)

    def _reap_expired_reservations_conn(self, conn: sqlite3.Connection) -> int:
        now_iso = self.get_now_iso()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT reservation_id, key_hash, lot_id, credits, request_id
            FROM quota_reservations
            WHERE status = 'reserved' AND expires_at < ?
            """,
            (now_iso,)
        )
        expired_res = cur.fetchall()
        reaped_count = 0

        for r in expired_res:
            res_id = r["reservation_id"]
            k_hash = r["key_hash"]
            lot_id = r["lot_id"]
            creds = r["credits"]
            req_id = r["request_id"]

            cur.execute(
                """
                UPDATE quota_reservations
                SET status = 'expired', released_at = ?, release_reason = 'reservation_ttl_expired'
                WHERE reservation_id = ? AND status = 'reserved'
                """,
                (now_iso, res_id)
            )
            if cur.rowcount > 0:
                cur.execute(
                    "UPDATE credit_lots SET credits_remaining = credits_remaining + ?, status = 'active' WHERE lot_id = ?",
                    (creds, lot_id)
                )
                cur.execute(
                    "UPDATE api_keys SET credits = credits + ? WHERE key_hash = ?",
                    (creds, k_hash)
                )
                cur.execute("SELECT credits FROM api_keys WHERE key_hash = ?", (k_hash,))
                new_bal = cur.fetchone()["credits"]
                cur.execute(
                    """
                    INSERT INTO credit_ledger_events (lot_id, key_hash, event_type, amount, balance_after, request_id, detail, created_at)
                    VALUES (?, ?, 'refund', ?, ?, ?, 'reap_expired_reservation', ?)
                    """,
                    (lot_id, k_hash, creds, new_bal, req_id, now_iso)
                )
                reaped_count += 1

        return reaped_count

    def _check_and_record_quota_thresholds_conn(self, conn: sqlite3.Connection, key_hash: str) -> Optional[float]:
        """
        Evaluates consumption percentage against (0.50, 0.80, 0.90, 0.95).
        Emits and records deduplicated threshold alerts in quota_threshold_alerts.
        Returns the highest newly crossed threshold or None.
        """
        now_iso = self.get_now_iso()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT SUM(credits_granted) as total_granted, SUM(credits_remaining) as total_remaining
            FROM credit_lots
            WHERE key_hash = ? AND status IN ('active', 'exhausted')
            """,
            (key_hash,)
        )
        row = cur.fetchone()
        if not row or not row["total_granted"]:
            return None

        total_granted = int(row["total_granted"])
        total_remaining = int(row["total_remaining"] or 0)
        total_consumed = total_granted - total_remaining

        if total_granted <= 0:
            return None

        ratio = total_consumed / float(total_granted)
        thresholds = (0.50, 0.80, 0.90, 0.95)
        newly_crossed = None

        for th in thresholds:
            if ratio >= th:
                cur.execute(
                    "SELECT id FROM quota_threshold_alerts WHERE key_hash = ? AND threshold = ?",
                    (key_hash, th)
                )
                if not cur.fetchone():
                    cur.execute(
                        "INSERT INTO quota_threshold_alerts (key_hash, threshold, triggered_at) VALUES (?, ?, ?)",
                        (key_hash, th, now_iso)
                    )
                    newly_crossed = th
                    cur.execute(
                        "INSERT INTO audit_logs (event_type, detail, created_at) VALUES (?, ?, ?)",
                        ("quota_warning_threshold_crossed", f"Key {key_hash[:12]} crossed {int(th*100)}% quota consumption ({total_consumed}/{total_granted})", now_iso)
                    )
                    if th == 0.80:
                        self._record_funnel_event_conn(
                            conn,
                            "quota_warning",
                            {"key_hash": key_hash, "threshold": 0.80},
                        )

        return newly_crossed

    def get_usage_and_threshold_status(self, raw_key_or_hash: str) -> Dict[str, Any]:
        """
        Returns full usage visibility and threshold alerts for an API key.
        """
        k_hash = self.hash_key(raw_key_or_hash) if not (len(raw_key_or_hash) == 64 and all(c in "0123456789abcdef" for c in raw_key_or_hash.lower())) else raw_key_or_hash

        with self._lock, self.connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT SUM(credits_granted) as total_granted, SUM(credits_remaining) as total_remaining
                FROM credit_lots
                WHERE key_hash = ? AND status IN ('active', 'exhausted')
                """,
                (k_hash,)
            )
            row = cur.fetchone()
            total_granted = int(row["total_granted"]) if row and row["total_granted"] else 0
            total_remaining = int(row["total_remaining"]) if row and row["total_remaining"] is not None else 0
            total_consumed = max(0, total_granted - total_remaining)
            percent = (total_consumed / float(total_granted) * 100.0) if total_granted > 0 else 0.0

            cur.execute(
                "SELECT threshold, triggered_at FROM quota_threshold_alerts WHERE key_hash = ? ORDER BY threshold ASC",
                (k_hash,)
            )
            alerts = [{"threshold": r["threshold"], "triggered_at": r["triggered_at"]} for r in cur.fetchall()]
            highest = alerts[-1]["threshold"] if alerts else None

            return {
                "quota_limit": total_granted,
                "consumed": total_consumed,
                "remaining": total_remaining,
                "percent_consumed": round(percent, 1),
                "warning_threshold_crossed": highest,
                "active_alerts": alerts,
                "configured_thresholds": [0.50, 0.80, 0.90, 0.95],
            }

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
                        if effective_tier in ("topup", "credit_topup") or effective_tier.startswith("topup"):
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
        rail: str = "solana",
    ) -> Tuple[Dict[str, Any], str, str]:
        """
        Creates a stateful payment invoice with a unique Solana Pay reference address
        and a client-held claim secret for zero-knowledge credential recovery.
        Returns: (invoice_dict, claim_secret, reference)
        """
        invoice_id = f"inv_{secrets.token_hex(12)}"
        claim_secret = f"sec_{secrets.token_hex(20)}"
        if rail == "nano":
            tag_offset = int(hashlib.sha256(invoice_id.encode()).hexdigest()[:8], 16) % 1_000_000
            reference = f"nano_ref_{tag_offset}_{secrets.token_hex(4)}"
        else:
            reference = generate_solana_reference()
        claim_secret_hash = hashlib.sha256(claim_secret.strip().encode("utf-8")).hexdigest()

        now = self.get_now()
        created_at_iso = now.isoformat()
        expires_at_iso = (now + timedelta(seconds=expiry_seconds)).isoformat()
        raw_text = str(amount_raw)
        safe_amount_raw = int(amount_raw) if int(amount_raw) < (2**62) else 0

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
                        target_key_hash, rail, amount_raw_text
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        invoice_id,
                        reference,
                        effective_tier,
                        credits,
                        asset,
                        safe_amount_raw,
                        recipient,
                        cluster,
                        claim_secret_hash,
                        created_at_iso,
                        expires_at_iso,
                        target_key_hash,
                        rail,
                        raw_text,
                    ),
                )

                self._record_funnel_event_conn(
                    conn,
                    "invoice_created",
                    {
                        "invoice_id": invoice_id,
                        "tier": effective_tier,
                        "rail": rail,
                        "asset": asset,
                        "amount_raw": safe_amount_raw,
                        "credits": credits,
                    },
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
            "rail": rail,
        }
        return invoice_record, claim_secret, reference

    def get_invoice(self, invoice_id: str) -> Optional[Dict[str, Any]]:
        with self._lock, self.connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT invoice_id, reference, tier, credits, asset, amount_raw,
                       recipient, cluster, status, claim_secret_hash, encrypted_key_envelope,
                       tx_signature, created_at, expires_at, fulfilled_at, target_key_hash,
                       rail, amount_raw_text
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
                       tx_signature, created_at, expires_at, fulfilled_at, target_key_hash,
                       rail, amount_raw_text
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
        safe_amount_raw = int(amount_raw) if int(amount_raw) < (2**62) else 0

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
                        if effective_tier in ("topup", "credit_topup") or effective_tier.startswith("topup"):
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
                                safe_amount_raw,
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

                        self._record_funnel_event_conn(
                            conn,
                            "payment_verified",
                            {
                                "invoice_id": inv_id,
                                "tier": effective_tier,
                                "asset": asset,
                                "payer_wallet": payer,
                                "credits_granted": credits_to_grant,
                                "is_topup": True,
                            },
                        )
                        if effective_tier in ("topup", "credit_topup") or effective_tier.startswith("topup"):
                            self._record_funnel_event_conn(
                                conn,
                                "topup_purchased",
                                {
                                    "invoice_id": inv_id,
                                    "tier": effective_tier,
                                    "asset": asset,
                                    "credits_granted": credits_to_grant,
                                    "key_hash": k_hash,
                                },
                            )

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

                    self._record_funnel_event_conn(
                        conn,
                        "payment_verified",
                        {
                            "invoice_id": inv_id,
                            "tier": effective_tier,
                            "asset": asset,
                            "payer_wallet": payer,
                            "credits_granted": credits_to_grant,
                            "is_topup": False,
                        },
                    )
                    self._record_funnel_event_conn(
                        conn,
                        "key_delivered",
                        {
                            "invoice_id": inv_id,
                            "tier": effective_tier,
                            "delivery_method": "immediate_fulfillment",
                        },
                    )

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

            with conn:
                self._record_funnel_event_conn(
                    conn,
                    "key_delivered",
                    {
                        "invoice_id": inv_id,
                        "tier": inv["tier"],
                        "delivery_method": "claim_secret_recovery",
                    },
                )

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
                SELECT p.tx_signature, p.key_hash, p.asset, p.tier, p.credits_granted, p.redeemed_at,
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
                "key_hash": row["key_hash"],
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

    def create_verification_challenge(
        self,
        challenge_type: str = "arithmetic",
        expiry_seconds: int = 120,
        challenge_text: Optional[str] = None,
        expected_answer: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Creates a new verification challenge with a short TTL (default: 120s).
        Stores a secure SHA-256 hash of the normalized answer.
        Never persists or returns the plaintext solution.
        """
        challenge_id = f"ch_{secrets.token_hex(12)}"
        now = self.get_now()
        created_at_iso = now.isoformat()
        expires_at_iso = (now + timedelta(seconds=expiry_seconds)).isoformat()

        if challenge_text is None or expected_answer is None:
            a = secrets.randbelow(40) + 10
            b = secrets.randbelow(30) + 5
            op = secrets.choice(["+", "-"])
            if op == "+":
                ans_val = a + b
                text = f"Calculate {a} plus {b} to verify."
            else:
                if a < b:
                    a, b = b, a
                ans_val = a - b
                text = f"Calculate {a} minus {b} to verify."
            expected_answer = f"{ans_val:.2f}"
            challenge_text = text

        norm_ans = normalize_challenge_answer(str(expected_answer))
        ans_hash = hashlib.sha256(norm_ans.encode("utf-8")).hexdigest()

        with self._lock, self.connection() as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO verification_challenges (
                        challenge_id, challenge_type, challenge_text, expected_answer_hash,
                        status, attempts, expires_at, created_at
                    ) VALUES (?, ?, ?, ?, 'pending', 0, ?, ?)
                    """,
                    (challenge_id, challenge_type, challenge_text, ans_hash, expires_at_iso, created_at_iso)
                )

        return {
            "challenge_id": challenge_id,
            "challenge_type": challenge_type,
            "challenge_text": challenge_text,
            "status": "pending",
            "expires_at": expires_at_iso,
            "created_at": created_at_iso,
        }

    def get_verification_challenge(self, challenge_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves verification challenge state. Excludes expected answer and hash.
        Checks TTL lazily.
        """
        with self._lock, self.connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT challenge_id, challenge_type, challenge_text, status,
                       attempts, expires_at, created_at, verified_at, proof_token
                FROM verification_challenges
                WHERE challenge_id = ?
                """,
                (challenge_id.strip(),)
            )
            row = cur.fetchone()
            if not row:
                return None
            res = dict(row)
            now_iso = self.get_now_iso()
            if res["status"] == "pending" and now_iso > res["expires_at"]:
                res["status"] = "expired"
            return res

    def verify_challenge_answer(self, challenge_id: str, submitted_answer: str) -> Dict[str, Any]:
        """
        Atomically evaluates challenge answer against the state machine:
        - If not found -> state: 'not_found'
        - If expired or past TTL -> state: 'expired'
        - If already solved -> state: 'already_answered' with existing proof_token
        - If already consumed -> state: 'consumed'
        - If pending and answer is incorrect -> transitions to 'consumed', state: 'wrong_answer'
        - If pending and answer is correct -> transitions to 'solved', state: 'solved' with new proof_token
        """
        clean_cid = challenge_id.strip()
        now_iso = self.get_now_iso()

        with self._lock, self.connection() as conn:
            with conn:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT challenge_id, challenge_type, challenge_text, expected_answer_hash,
                           status, attempts, expires_at, created_at, verified_at, proof_token
                    FROM verification_challenges
                    WHERE challenge_id = ?
                    """,
                    (clean_cid,)
                )
                row = cur.fetchone()
                if not row:
                    return {"state": "not_found", "challenge_id": clean_cid}

                # Check expiry
                if row["status"] == "expired" or now_iso > row["expires_at"]:
                    if row["status"] == "pending":
                        cur.execute("UPDATE verification_challenges SET status = 'expired' WHERE challenge_id = ?", (clean_cid,))
                    return {
                        "state": "expired",
                        "challenge_id": clean_cid,
                        "expires_at": row["expires_at"],
                    }

                # Check already answered
                if row["status"] == "solved":
                    return {
                        "state": "already_answered",
                        "challenge_id": clean_cid,
                        "proof_token": row["proof_token"],
                        "verified_at": row["verified_at"],
                    }

                # Check already consumed
                if row["status"] == "consumed":
                    return {
                        "state": "consumed",
                        "challenge_id": clean_cid,
                    }

                # Challenge is pending: verify answer
                norm_sub = normalize_challenge_answer(submitted_answer)
                sub_hash = hashlib.sha256(norm_sub.encode("utf-8")).hexdigest()
                is_correct = hmac.compare_digest(row["expected_answer_hash"], sub_hash)

                if not is_correct:
                    cur.execute(
                        """
                        UPDATE verification_challenges
                        SET status = 'consumed', attempts = attempts + 1
                        WHERE challenge_id = ? AND status = 'pending'
                        """,
                        (clean_cid,)
                    )
                    return {
                        "state": "wrong_answer",
                        "challenge_id": clean_cid,
                    }

                proof_token = f"proof_{secrets.token_hex(16)}"
                cur.execute(
                    """
                    UPDATE verification_challenges
                    SET status = 'solved', attempts = attempts + 1, verified_at = ?, proof_token = ?
                    WHERE challenge_id = ? AND status = 'pending'
                    """,
                    (now_iso, proof_token, clean_cid)
                )
                if cur.rowcount == 0:
                    cur.execute(
                        "SELECT status, verified_at, proof_token FROM verification_challenges WHERE challenge_id = ?",
                        (clean_cid,)
                    )
                    latest = cur.fetchone()
                    if latest and latest["status"] == "solved":
                        return {
                            "state": "already_answered",
                            "challenge_id": clean_cid,
                            "proof_token": latest["proof_token"],
                            "verified_at": latest["verified_at"],
                        }
                    return {"state": "consumed", "challenge_id": clean_cid}

                return {
                    "state": "solved",
                    "challenge_id": clean_cid,
                    "proof_token": proof_token,
                    "verified_at": now_iso,
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

    def _record_funnel_event_conn(
        self,
        conn: sqlite3.Connection,
        event_name: str,
        properties: Optional[Dict[str, Any]] = None,
    ) -> str:
        event_id = f"fnl_{secrets.token_hex(8)}"
        now_iso = self.get_now_iso()
        props = dict(properties or {})

        sanitized: Dict[str, Any] = {}
        for k, v in props.items():
            if k in ("key", "api_key", "secret", "claim_secret", "ip", "client_ip", "ip_address"):
                continue
            if k in ("key_hash", "hash"):
                sanitized[k] = str(v)[:8] + "..." if v else None
                continue
            if "wallet" in k or k in ("payer", "payer_wallet", "address"):
                if isinstance(v, str) and len(v) > 8:
                    sanitized[k] = f"{v[:4]}...{v[-4:]}"
                else:
                    sanitized[k] = v
                continue
            sanitized[k] = v

        props_json = json.dumps(sanitized, sort_keys=True)
        conn.execute(
            """
            INSERT INTO funnel_events (event_id, event_name, timestamp_utc, properties_json)
            VALUES (?, ?, ?, ?)
            """,
            (event_id, event_name, now_iso, props_json),
        )
        return event_id

    def record_funnel_event(
        self,
        event_name: str,
        properties: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Records a privacy-conscious funnel conversion event.
        Sanitizes properties to eliminate raw keys, hashes, IPs, and truncate wallet addresses.
        """
        with self._lock, self.connection() as conn:
            with conn:
                return self._record_funnel_event_conn(conn, event_name, properties)

    def get_funnel_metrics(self, since_utc: Optional[str] = None) -> Dict[str, Any]:
        """
        Aggregates conversion counts across funnel stages.
        """
        with self._lock, self.connection() as conn:
            cur = conn.cursor()
            if since_utc:
                cur.execute(
                    """
                    SELECT event_name, COUNT(*) as cnt
                    FROM funnel_events
                    WHERE timestamp_utc >= ?
                    GROUP BY event_name
                    """,
                    (since_utc,),
                )
            else:
                cur.execute(
                    """
                    SELECT event_name, COUNT(*) as cnt
                    FROM funnel_events
                    GROUP BY event_name
                    """
                )
            counts = {row["event_name"]: row["cnt"] for row in cur.fetchall()}

        return {
            "sample_viewed": counts.get("sample_viewed", 0),
            "invoice_created": counts.get("invoice_created", 0),
            "payment_verified": counts.get("payment_verified", 0),
            "key_delivered": counts.get("key_delivered", 0),
            "first_query": counts.get("first_query", 0),
            "quota_warning": counts.get("quota_warning", 0),
            "quota_exhausted": counts.get("quota_exhausted", 0),
            "topup_purchased": counts.get("topup_purchased", 0),
            "total_events": sum(counts.values()),
        }

    def get_funnel_events(
        self,
        limit: int = 100,
        event_name: Optional[str] = None,
    ) -> list[Dict[str, Any]]:
        with self._lock, self.connection() as conn:
            cur = conn.cursor()
            if event_name:
                cur.execute(
                    """
                    SELECT event_id, event_name, timestamp_utc, properties_json
                    FROM funnel_events
                    WHERE event_name = ?
                    ORDER BY timestamp_utc DESC
                    LIMIT ?
                    """,
                    (event_name, limit),
                )
            else:
                cur.execute(
                    """
                    SELECT event_id, event_name, timestamp_utc, properties_json
                    FROM funnel_events
                    ORDER BY timestamp_utc DESC
                    LIMIT ?
                    """,
                    (limit,),
                )
            results = []
            for row in cur.fetchall():
                props = {}
                if row["properties_json"]:
                    try:
                        props = json.loads(row["properties_json"])
                    except Exception:
                        pass
                results.append({
                    "event_id": row["event_id"],
                    "event_name": row["event_name"],
                    "timestamp_utc": row["timestamp_utc"],
                    "properties": props,
                })
            return results

    def get_dashboard_metrics(self) -> Dict[str, Any]:
        """
        Aggregates live operational, commercial, and traffic metrics for the Moltbook Alpha dashboard:
        - Current connected & active users (5m, 1h, 24h)
        - Total registered users and tier distribution
        - Completed sales volume, revenue in USD, and multi-rail breakdown
        - Invoice lifecycle conversion metrics (created, fulfilled, pending, expired)
        - Conversion funnel telemetry and drop-off rates
        - Recent live activity stream and completed transactions
        """
        now = datetime.now(timezone.utc)
        iso_5m = (now - timedelta(minutes=5)).isoformat()
        iso_1h = (now - timedelta(hours=1)).isoformat()
        iso_24h = (now - timedelta(hours=24)).isoformat()

        with self._lock, self.connection() as conn:
            cur = conn.cursor()

            # 1. Total & Active Users
            cur.execute("""
                SELECT
                    COUNT(*) as total_users,
                    SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END) as active_users,
                    SUM(CASE WHEN is_active = 0 THEN 1 ELSE 0 END) as revoked_users
                FROM api_keys
            """)
            u_row = cur.fetchone()
            total_users = u_row["total_users"] if u_row else 0
            active_users = u_row["active_users"] if u_row else 0
            revoked_users = u_row["revoked_users"] if u_row else 0

            cur.execute("""
                SELECT tier, COUNT(*) as cnt
                FROM api_keys
                GROUP BY tier
                ORDER BY cnt DESC
            """)
            users_by_tier = {row["tier"]: row["cnt"] for row in cur.fetchall()}

            cur.execute("""
                SELECT key_prefix, tier, credits, created_at, is_active
                FROM api_keys
                ORDER BY created_at DESC
                LIMIT 8
            """)
            recent_keys = [dict(r) for r in cur.fetchall()]

            # 2. Activity / Events count from audit logs
            cur.execute("SELECT COUNT(*) as cnt FROM audit_logs WHERE created_at >= ?", (iso_5m,))
            events_5m = cur.fetchone()["cnt"]

            cur.execute("SELECT COUNT(*) as cnt FROM audit_logs WHERE created_at >= ?", (iso_1h,))
            events_1h = cur.fetchone()["cnt"]

            cur.execute("SELECT COUNT(*) as cnt FROM audit_logs WHERE created_at >= ?", (iso_24h,))
            events_24h = cur.fetchone()["cnt"]

            # 3. Completed Sales & Revenue
            cur.execute("""
                SELECT
                    COUNT(*) as sales_count,
                    asset,
                    tier,
                    SUM(amount_raw) as total_amount_raw
                FROM payment_redemptions
                GROUP BY asset, tier
            """)
            redemptions = [dict(r) for r in cur.fetchall()]

            total_sales_count = sum(r["sales_count"] for r in redemptions)
            sales_by_tier: Dict[str, int] = {}
            sales_by_asset: Dict[str, Dict[str, Any]] = {}
            total_revenue_usd = 0.0

            TIER_PRICES_USD = {
                "tier_micro": 0.25,
                "tier_starter": 1.00,
                "starter": 1.00,
                "tier_pro": 5.00,
                "pro": 5.00,
                "tier_premium": 20.00,
                "premium": 20.00,
                "topup_500": 8.00,
                "topup_1500": 20.00,
                "topup_5000": 50.00,
            }

            for r in redemptions:
                t = r["tier"]
                a = r["asset"]
                cnt = r["sales_count"]
                sales_by_tier[t] = sales_by_tier.get(t, 0) + cnt

                tier_unit_price = TIER_PRICES_USD.get(t, 1.00)
                tier_rev = cnt * tier_unit_price
                total_revenue_usd += tier_rev

                if a not in sales_by_asset:
                    sales_by_asset[a] = {"count": 0, "revenue_usd": 0.0}
                sales_by_asset[a]["count"] += cnt
                sales_by_asset[a]["revenue_usd"] = round(sales_by_asset[a]["revenue_usd"] + tier_rev, 2)

            cur.execute("""
                SELECT tx_signature, asset, amount_raw, tier, credits_granted, redeemed_at, payer_wallet
                FROM payment_redemptions
                ORDER BY redeemed_at DESC
                LIMIT 8
            """)
            recent_sales = [dict(r) for r in cur.fetchall()]

            # 4. Invoices Lifecycle
            cur.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'fulfilled' THEN 1 ELSE 0 END) as fulfilled,
                    SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
                    SUM(CASE WHEN status = 'expired' THEN 1 ELSE 0 END) as expired
                FROM payment_invoices
            """)
            inv = cur.fetchone()
            total_invoices = inv["total"] if inv else 0
            fulfilled_invoices = inv["fulfilled"] if inv else 0
            pending_invoices = inv["pending"] if inv else 0
            expired_invoices = inv["expired"] if inv else 0
            settlement_rate = (fulfilled_invoices / total_invoices * 100.0) if total_invoices > 0 else 0.0

            # 5. Conversion Funnel Telemetry
            funnel_metrics = self.get_funnel_metrics()

            # 6. Recent System Activity Log
            cur.execute("""
                SELECT id, event_type, detail, created_at
                FROM audit_logs
                ORDER BY id DESC
                LIMIT 25
            """)
            recent_activity = [dict(r) for r in cur.fetchall()]

        return {
            "users": {
                "total_users": total_users,
                "active_users": active_users,
                "revoked_users": revoked_users,
                "users_by_tier": users_by_tier,
                "recent_keys": recent_keys,
            },
            "activity": {
                "events_last_5m": events_5m,
                "events_last_1h": events_1h,
                "events_last_24h": events_24h,
            },
            "sales": {
                "total_sales_count": total_sales_count,
                "total_revenue_usd": round(total_revenue_usd, 2),
                "sales_by_tier": sales_by_tier,
                "sales_by_asset": sales_by_asset,
                "recent_sales": recent_sales,
                "invoices": {
                    "total": total_invoices,
                    "fulfilled": fulfilled_invoices,
                    "pending": pending_invoices,
                    "expired": expired_invoices,
                    "settlement_rate_pct": round(settlement_rate, 1),
                },
            },
            "funnel": funnel_metrics,
            "recent_activity": recent_activity,
        }

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
                cur.execute("DELETE FROM quota_threshold_alerts WHERE key_hash = ?", (key_hash,))
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
                self._reap_expired_reservations_conn(conn)
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

                total_granted = sum(lot["credits_granted"] for lot in lots)
                total_remaining = sum(lot["credits_remaining"] for lot in lots)
                total_consumed = max(0, total_granted - total_remaining)
                percent_consumed = round((total_consumed / float(total_granted) * 100.0), 1) if total_granted > 0 else 0.0

                cur.execute(
                    "SELECT threshold, triggered_at FROM quota_threshold_alerts WHERE key_hash = ? ORDER BY threshold ASC",
                    (k_hash,)
                )
                alerts = [{"threshold": r["threshold"], "triggered_at": r["triggered_at"]} for r in cur.fetchall()]
                highest_alert = alerts[-1]["threshold"] if alerts else None

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
                    "usage": {
                        "quota_limit": total_granted,
                        "consumed": total_consumed,
                        "remaining": total_remaining,
                        "percent_consumed": percent_consumed,
                        "warning_threshold_crossed": highest_alert,
                        "active_alerts": alerts,
                        "configured_thresholds": [0.50, 0.80, 0.90, 0.95],
                    },
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
            with conn:
                self._expire_overdue_lots_and_entitlements(conn)
                self._reap_expired_reservations_conn(conn)
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

    def record_unmatched_payment(
        self,
        rail: str,
        tx_signature: str,
        payer_wallet: str,
        asset: str,
        amount_raw: int,
        expected_amount_raw: Optional[int],
        reason: str,
    ) -> Dict[str, Any]:
        """Records an unmatched or invalid payment in HELD state for refund dispatch."""
        unmatched_id = f"unm_{secrets.token_hex(8)}"
        now_iso = self.get_now().isoformat()
        with self._lock, self.connection() as conn:
            with conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO unmatched_payments (
                        unmatched_id, rail, tx_signature, payer_wallet, asset,
                        amount_raw, expected_amount_raw, reason, status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'HELD', ?)
                    """,
                    (
                        unmatched_id,
                        rail,
                        tx_signature,
                        payer_wallet,
                        asset,
                        amount_raw,
                        expected_amount_raw,
                        reason,
                        now_iso,
                    ),
                )
        return {
            "unmatched_id": unmatched_id,
            "rail": rail,
            "tx_signature": tx_signature,
            "payer_wallet": payer_wallet,
            "asset": asset,
            "amount_raw": amount_raw,
            "expected_amount_raw": expected_amount_raw,
            "reason": reason,
            "status": "HELD",
            "created_at": now_iso,
        }

    def get_unmatched_payment(self, unmatched_id: str) -> Optional[Dict[str, Any]]:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM unmatched_payments WHERE unmatched_id = ?",
                (unmatched_id,),
            ).fetchone()
            return dict(row) if row else None

    def get_unmatched_by_signature(self, tx_signature: str) -> Optional[Dict[str, Any]]:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM unmatched_payments WHERE tx_signature = ?",
                (tx_signature,),
            ).fetchone()
            return dict(row) if row else None

    def list_unmatched_payments(
        self,
        status: Optional[str] = None,
        payer_wallet: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        query = "SELECT * FROM unmatched_payments WHERE 1=1"
        params = []
        if status:
            query += " AND status = ?"
            params.append(status)
        if payer_wallet:
            query += " AND payer_wallet = ?"
            params.append(payer_wallet)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self.connection() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
            return [dict(r) for r in rows]

    def mark_unmatched_refunded(
        self, unmatched_id: str, refund_tx_sig: str, refunded_amount_raw: int
    ) -> bool:
        now_iso = self.get_now().isoformat()
        with self._lock, self.connection() as conn:
            with conn:
                cur = conn.execute(
                    """
                    UPDATE unmatched_payments
                    SET status = 'REFUNDED', refund_tx_sig = ?, refunded_amount_raw = ?, refunded_at = ?
                    WHERE unmatched_id = ? AND status = 'HELD'
                    """,
                    (refund_tx_sig, refunded_amount_raw, now_iso, unmatched_id),
                )
                return cur.rowcount > 0

    def create_webhook_subscription(
        self,
        target_url: str,
        secret_token: str,
        subscribed_events: List[str],
        min_severity: str = "HIGH",
    ) -> Dict[str, Any]:
        """Registers a new webhook callback subscription."""
        subscription_id = f"whsub_{secrets.token_hex(8)}"
        now_iso = self.get_now().isoformat()
        events_json = json.dumps(subscribed_events)

        with self._lock, self.connection() as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO webhook_subscriptions (
                        subscription_id, target_url, secret_token, subscribed_events,
                        min_severity, is_active, created_at
                    ) VALUES (?, ?, ?, ?, ?, 1, ?)
                    """,
                    (subscription_id, target_url.strip(), secret_token.strip(), events_json, min_severity.upper(), now_iso),
                )
        return {
            "subscription_id": subscription_id,
            "target_url": target_url.strip(),
            "subscribed_events": subscribed_events,
            "min_severity": min_severity.upper(),
            "is_active": True,
            "created_at": now_iso,
        }

    def get_webhook_subscription(self, subscription_id: str) -> Optional[Dict[str, Any]]:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM webhook_subscriptions WHERE subscription_id = ?",
                (subscription_id.strip(),),
            ).fetchone()
            if not row:
                return None
            res = dict(row)
            res["subscribed_events"] = json.loads(res["subscribed_events"])
            res["is_active"] = bool(res["is_active"])
            return res

    def list_webhook_subscriptions(self, active_only: bool = True) -> List[Dict[str, Any]]:
        query = "SELECT * FROM webhook_subscriptions"
        if active_only:
            query += " WHERE is_active = 1"
        query += " ORDER BY created_at DESC"
        with self.connection() as conn:
            rows = conn.execute(query).fetchall()
            results = []
            for r in rows:
                item = dict(r)
                item["subscribed_events"] = json.loads(item["subscribed_events"])
                item["is_active"] = bool(item["is_active"])
                results.append(item)
            return results

    def delete_webhook_subscription(self, subscription_id: str) -> bool:
        with self._lock, self.connection() as conn:
            with conn:
                cur = conn.execute(
                    "DELETE FROM webhook_subscriptions WHERE subscription_id = ?",
                    (subscription_id.strip(),),
                )
                return cur.rowcount > 0

    # ---------------------------------------------------------
    # Administrator Authentication & Session Management
    # ---------------------------------------------------------

    def verify_admin_credentials(self, username: str, password: str) -> bool:
        """Verifies admin credentials using PBKDF2-HMAC-SHA256 and constant-time comparison."""
        clean_user = (username or "").strip().upper()
        if not clean_user or not password:
            return False
        with self._lock, self.connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT password_hash, salt FROM admin_users WHERE username = ?", (clean_user,))
            row = cur.fetchone()
            if not row:
                return False
            stored_hash = row["password_hash"]
            salt = row["salt"]
            calc_hash = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000).hex()
            return hmac.compare_digest(stored_hash, calc_hash)

    def change_admin_password(self, username: str, current_password: str, new_password: str) -> Tuple[bool, str]:
        """
        Validates current password and updates to new password with a fresh cryptographic salt.
        Revokes existing active sessions to enforce security.
        """
        clean_user = (username or "").strip().upper()
        if not clean_user:
            return False, "Username is required."
        if not self.verify_admin_credentials(clean_user, current_password):
            return False, "Current password does not match."
        if not new_password or len(new_password) < 8:
            return False, "New password must be at least 8 characters long."

        new_salt = secrets.token_hex(16)
        new_hash = hashlib.pbkdf2_hmac("sha256", new_password.encode("utf-8"), new_salt.encode("utf-8"), 100_000).hex()
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock, self.connection() as conn:
            with conn:
                conn.execute(
                    "UPDATE admin_users SET password_hash = ?, salt = ?, updated_at = ? WHERE username = ?",
                    (new_hash, new_salt, now_iso, clean_user),
                )
                conn.execute("DELETE FROM admin_sessions WHERE username = ?", (clean_user,))
        self.log_audit_event("admin_password_changed", f"Password changed for admin user '{clean_user}'")
        return True, "Password changed successfully."

    def create_admin_session(self, username: str, duration_hours: int = 24) -> str:
        """Issues an active session token for the authenticated admin user."""
        clean_user = (username or "").strip().upper()
        token = f"adm_sess_{secrets.token_hex(24)}"
        now = datetime.now(timezone.utc)
        expires = now + timedelta(hours=duration_hours)
        with self._lock, self.connection() as conn:
            with conn:
                conn.execute(
                    "INSERT INTO admin_sessions (token, username, created_at, expires_at) VALUES (?, ?, ?, ?)",
                    (token, clean_user, now.isoformat(), expires.isoformat()),
                )
        return token

    def validate_admin_session(self, token: str) -> Optional[str]:
        """Validates an admin session token, returning the username if valid and unexpired."""
        if not token or not token.startswith("adm_sess_"):
            return None
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock, self.connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT username, expires_at FROM admin_sessions WHERE token = ?", (token,))
            row = cur.fetchone()
            if not row:
                return None
            if row["expires_at"] < now_iso:
                with conn:
                    conn.execute("DELETE FROM admin_sessions WHERE token = ?", (token,))
                return None
            return row["username"]

    def revoke_admin_session(self, token: str) -> bool:
        """Revokes an admin session token."""
        if not token:
            return False
        with self._lock, self.connection() as conn:
            with conn:
                res = conn.execute("DELETE FROM admin_sessions WHERE token = ?", (token,))
                return res.rowcount > 0
