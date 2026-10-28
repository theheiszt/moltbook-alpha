"""
Moltbook Alpha Client SDK — Cryptographic Verification.
Provides RFC 8785 JCS canonicalization, Base58 decoding, and Ed25519 local signature verification.
Zero network calls required for offline proof verification.
"""

import json
import hashlib
from typing import Dict, Any, Union

B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
ED25519_SPKI_PREFIX = bytes.fromhex("302a300506032b6570032100")


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
    """Serializes data according to RFC 8785: JSON Canonicalization Scheme (JCS)."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def verify_witness_signature_local(
    public_key: Union[bytes, str],
    data_bytes: bytes,
    signature_hex: str,
) -> bool:
    """
    Independently verifies an Ed25519 signature over canonical data bytes.
    Supports pycryptodome or cryptography libraries.
    """
    # 1. Try pycryptodome
    try:
        from Crypto.PublicKey import ECC
        from Crypto.Signature import eddsa

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
    except ImportError:
        pass
    except Exception:
        return False

    # 2. Try cryptography library
    try:
        from cryptography.hazmat.primitives.asymmetric import ed25519

        raw_pub = b58decode(public_key) if isinstance(public_key, str) and not public_key.startswith("-----BEGIN") else public_key
        if isinstance(raw_pub, bytes) and len(raw_pub) == 32:
            pub_key_obj = ed25519.Ed25519PublicKey.from_public_bytes(raw_pub)
            pub_key_obj.verify(bytes.fromhex(signature_hex), data_bytes)
            return True
    except Exception:
        return False

    return False


def verify_witness_payload_offline(witness: Dict[str, Any], public_key_b58: str) -> Dict[str, Any]:
    """
    Offline verification of an RFC 8785 state witness against a server public key.
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

    sig_hex = witness.get("signature", "")
    sig_valid = verify_witness_signature_local(
        public_key=public_key_b58,
        data_bytes=expected_digest.encode("utf-8"),
        signature_hex=sig_hex,
    )

    return {
        "valid": digest_matches and sig_valid,
        "digest_matches": digest_matches,
        "signature_valid": sig_valid,
        "transition_digest": expected_digest,
    }
