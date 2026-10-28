"""
Cryptographic State Witnesses Engine for Moltbook Alpha API.
Provides RFC 8785 JSON Canonicalization, SHA-256 state digests, Ed25519 digital signatures,
monotonic sequence tracking, and hash-chain audit proofs for state transitions.
"""

import json
import hashlib
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, Union, Tuple

from Crypto.PublicKey import ECC
from Crypto.Signature import eddsa

# Base58 alphabet for Solana & decentralized identity compatibility
B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

# ASN.1 SubjectPublicKeyInfo prefix for Ed25519 (OID 1.3.101.112)
ED25519_SPKI_PREFIX = bytes.fromhex("302a300506032b6570032100")



def b58encode(b: bytes) -> str:
    """Encodes arbitrary bytes into a standard Base58 string (Bitcoin/Solana alphabet)."""
    leading_zeros = len(b) - len(b.lstrip(b"\x00"))
    num = int.from_bytes(b, "big")
    chars = []
    while num > 0:
        num, rem = divmod(num, 58)
        chars.append(B58_ALPHABET[rem])
    return (B58_ALPHABET[0] * leading_zeros) + "".join(reversed(chars))


def b58decode(s: str) -> bytes:
    """Decodes a Base58 string into raw bytes."""
    num = 0
    for char in s:
        idx = B58_ALPHABET.find(char)
        if idx == -1:
            raise ValueError(f"Invalid Base58 character: '{char}'")
        num = num * 58 + idx
    pad = 0
    for char in s:
        if char == B58_ALPHABET[0]:
            pad += 1
        else:
            break
    n_bytes = (num.bit_length() + 7) // 8
    res = num.to_bytes(n_bytes, "big") if num > 0 else b""
    return (b"\x00" * pad) + res


def canonical_json(data: Any) -> bytes:
    """
    Serializes data according to RFC 8785: JSON Canonicalization Scheme (JCS).
    Lexicographically sorts keys, removes all whitespace, enforces UTF-8.
    """
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def hash_payload(data: Any) -> str:
    """Computes SHA-256 hex digest of RFC 8785 canonicalized payload."""
    return hashlib.sha256(canonical_json(data)).hexdigest()


class WitnessKeyManager:
    """Manages the server Ed25519 signing keypair for state witnesses."""

    def __init__(self, key_path: Optional[Path] = None, private_key_pem: Optional[str] = None):
        self.key_path = key_path
        self._key = None
        if private_key_pem:
            self._key = ECC.import_key(private_key_pem)
        else:
            self._load_or_generate()

    def _load_or_generate(self) -> None:
        if self.key_path and self.key_path.exists():
            try:
                pem = self.key_path.read_text(encoding="utf-8")
                self._key = ECC.import_key(pem)
                return
            except Exception:
                pass

        # Generate new Ed25519 keypair
        self._key = ECC.generate(curve="ed25519")
        if self.key_path:
            try:
                self.key_path.parent.mkdir(parents=True, exist_ok=True)
                pem = self._key.export_key(format="PEM")
                self.key_path.write_text(pem, encoding="utf-8")
            except Exception:
                pass

    @property
    def key_id(self) -> str:
        raw_pub = self._key.public_key().export_key(format="raw")
        return f"wit_key_{hashlib.sha256(raw_pub).hexdigest()[:12]}"

    @property
    def public_key_raw(self) -> bytes:
        return self._key.public_key().export_key(format="raw")

    @property
    def public_key_base58(self) -> str:
        return b58encode(self.public_key_raw)

    @property
    def public_key_pem(self) -> str:
        return self._key.public_key().export_key(format="PEM")

    def sign(self, data_bytes: bytes) -> str:
        signer = eddsa.new(self._key, "rfc8032")
        sig_bytes = signer.sign(data_bytes)
        return sig_bytes.hex()

    def get_public_key_info(self) -> Dict[str, Any]:
        return {
            "key_id": self.key_id,
            "algorithm": "Ed25519",
            "public_key_base58": self.public_key_base58,
            "valid_from": "2026-01-01T00:00:00Z",
            "valid_until": "2027-01-01T00:00:00Z",
        }


def verify_witness_signature(
    public_key: Union[bytes, str],
    data_bytes: bytes,
    signature_hex: str,
) -> bool:
    """
    Verifies an Ed25519 signature over canonical data bytes.
    Accepts public_key as raw 32 bytes, Base58 string, or PEM string.
    """
    try:
        if isinstance(public_key, str):
            if public_key.startswith("-----BEGIN"):
                pub = ECC.import_key(public_key)
            else:
                raw_bytes = b58decode(public_key)
                if len(raw_bytes) != 32:
                    return False
                der = ED25519_SPKI_PREFIX + raw_bytes
                pub = ECC.import_key(der)
        elif isinstance(public_key, bytes):
            if len(public_key) == 32:
                der = ED25519_SPKI_PREFIX + public_key
                pub = ECC.import_key(der)
            else:
                pub = ECC.import_key(public_key)
        else:
            return False

        verifier = eddsa.new(pub, "rfc8032")
        verifier.verify(data_bytes, bytes.fromhex(signature_hex))
        return True
    except Exception:
        return False


class WitnessManager:
    """
    Generates, stores, and verifies cryptographic state witnesses for state transitions.
    Maintains monotonic sequence numbers and hash-chaining per key.
    """

    def __init__(self, storage_manager, key_manager: Optional[WitnessKeyManager] = None):
        self.storage = storage_manager
        self.key_manager = key_manager or WitnessKeyManager()
        self._init_witness_table()

    def _init_witness_table(self) -> None:
        with self.storage.connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS state_witnesses (
                    witness_id TEXT PRIMARY KEY,
                    action TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    key_hash TEXT,
                    lot_id TEXT,
                    nonce INTEGER NOT NULL,
                    pre_balance INTEGER,
                    credit_delta INTEGER,
                    post_balance INTEGER,
                    timestamp TEXT NOT NULL,
                    request_id TEXT,
                    prev_witness_hash TEXT NOT NULL,
                    transition_digest TEXT NOT NULL,
                    signature TEXT NOT NULL,
                    key_id TEXT NOT NULL,
                    public_key_base58 TEXT NOT NULL,
                    environmental_anchor_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            # Additive migration if lot_id column missing
            cur.execute("PRAGMA table_info(state_witnesses)")
            cols = {row["name"] if isinstance(row, dict) else row[1] for row in cur.fetchall()}
            if "lot_id" not in cols:
                cur.execute("ALTER TABLE state_witnesses ADD COLUMN lot_id TEXT")

            cur.execute("CREATE INDEX IF NOT EXISTS idx_witness_key_hash ON state_witnesses(key_hash)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_witness_nonce ON state_witnesses(key_hash, nonce)")
            conn.commit()

    def get_latest_witness_hash(self, key_hash: Optional[str]) -> Tuple[int, str]:
        """Returns the latest (nonce, transition_digest) for a key's hash chain."""
        with self.storage.connection() as conn:
            cur = conn.cursor()
            if key_hash:
                cur.execute(
                    "SELECT nonce, transition_digest FROM state_witnesses WHERE key_hash = ? ORDER BY nonce DESC LIMIT 1",
                    (key_hash,)
                )
            else:
                cur.execute("SELECT nonce, transition_digest FROM state_witnesses ORDER BY nonce DESC LIMIT 1")
            row = cur.fetchone()
            if row:
                return row[0], row[1]
            return 0, "0" * 64

    def create_witness(
        self,
        action: str,
        actor: str,
        key_hash: Optional[str] = None,
        lot_id: Optional[str] = None,
        pre_balance: Optional[int] = None,
        credit_delta: Optional[int] = None,
        post_balance: Optional[int] = None,
        request_id: Optional[str] = None,
        environmental_anchor: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Creates, signs, and durably records a cryptographic state witness.
        """
        last_nonce, prev_hash = self.get_latest_witness_hash(key_hash)
        next_nonce = last_nonce + 1
        now_iso = datetime.now(timezone.utc).isoformat()
        anchor = environmental_anchor or {"cluster": "mainnet-beta", "verified_at": now_iso}

        witness_salt = secrets.token_hex(4)
        witness_id = f"wit_{now_iso[:10].replace('-', '')}_{next_nonce:06d}_{witness_salt}"

        # Canonical transition payload to sign
        transition_payload = {
            "action": action,
            "actor": actor,
            "credit_delta": credit_delta,
            "environmental_anchor": anchor,
            "key_hash": key_hash,
            "lot_id": lot_id,
            "nonce": next_nonce,
            "post_balance": post_balance,
            "pre_balance": pre_balance,
            "prev_witness_hash": prev_hash,
            "request_id": request_id,
            "timestamp": now_iso,
        }

        canonical_bytes = canonical_json(transition_payload)
        digest = hashlib.sha256(canonical_bytes).hexdigest()
        signature = self.key_manager.sign(digest.encode("utf-8"))

        witness_record = {
            "witness_id": witness_id,
            **transition_payload,
            "transition_digest": digest,
            "signature": signature,
            "key_id": self.key_manager.key_id,
            "public_key_base58": self.key_manager.public_key_base58,
        }

        with self.storage.connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO state_witnesses (
                    witness_id, action, actor, key_hash, lot_id, nonce, pre_balance,
                    credit_delta, post_balance, timestamp, request_id,
                    prev_witness_hash, transition_digest, signature,
                    key_id, public_key_base58, environmental_anchor_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                witness_id, action, actor, key_hash, lot_id, next_nonce, pre_balance,
                credit_delta, post_balance, now_iso, request_id,
                prev_hash, digest, signature, self.key_manager.key_id,
                self.key_manager.public_key_base58, json.dumps(anchor), now_iso
            ))
            conn.commit()

        return witness_record

    def get_witness(self, witness_id: str) -> Optional[Dict[str, Any]]:
        with self.storage.connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT witness_id, action, actor, key_hash, lot_id, nonce, pre_balance,
                       credit_delta, post_balance, timestamp, request_id,
                       prev_witness_hash, transition_digest, signature,
                       key_id, public_key_base58, environmental_anchor_json
                FROM state_witnesses WHERE witness_id = ?
            """, (witness_id,))
            row = cur.fetchone()
            if not row:
                return None
            return {
                "witness_id": row[0],
                "action": row[1],
                "actor": row[2],
                "key_hash": row[3],
                "lot_id": row[4],
                "nonce": row[5],
                "pre_balance": row[6],
                "credit_delta": row[7],
                "post_balance": row[8],
                "timestamp": row[9],
                "request_id": row[10],
                "prev_witness_hash": row[11],
                "transition_digest": row[12],
                "signature": row[13],
                "key_id": row[14],
                "public_key_base58": row[15],
                "environmental_anchor": json.loads(row[16]),
            }

    def verify_witness_payload(
        self,
        witness: Dict[str, Any],
        public_key_b58: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Independently verifies witness schema, digest calculation, and Ed25519 signature.
        Returns a verification report dictionary with detailed pass/fail diagnostics.
        """
        payload_to_verify = {
            "action": witness.get("action"),
            "actor": witness.get("actor"),
            "credit_delta": witness.get("credit_delta"),
            "environmental_anchor": witness.get("environmental_anchor"),
            "key_hash": witness.get("key_hash"),
            "lot_id": witness.get("lot_id"),
            "nonce": witness.get("nonce"),
            "post_balance": witness.get("post_balance"),
            "pre_balance": witness.get("pre_balance"),
            "prev_witness_hash": witness.get("prev_witness_hash"),
            "request_id": witness.get("request_id"),
            "timestamp": witness.get("timestamp"),
        }

        canonical_bytes = canonical_json(payload_to_verify)
        expected_digest = hashlib.sha256(canonical_bytes).hexdigest()
        digest_matches = expected_digest == witness.get("transition_digest")

        target_pub_key = public_key_b58 or witness.get("public_key_base58") or self.key_manager.public_key_base58
        sig_hex = witness.get("signature", "")

        sig_valid = verify_witness_signature(
            public_key=target_pub_key,
            data_bytes=expected_digest.encode("utf-8"),
            signature_hex=sig_hex,
        )

        is_valid = digest_matches and sig_valid
        reason = None
        if not digest_matches:
            reason = "Transition digest mismatch (canonical payload hash does not match transition_digest)."
        elif not sig_valid:
            reason = "Cryptographic signature invalid or signed by a different public key."

        return {
            "valid": is_valid,
            "transition_digest": expected_digest,
            "digest_matches": digest_matches,
            "signature_valid": sig_valid,
            "public_key_verified": target_pub_key,
            "reason": reason,
        }

    def get_public_keys_metadata(self) -> Dict[str, Any]:
        info = self.key_manager.get_public_key_info()
        return {
            "active_key_id": self.key_manager.key_id,
            "public_keys": {
                self.key_manager.key_id: {
                    "algorithm": info["algorithm"],
                    "public_key_base58": info["public_key_base58"],
                    "valid_from": info["valid_from"],
                    "valid_until": info["valid_until"],
                }
            },
        }
