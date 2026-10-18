"""
Tests for Cryptographic State Witnesses Engine and API Endpoints.
Verifies RFC 8785 JCS canonicalization, Ed25519 signing/verification,
monotonic nonces, hash chaining, tamper detection, and public key discovery.
"""

from fastapi.testclient import TestClient
from storage import StorageManager
from cryptographic_witness import (
    WitnessKeyManager,
    WitnessManager,
    canonical_json,
    b58encode,
    b58decode,
)
from api_server import app, storage


def test_base58_encoding_and_decoding():
    raw = b"MoltbookAlphaCryptographicWitness32B"
    encoded = b58encode(raw)
    decoded = b58decode(encoded)
    assert decoded == raw


def test_canonical_json_rfc8785_ordering_and_spacing():
    # Test dictionary with un-ordered keys and spaces
    data = {
        "z_param": 100,
        "a_param": "hello world",
        "nested": {
            "b": 2,
            "a": 1,
        },
    }
    canonical = canonical_json(data).decode("utf-8")
    expected = '{"a_param":"hello world","nested":{"a":1,"b":2},"z_param":100}'
    assert canonical == expected
    assert " " not in canonical.replace("hello world", "")


def test_witness_key_manager_generation_and_signing(tmp_path):
    key_file = tmp_path / "test_ed25519.pem"
    km = WitnessKeyManager(key_file)
    assert key_file.exists()
    assert km.key_id.startswith("wit_key_")
    assert len(km.public_key_raw) == 32
    assert len(km.public_key_base58) > 30

    # Test signing
    data = b"state_transition_digest_bytes"
    sig = km.sign(data)
    assert len(sig) == 128  # 64 bytes hex encoded

    # Re-instantiate from existing file
    km2 = WitnessKeyManager(key_file)
    assert km2.key_id == km.key_id
    assert km2.public_key_base58 == km.public_key_base58


def test_witness_monotonic_sequence_and_hash_chaining(tmp_path):
    db_file = tmp_path / "test_chain.db"
    sm = StorageManager(db_file)
    wm = WitnessManager(sm)

    # Transition 1
    w1 = wm.create_witness(
        action="QUERY_DEDUCTED",
        actor="molt_test_user_1",
        key_hash="hash_user_1",
        lot_id="lot_001",
        pre_balance=50,
        credit_delta=-1,
        post_balance=49,
        request_id="req_001",
    )
    assert w1["nonce"] == 1
    assert w1["prev_witness_hash"] == "0" * 64

    # Transition 2
    w2 = wm.create_witness(
        action="QUERY_DEDUCTED",
        actor="molt_test_user_1",
        key_hash="hash_user_1",
        lot_id="lot_001",
        pre_balance=49,
        credit_delta=-1,
        post_balance=48,
        request_id="req_002",
    )
    assert w2["nonce"] == 2
    assert w2["prev_witness_hash"] == w1["transition_digest"]

    # Verify both witnesses
    res1 = wm.verify_witness_payload(w1)
    assert res1["valid"] is True
    assert res1["digest_matches"] is True
    assert res1["signature_valid"] is True

    res2 = wm.verify_witness_payload(w2)
    assert res2["valid"] is True
    assert res2["digest_matches"] is True
    assert res2["signature_valid"] is True


def test_witness_tamper_detection(tmp_path):
    db_file = tmp_path / "test_tamper.db"
    sm = StorageManager(db_file)
    wm = WitnessManager(sm)

    w = wm.create_witness(
        action="PAYMENT_SETTLED",
        actor="molt_payer_xyz",
        key_hash="hash_payer",
        lot_id="lot_grant_100",
        pre_balance=0,
        credit_delta=100,
        post_balance=100,
        request_id="req_settle_1",
    )

    # Legitimate verify passes
    assert wm.verify_witness_payload(w)["valid"] is True

    # Tamper 1: change post_balance
    tampered_balance = dict(w)
    tampered_balance["post_balance"] = 999
    res_tamper1 = wm.verify_witness_payload(tampered_balance)
    assert res_tamper1["valid"] is False
    assert res_tamper1["digest_matches"] is False

    # Tamper 2: tamper signature
    tampered_sig = dict(w)
    tampered_sig["signature"] = "0" * 128
    res_tamper2 = wm.verify_witness_payload(tampered_sig)
    assert res_tamper2["valid"] is False
    assert res_tamper2["digest_matches"] is True  # Payload didn't change, signature did
    assert res_tamper2["signature_valid"] is False


def test_api_witnesses_public_keys():
    client = TestClient(app)
    resp = client.get("/v1/witnesses/public-keys")
    assert resp.status_code == 200
    data = resp.json()
    assert "active_key_id" in data
    assert data["active_key_id"] in data["public_keys"]
    key_info = data["public_keys"][data["active_key_id"]]
    assert key_info["algorithm"] == "Ed25519"
    assert "public_key_base58" in key_info
    assert len(key_info["public_key_base58"]) > 30


def test_api_witnesses_fetch_and_verify_endpoints():
    client = TestClient(app)

    # Create an API key with credits and make a briefing request to generate a witness
    raw_key, record = storage.create_api_key(tier="starter", credits=10, prefix_tag="molt_wit_test")
    resp_brief = client.get("/v1/briefing/latest", headers={"X-API-KEY": raw_key})
    assert resp_brief.status_code == 200
    brief_data = resp_brief.json()
    assert brief_data["success"] is True
    witness_id = brief_data.get("state_witness_id")
    assert witness_id is not None
    assert witness_id.startswith("wit_")

    # Fetch witness record by ID
    resp_wit = client.get(f"/v1/witnesses/{witness_id}")
    assert resp_wit.status_code == 200
    wit_record = resp_wit.json()
    assert wit_record["witness_id"] == witness_id
    assert wit_record["action"] == "QUERY_DEDUCTED"
    assert wit_record["credit_delta"] == -1
    assert wit_record["post_balance"] == 9

    # Verify via POST /v1/witnesses/verify
    verify_resp = client.post("/v1/witnesses/verify", json={"witness": wit_record})
    assert verify_resp.status_code == 200
    verify_data = verify_resp.json()
    assert verify_data["valid"] is True
    assert verify_data["digest_matches"] is True
    assert verify_data["signature_valid"] is True

    # Unknown witness ID returns 404
    resp_404 = client.get("/v1/witnesses/wit_non_existent_id")
    assert resp_404.status_code == 404
