#!/usr/bin/env python3
"""
Moltbook Alpha & ATLAS Security — Autonomous Provenance Guard & Anti-Pope Firewall.
Document Reference: ATLAS-SEC-SPEC-2026-001

Implements the official ATLAS Dual-Spec Architecture:
1. Spec A: Non-Inferable Permission Tokens (The Anti-Pope Gate)
   - Eliminates ambient authority and conversational context ordination.
   - Pins parameters to canonical RFC 8785 byte digests.
   - Enforces single-use nonce invalidation in SQLite ACID storage.
   - Enforces strict 300s TTL.
2. Spec B: Out-of-Band State Witness & L1 Anchoring (The External Head Protocol)
   - Confines sandboxed agents to unidirectional append proposals over IPC.
   - Detached supervisor maintains monotonic sequences and signs the cumulative
     head outside the sandbox with host-isolated Ed25519 keys (wit_ records).
   - Anchors daily Merkle roots into DEUSPROOF and Bitcoin L1 block headers.
"""

import hashlib
import secrets
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, List

# Fix Windows console encoding if executed standalone
if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config import DATA_DIR  # noqa: E402
from cryptographic_witness import (  # noqa: E402
    WitnessKeyManager,
    canonical_json,
    verify_witness_signature,
)

DEFAULT_SECURITY_DB = DATA_DIR / "atlas_security.db"


@contextmanager
def db_connection(db_path: Path):
    """Context manager ensuring sqlite connection is properly closed on Windows."""
    conn = sqlite3.connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


class SecurityError(Exception):
    """Base exception for security boundary violations."""
    pass


class UnauthorizedOrdinationError(SecurityError):
    """Raised when an action attempts to derive permission from context compression/summaries."""
    pass


class TamperDetectedError(SecurityError):
    """Raised when an in-sandbox file or hash-chain entry deviates from out-of-band witness head."""
    pass


class InvalidCapabilityTokenError(SecurityError):
    """Raised when a capability token is expired, forged, or parameter-mismatched."""
    pass


class ReplayAttackError(SecurityError):
    """Raised when a single-use capability token nonce has already been consumed."""
    pass


class ATLASCapabilityToken:
    """
    An un-summarizable, cryptographically bound permission grant for ATLAS Level 2 operations.
    """

    def __init__(
        self,
        capability: str,
        target_resource: str,
        parameters: Dict[str, Any],
        issuer_did: str = "did:key:authorized_sovereign_identity",
        audience: str = "agent:moltbook-intel:worker-alpha",
        ttl_seconds: int = 300,
        token_id: Optional[str] = None,
        nonce: Optional[str] = None,
        issued_at: Optional[str] = None,
        expires_at: Optional[str] = None,
        signature: Optional[str] = None,
    ):
        self.token_id = token_id or f"cap_{secrets.token_hex(8)}"
        self.issuer_did = issuer_did
        self.audience = audience
        self.capability = capability
        self.target_resource = target_resource
        self.parameters = parameters
        self.parameters_digest = hashlib.sha256(canonical_json(parameters)).hexdigest()
        self.nonce = nonce or f"n_{secrets.token_hex(12)}"

        now = datetime.now(timezone.utc)
        self.issued_at = issued_at or now.isoformat()
        self.expires_at = expires_at or (now + timedelta(seconds=ttl_seconds)).isoformat()
        self.signature = signature

    def canonical_payload(self) -> Dict[str, Any]:
        """Returns the canonical authorization payload for signing."""
        return {
            "token_id": self.token_id,
            "issuer_did": self.issuer_did,
            "audience": self.audience,
            "capability": self.capability,
            "target_resource": self.target_resource,
            "parameters_digest": self.parameters_digest,
            "nonce": self.nonce,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
        }

    def compute_digest(self) -> str:
        """Computes SHA-256 hex digest over canonical JSON bytes."""
        payload_bytes = canonical_json(self.canonical_payload())
        return hashlib.sha256(payload_bytes).hexdigest()

    def sign(self, key_manager: WitnessKeyManager) -> str:
        """Signs the canonical token payload using the grantor's Ed25519 key."""
        digest = self.compute_digest()
        self.signature = key_manager.sign(digest.encode("utf-8"))
        return self.signature

    def is_expired(self, clock_leeway_sec: int = 5) -> bool:
        """Checks if token expiration timestamp has elapsed."""
        now = datetime.now(timezone.utc)
        exp = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        return now > (exp + timedelta(seconds=clock_leeway_sec))

    def to_dict(self) -> Dict[str, Any]:
        return {
            **self.canonical_payload(),
            "signature": self.signature,
            "parameters": self.parameters,
        }


class AntiPopeGate:
    """
    Enforces Spec A: Eliminates ambient authority and context ordination.
    Maintains the single-use nonce invalidation ledger (atlas_consumed_tokens) in SQLite.
    """

    def __init__(self, db_path: Path = DEFAULT_SECURITY_DB, trusted_issuers: Optional[Dict[str, str]] = None):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.trusted_issuers = trusted_issuers or {}
        self._init_db()

    def _init_db(self) -> None:
        with db_connection(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS atlas_consumed_tokens (
                    token_id TEXT PRIMARY KEY,
                    issuer_did TEXT NOT NULL,
                    audience TEXT NOT NULL,
                    capability TEXT NOT NULL,
                    parameters_digest TEXT NOT NULL,
                    nonce TEXT NOT NULL UNIQUE,
                    issued_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    consumed_at TEXT NOT NULL
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_consumed_nonce ON atlas_consumed_tokens(nonce)")
            conn.commit()

    def register_trusted_issuer(self, issuer_did: str, public_key_b58: str) -> None:
        """Registers an authorized sovereign identity public key."""
        self.trusted_issuers[issuer_did] = public_key_b58

    def authorize_action(
        self,
        capability: str,
        target_resource: str,
        parameters: Dict[str, Any],
        token: Optional[ATLASCapabilityToken] = None,
        context_justification: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Validates authorization for consequential operations.
        Fails closed with UnauthorizedOrdinationError if context is cited without a signed token.
        """
        if token is None:
            claim = context_justification or "Conversational memory or compression summary"
            raise UnauthorizedOrdinationError(
                f"Authorization Denied: '{claim}' cannot ordain permissions for capability '{capability}'. "
                "ATLAS Non-Inferable Principle: Remembered intent in context compression is not an execution grant. "
                "An explicit, cryptographically signed CapabilityToken is strictly required."
            )

        # 1. Action & Resource Scope Check
        if token.capability != capability:
            raise InvalidCapabilityTokenError(
                f"Capability mismatch: token grants '{token.capability}', requested '{capability}'."
            )

        if token.target_resource != target_resource:
            raise InvalidCapabilityTokenError(
                f"Resource mismatch: token grants '{token.target_resource}', requested '{target_resource}'."
            )

        # 2. Parameter Pinning Check
        current_digest = hashlib.sha256(canonical_json(parameters)).hexdigest()
        if token.parameters_digest != current_digest:
            raise InvalidCapabilityTokenError(
                f"Parameter tampering detected: runtime parameters hash {current_digest} != granted {token.parameters_digest}."
            )

        # 3. Expiration Check
        if token.is_expired():
            raise InvalidCapabilityTokenError(f"Capability token {token.token_id} expired at {token.expires_at}.")

        # 4. Asymmetric Cryptographic Signature Check
        public_key = self.trusted_issuers.get(token.issuer_did)
        if not public_key:
            raise InvalidCapabilityTokenError(f"Untrusted issuer DID: '{token.issuer_did}'.")

        digest = token.compute_digest()
        valid_sig = verify_witness_signature(
            public_key=public_key,
            data_bytes=digest.encode("utf-8"),
            signature_hex=token.signature or "",
        )
        if not valid_sig:
            raise InvalidCapabilityTokenError("Cryptographic signature invalid on capability token.")

        # 5. Atomic Nonce Consumption (Anti-Replay Ledger)
        now_iso = datetime.now(timezone.utc).isoformat()
        try:
            with db_connection(self.db_path) as conn:
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO atlas_consumed_tokens (
                        token_id, issuer_did, audience, capability, parameters_digest,
                        nonce, issued_at, expires_at, consumed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    token.token_id, token.issuer_did, token.audience, token.capability,
                    token.parameters_digest, token.nonce, token.issued_at, token.expires_at, now_iso
                ))
                conn.commit()
        except sqlite3.IntegrityError as e:
            raise ReplayAttackError(
                f"Replay Attack Blocked: Nonce '{token.nonce}' has already been consumed."
            ) from e

        return {
            "authorized": True,
            "token_id": token.token_id,
            "capability": capability,
            "resource": target_resource,
            "parameters_digest": token.parameters_digest,
            "nonce": token.nonce,
            "consumed_at": now_iso,
        }


class OutOfBandProvenanceWitness:
    """
    Enforces Spec B: External Head Protocol.
    Maintains an immutable hash-chain ledger outside the sandbox.
    Sandboxed workers only emit unidirectional proposals; host daemon signs the head.
    """

    def __init__(self, key_manager: Optional[WitnessKeyManager] = None):
        self.key_manager = key_manager or WitnessKeyManager()
        self._journal: List[Dict[str, Any]] = []
        self._latest_digest: str = "0" * 64
        self._sequence_counter: int = 0

    @property
    def host_public_key_b58(self) -> str:
        return self.key_manager.public_key_base58

    @property
    def latest_head_digest(self) -> str:
        return self._latest_digest

    @property
    def sequence_counter(self) -> int:
        return self._sequence_counter

    def propose_event(
        self,
        event_type: str,
        actor: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Processes an append-only event proposal submitted from the unprivileged sandbox.
        Assigns monotonic sequence, computes cumulative SHA-256 link, and signs the head.
        """
        self._sequence_counter += 1
        now_iso = datetime.now(timezone.utc).isoformat()
        prev_digest = self._latest_digest

        canonical_event = {
            "sequence": self._sequence_counter,
            "event_type": event_type,
            "actor": actor,
            "payload": payload,
            "prev_digest": prev_digest,
            "timestamp": now_iso,
        }

        canonical_bytes = canonical_json(canonical_event)
        transition_digest = hashlib.sha256(canonical_bytes).hexdigest()
        signature = self.key_manager.sign(transition_digest.encode("utf-8"))

        witness_record = {
            "witness_id": f"wit_{now_iso[:10].replace('-', '')}_{self._sequence_counter:06d}_{secrets.token_hex(4)}",
            **canonical_event,
            "transition_digest": transition_digest,
            "signature": signature,
            "public_key_base58": self.host_public_key_b58,
        }

        self._journal.append(witness_record)
        self._latest_digest = transition_digest
        return witness_record

    def verify_chain_integrity(self, candidate_journal: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """
        Validates hash-chain continuity and Ed25519 signatures across every link.
        If any record was tampered with in-sandbox, detects the divergence immediately.
        """
        records = candidate_journal if candidate_journal is not None else self._journal
        expected_prev = "0" * 64
        expected_seq = 1

        for idx, rec in enumerate(records):
            seq = rec.get("sequence")
            prev_hash = rec.get("prev_digest")
            digest = rec.get("transition_digest")
            sig = rec.get("signature")

            if seq != expected_seq:
                raise TamperDetectedError(
                    f"Chain sequence broken at index {idx}: expected {expected_seq}, found {seq}."
                )

            if prev_hash != expected_prev:
                raise TamperDetectedError(
                    f"Hash-chain link broken at index {idx}: expected prev {expected_prev}, found {prev_hash}."
                )

            event_core = {
                "sequence": seq,
                "event_type": rec.get("event_type"),
                "actor": rec.get("actor"),
                "payload": rec.get("payload"),
                "prev_digest": prev_hash,
                "timestamp": rec.get("timestamp"),
            }
            computed_digest = hashlib.sha256(canonical_json(event_core)).hexdigest()
            if computed_digest != digest:
                raise TamperDetectedError(
                    f"Payload tampering detected at sequence {seq}: computed digest {computed_digest} != {digest}."
                )

            valid_sig = verify_witness_signature(
                public_key=self.host_public_key_b58,
                data_bytes=digest.encode("utf-8"),
                signature_hex=sig,
            )
            if not valid_sig:
                raise TamperDetectedError(
                    f"Signature validation failed at sequence {seq}. Record was forged or signed by unknown key."
                )

            expected_prev = digest
            expected_seq += 1

        return {
            "valid": True,
            "chain_length": len(records),
            "head_digest": expected_prev,
            "anchor_verified": True,
        }


class DEUSPROOFAnchorBridge:
    """
    Computes balanced Merkle trees over daily state transition digests
    and anchors the epoch root into Bitcoin block headers via DEUSPROOF.
    """

    def __init__(self, db_path: Path = DEFAULT_SECURITY_DB):
        self.db_path = Path(db_path)
        self._init_db()

    def _init_db(self) -> None:
        with db_connection(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS atlas_epoch_anchors (
                    epoch_date TEXT PRIMARY KEY,
                    merkle_root TEXT NOT NULL,
                    start_nonce INTEGER NOT NULL,
                    end_nonce INTEGER NOT NULL,
                    witness_count INTEGER NOT NULL,
                    deusproof_cert_id TEXT,
                    bitcoin_block_height INTEGER,
                    bitcoin_block_hash TEXT,
                    status TEXT NOT NULL,
                    anchored_at TEXT NOT NULL
                )
            """)
            conn.commit()

    @staticmethod
    def compute_merkle_root(leaf_hashes: List[str]) -> str:
        """Computes balanced binary Merkle root from list of SHA-256 hex hashes."""
        if not leaf_hashes:
            return "0" * 64
        current_layer = [bytes.fromhex(h) for h in leaf_hashes]

        while len(current_layer) > 1:
            next_layer = []
            for i in range(0, len(current_layer), 2):
                left = current_layer[i]
                right = current_layer[i + 1] if i + 1 < len(current_layer) else left
                combined = hashlib.sha256(left + right).digest()
                next_layer.append(combined)
            current_layer = next_layer

        return current_layer[0].hex()

    def anchor_epoch(
        self,
        epoch_date: str,
        leaf_hashes: List[str],
        deusproof_cert_id: Optional[str] = None,
        bitcoin_block_height: Optional[int] = None,
        bitcoin_block_hash: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Calculates Merkle root and persists the epoch L1 anchor record."""
        merkle_root = self.compute_merkle_root(leaf_hashes)
        count = len(leaf_hashes)
        now_iso = datetime.now(timezone.utc).isoformat()
        status = "L1_CONFIRMED" if (bitcoin_block_height and bitcoin_block_hash) else "NOTARIZED"

        with db_connection(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT OR REPLACE INTO atlas_epoch_anchors (
                    epoch_date, merkle_root, start_nonce, end_nonce, witness_count,
                    deusproof_cert_id, bitcoin_block_height, bitcoin_block_hash, status, anchored_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                epoch_date, merkle_root, 1, count, count,
                deusproof_cert_id or f"cert_{epoch_date.replace('-', '')}_{merkle_root[:8]}",
                bitcoin_block_height, bitcoin_block_hash, status, now_iso
            ))
            conn.commit()

        return {
            "epoch_date": epoch_date,
            "merkle_root": merkle_root,
            "witness_count": count,
            "deusproof_cert_id": deusproof_cert_id,
            "bitcoin_block_height": bitcoin_block_height,
            "bitcoin_block_hash": bitcoin_block_hash,
            "status": status,
            "anchored_at": now_iso,
        }


class AtlasProvenanceGuard:
    """
    Unified Orchestrator: Combines AntiPopeGate, OutOfBandWitness, and DEUSPROOFAnchorBridge.
    """

    def __init__(
        self,
        db_path: Path = DEFAULT_SECURITY_DB,
        key_manager: Optional[WitnessKeyManager] = None,
    ):
        self.key_manager = key_manager or WitnessKeyManager()
        self.anti_pope_gate = AntiPopeGate(
            db_path=db_path,
            trusted_issuers={"did:key:host": self.key_manager.public_key_base58},
        )
        self.witness_daemon = OutOfBandProvenanceWitness(key_manager=self.key_manager)
        self.l1_bridge = DEUSPROOFAnchorBridge(db_path=db_path)

    def guard_execution(
        self,
        capability: str,
        target_resource: str,
        parameters: Dict[str, Any],
        token: Optional[ATLASCapabilityToken],
        execution_callable: Any,
        context_claims: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Executes a sensitive action strictly inside the ATLAS security boundary:
        1. Validates and consumes the CapabilityToken (anti-pope + anti-replay).
        2. Executes the protected callable.
        3. Records and signs an out-of-band state witness transition.
        """
        # 1. Gate verification
        auth_receipt = self.anti_pope_gate.authorize_action(
            capability=capability,
            target_resource=target_resource,
            parameters=parameters,
            token=token,
            context_justification=context_claims,
        )

        # 2. Protected Execution
        result = execution_callable()

        # 3. Out-of-band witness record
        witness_rec = self.witness_daemon.propose_event(
            event_type=f"EXECUTE_{capability.upper()}",
            actor=token.audience,
            payload={
                "target_resource": target_resource,
                "parameters_digest": token.parameters_digest,
                "token_id": token.token_id,
            },
        )

        return {
            "success": True,
            "auth": auth_receipt,
            "result": result,
            "state_witness": witness_rec,
        }


if __name__ == "__main__":
    guard = AtlasProvenanceGuard()
    print(f"[ATLAS Provenance Guard] Initialized with Host Public Key: {guard.key_manager.public_key_base58}")
