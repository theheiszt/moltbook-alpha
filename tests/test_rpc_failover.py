"""
Deterministic Unit and Integration Tests for Solana Multi-RPC Failover.
Validates automated failover on HTTP 429, timeouts, and network errors across RPC pools.
"""

import os
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

from config import load_payment_config, CANONICAL_USDC_MINT
from payment_verifier import (
    SolanaPaymentVerifier,
    RPCError,
    VerificationError,
)
from api_server import app, rate_limiter

TREASURY_WALLET = "BU5zBur46YjnCaY34XGBTJ8KSAG9EExjpZA58wDo7wAx"
TEST_SIGNATURE = "5wHu1qwLq7Xg5WpS1Gv7nJ8cK3L9bM2rT4vN6pQ8sY1xZ3aB5cD7eF9gH2jK4mN6pQ8sY1xZ3aB5cD7eF9gH2jK4"


def make_valid_usdc_tx(
    amount_micro_usdc: int = 1_000_000,
    recipient: str = TREASURY_WALLET,
    reference: str = None,
    block_time: int = None,
) -> dict:
    if block_time is None:
        import time
        block_time = int(time.time())
    account_keys = [
        {"pubkey": "BuyerWallet11111111111111111111111111111111", "signer": True},
        {"pubkey": recipient, "signer": False},
    ]
    if reference:
        account_keys.append({"pubkey": reference, "signer": False, "writable": False})
    return {
        "blockTime": block_time,
        "slot": 250000000,
        "meta": {
            "err": None,
            "preTokenBalances": [],
            "postTokenBalances": [
                {
                    "accountIndex": 1,
                    "mint": CANONICAL_USDC_MINT,
                    "owner": recipient,
                    "uiTokenAmount": {
                        "amount": str(amount_micro_usdc),
                        "decimals": 6,
                        "uiAmount": amount_micro_usdc / 1_000_000,
                    },
                }
            ],
            "preBalances": [2000000000, 1000000000],
            "postBalances": [1995000000, 1000000000],
        },
        "transaction": {
            "message": {
                "accountKeys": account_keys
            }
        },
    }


def test_config_loads_fallback_rpc_endpoints(monkeypatch):
    monkeypatch.setenv("SOLANA_RPC_URL", "https://primary-rpc.example.com")
    monkeypatch.setenv("SOLANA_RPC_FALLBACKS", "https://backup1.example.com, https://backup2.example.com")

    cfg = load_payment_config()
    assert cfg["rpc_url"] == "https://primary-rpc.example.com"
    assert cfg["rpc_endpoints"] == [
        "https://primary-rpc.example.com",
        "https://backup1.example.com",
        "https://backup2.example.com",
    ]


def test_rpc_failover_when_primary_returns_429():
    endpoints = [
        "https://primary.solana.com",
        "https://secondary.solana.com",
    ]
    call_log = []

    def mock_rpc_caller(endpoint: str, method: str, params: list):
        call_log.append(endpoint)
        if endpoint == "https://primary.solana.com":
            raise RPCError("HTTP error 429: Too Many Requests")
        if endpoint == "https://secondary.solana.com":
            return {"jsonrpc": "2.0", "result": make_valid_usdc_tx(1_000_000)}
        raise ValueError(f"Unexpected endpoint: {endpoint}")

    verifier = SolanaPaymentVerifier(
        treasury_wallet=TREASURY_WALLET,
        rpc_endpoints=endpoints,
        rpc_caller=mock_rpc_caller,
    )

    payment = verifier.verify_payment(TEST_SIGNATURE, "tier_starter")

    # Assert failover sequence occurred in order
    assert call_log == ["https://primary.solana.com", "https://secondary.solana.com"]
    assert verifier.active_rpc_endpoint == "https://secondary.solana.com"
    assert payment.rpc_endpoint_used == "https://secondary.solana.com"
    assert payment.asset == "USDC"
    assert payment.amount_raw == 1_000_000
    assert payment.tier == "tier_starter"
    assert payment.credits == 50


def test_rpc_failover_when_primary_times_out():
    endpoints = [
        "https://timeout-node.solana.com",
        "https://reliable-backup.solana.com",
    ]
    call_log = []

    def mock_rpc_caller(endpoint: str, method: str, params: list):
        call_log.append(endpoint)
        if endpoint == "https://timeout-node.solana.com":
            raise TimeoutError("Connection timed out after 10000ms")
        return {"jsonrpc": "2.0", "result": make_valid_usdc_tx(5_000_000)}

    verifier = SolanaPaymentVerifier(
        treasury_wallet=TREASURY_WALLET,
        rpc_endpoints=endpoints,
        rpc_caller=mock_rpc_caller,
    )

    payment = verifier.verify_payment(TEST_SIGNATURE, "tier_pro")

    assert call_log == ["https://timeout-node.solana.com", "https://reliable-backup.solana.com"]
    assert payment.tier == "tier_pro"
    assert payment.credits == 300
    assert payment.rpc_endpoint_used == "https://reliable-backup.solana.com"


def test_rpc_failover_across_three_endpoints():
    endpoints = [
        "https://node-a.com",
        "https://node-b.com",
        "https://node-c.com",
    ]
    call_log = []

    def mock_rpc_caller(endpoint: str, method: str, params: list):
        call_log.append(endpoint)
        if endpoint == "https://node-a.com":
            raise ConnectionResetError("Connection reset by peer")
        if endpoint == "https://node-b.com":
            raise RPCError("HTTP error 503: Service Unavailable")
        if endpoint == "https://node-c.com":
            return {"jsonrpc": "2.0", "result": make_valid_usdc_tx(20_000_000)}
        raise ValueError(f"Unknown endpoint: {endpoint}")

    verifier = SolanaPaymentVerifier(
        treasury_wallet=TREASURY_WALLET,
        rpc_endpoints=endpoints,
        rpc_caller=mock_rpc_caller,
    )

    payment = verifier.verify_payment(TEST_SIGNATURE, "tier_unlimited")

    assert call_log == ["https://node-a.com", "https://node-b.com", "https://node-c.com"]
    assert verifier.active_rpc_endpoint == "https://node-c.com"
    assert payment.tier == "tier_unlimited"
    assert payment.credits == 10000



def test_rpc_failover_all_endpoints_fail_closed():
    endpoints = [
        "https://dead-node-1.com",
        "https://dead-node-2.com",
    ]

    def mock_rpc_caller(endpoint: str, method: str, params: list):
        raise RPCError(f"Node {endpoint} unavailable")

    verifier = SolanaPaymentVerifier(
        treasury_wallet=TREASURY_WALLET,
        rpc_endpoints=endpoints,
        rpc_caller=mock_rpc_caller,
    )

    with pytest.raises(RPCError) as exc_info:
        verifier.verify_payment(TEST_SIGNATURE, "tier_starter")

    err_msg = str(exc_info.value)
    assert "All 2 Solana RPC endpoint(s) failed" in err_msg
    assert "https://dead-node-1.com" in err_msg
    assert "https://dead-node-2.com" in err_msg


def test_rpc_failover_preserves_strict_recipient_validation():
    endpoints = [
        "https://primary.solana.com",
        "https://secondary.solana.com",
    ]

    tx_wrong_recipient = make_valid_usdc_tx(1_000_000, recipient="WrongWallet11111111111111111111111111111111")

    def mock_rpc_caller(endpoint: str, method: str, params: list):
        if endpoint == "https://primary.solana.com":
            raise RPCError("Rate limit 429")
        # Secondary returns tx that went to wrong recipient
        return {"jsonrpc": "2.0", "result": tx_wrong_recipient}

    verifier = SolanaPaymentVerifier(
        treasury_wallet=TREASURY_WALLET,
        rpc_endpoints=endpoints,
        rpc_caller=mock_rpc_caller,
    )

    with pytest.raises(VerificationError) as exc_info:
        verifier.verify_payment(TEST_SIGNATURE, "tier_starter")

    assert "No verified transfer to the configured treasury wallet found" in str(exc_info.value)


def test_api_verify_endpoint_succeeds_through_rpc_failover():
    client = TestClient(app)
    rate_limiter.reset()

    inv = client.post("/v1/payments/invoice", json={"target_tier": "tier_starter"}).json()
    ref = inv["reference"]
    inv_id = inv["invoice_id"]

    import random
    b58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    sig = "".join(random.choices(b58, k=88))
    payload = {"transaction_signature": sig, "invoice_id": inv_id}

    with patch.dict(os.environ, {
        "SOLANA_RPC_URL": "https://flaky-primary.com",
        "SOLANA_RPC_FALLBACKS": "https://working-backup.com",
    }):
        with patch("payment_verifier.SolanaPaymentVerifier._send_http_rpc") as mock_http:
            def side_effect(endpoint, method, params):
                if "flaky-primary" in endpoint:
                    raise RPCError("HTTP error 429: Too Many Requests")
                return {"jsonrpc": "2.0", "result": make_valid_usdc_tx(1_000_000, reference=ref)}

            mock_http.side_effect = side_effect

            resp = client.post(
                "/v1/payments/verify-solana",
                json=payload,
                headers={"x-forwarded-for": "198.51.100.77"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True
            assert data["tier"] == "tier_starter"
            assert data["credits"] == 50
            assert "molt_sol_" in data["api_key"]
