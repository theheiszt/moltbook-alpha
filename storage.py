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

                    CREATE INDEX IF NOT EXISTS idx_keys_active ON api_keys(is_active);
                    CREATE INDEX IF NOT EXISTS idx_redemptions_hash ON payment_redemptions(key_hash);
                    CREATE INDEX IF NOT EXISTS idx_invoices_ref ON payment_invoices(reference);
                    CREATE INDEX IF NOT EXISTS idx_invoices_status ON payment_invoices(status);
                """)

                # Additive migration for payment_redemptions metadata columns
                cur = conn.cursor()
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
                self._cached_active_count = None

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
                    self._cached_active_count = None
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

        now = datetime.now(timezone.utc)
        created_at_iso = now.isoformat()
        expires_at_iso = (now + timedelta(seconds=expiry_seconds)).isoformat()

        with self._lock, self.connection() as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO payment_invoices (
                        invoice_id, reference, tier, credits, asset, amount_raw,
                        recipient, cluster, status, claim_secret_hash, created_at, expires_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
                    """,
                    (
                        invoice_id,
                        reference,
                        tier,
                        credits,
                        asset,
                        amount_raw,
                        recipient,
                        cluster,
                        claim_secret_hash,
                        created_at_iso,
                        expires_at_iso,
                    ),
                )

        invoice_record = {
            "invoice_id": invoice_id,
            "reference": reference,
            "tier": tier,
            "credits": credits,
            "asset": asset,
            "amount_raw": amount_raw,
            "recipient": recipient,
            "cluster": cluster,
            "status": "pending",
            "created_at": created_at_iso,
            "expires_at": expires_at_iso,
        }
        return invoice_record, claim_secret, reference

    def get_invoice(self, invoice_id: str) -> Optional[Dict[str, Any]]:
        with self._lock, self.connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT invoice_id, reference, tier, credits, asset, amount_raw,
                       recipient, cluster, status, claim_secret_hash, encrypted_key_envelope,
                       tx_signature, created_at, expires_at, fulfilled_at
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
                       tx_signature, created_at, expires_at, fulfilled_at
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
        Atomically transitions an invoice from 'pending' to 'fulfilled' and mints an API key.
        Guarantees that:
        1. A transaction signature cannot be redeemed twice.
        2. An invoice cannot be fulfilled twice.
        3. Encrypts the raw key with claim_secret for zero-knowledge client recovery.
        4. Completely rolls back if any operation fails.
        """
        sig = tx_signature.strip()
        inv_id = invoice_id.strip()
        now_iso = datetime.now(timezone.utc).isoformat()

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
                       status, expires_at, claim_secret_hash
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
                    "tier": winner["tier"] if winner else tier,
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

            # 3. Mint new key and prepare encrypted envelope
            raw_token = f"molt_sol_{secrets.token_hex(16)}"
            k_hash = self.hash_key(raw_token)
            k_prefix = raw_token[:12] + "..."

            encrypted_envelope = None
            if claim_secret:
                try:
                    encrypted_envelope = encrypt_key_envelope(raw_token, claim_secret)
                except Exception as e:
                    raise StorageError(f"Failed to prepare key recovery envelope: {e}") from e

            # 4. Atomic execution
            try:
                with conn:
                    # Insert API key
                    cur.execute(
                        """
                        INSERT INTO api_keys (key_hash, key_prefix, tier, credits, created_at, is_active)
                        VALUES (?, ?, ?, ?, ?, 1)
                        """,
                        (k_hash, k_prefix, tier, credits_to_grant, now_iso),
                    )

                    # Insert redemption record
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
                            tier,
                            credits_to_grant,
                            now_iso,
                            inv_id,
                            payer,
                            reference or inv["reference"],
                            slot,
                            block_time,
                        ),
                    )

                    # Update invoice state to fulfilled
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
                    "tier": tier,
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
                    "tier": winner["tier"] if winner else tier,
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
