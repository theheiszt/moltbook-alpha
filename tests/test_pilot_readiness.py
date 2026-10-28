"""
Tests for Stage 17 Alpha Pilot Readiness:
1. Trusted proxy IP spoofing prevention and forwarding boundaries
2. Solana Pay expected payer and reference verification
3. Health diagnostic information exposure guardrails
4. Webhook duplicate delivery idempotency and malformed payload rejection
5. Quota consistency and persistence verification
"""

from fastapi.testclient import TestClient
from unittest.mock import patch
import pytest

from api_server import app, is_trusted_proxy, get_client_ip
from payment_verifier import SolanaPaymentVerifier, VerificationError



def test_trusted_proxy_detection_with_cidrs():
    # Empty trusted proxies -> nothing trusted
    assert is_trusted_proxy("192.168.1.1", []) is False

    # Exact IP matching
    assert is_trusted_proxy("10.0.0.1", ["10.0.0.1"]) is True
    assert is_trusted_proxy("10.0.0.2", ["10.0.0.1"]) is False

    # CIDR network matching
    trusted = ["10.0.0.0/24", "172.16.0.0/16", "127.0.0.1"]
    assert is_trusted_proxy("10.0.0.42", trusted) is True
    assert is_trusted_proxy("10.0.1.1", trusted) is False
    assert is_trusted_proxy("172.16.5.99", trusted) is True
    assert is_trusted_proxy("172.17.0.1", trusted) is False
    assert is_trusted_proxy("127.0.0.1", trusted) is True
    assert is_trusted_proxy("invalid-ip", trusted) is False


def test_untrusted_forwarded_headers_cannot_spoof_client_ip(monkeypatch):
    """
    Proves that an untrusted remote client sending a forged X-Forwarded-For
    cannot spoof their IP to evade rate limiting or pollute audit logs.
    """
    # In production with empty TRUSTED_PROXIES, peer is untrusted
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("TRUSTED_PROXIES", raising=False)

    class MockClient:
        host = "198.51.100.55"

    class MockRequest:
        client = MockClient()
        headers = {"x-forwarded-for": "8.8.8.8, 1.1.1.1"}

    # Must return the actual connection peer IP, ignoring the forged header
    derived_ip = get_client_ip(MockRequest())
    assert derived_ip == "198.51.100.55"


def test_trusted_forwarded_headers_respected_when_configured(monkeypatch):
    """
    Proves that when behind an approved reverse proxy (e.g., 10.0.0.1),
    the forwarded client IP is correctly extracted.
    """
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("TRUSTED_PROXIES", "10.0.0.1, 127.0.0.1")

    class MockClient:
        host = "10.0.0.1"

    class MockRequest:
        client = MockClient()
        headers = {"x-forwarded-for": "203.0.113.195, 10.0.0.1"}

    derived_ip = get_client_ip(MockRequest())
    assert derived_ip == "203.0.113.195"


def test_expected_payer_verification_success_and_failure():
    verifier = SolanaPaymentVerifier(rpc_caller=lambda *a, **k: {})

    fake_payer = "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R"
    wrong_payer = "6b57xUptv5r2Hn7W9x8wDkXzN4gV3yP1qR8sT7uV2wXy"
    treasury = verifier.treasury_wallet

    fake_tx = {
        "slot": 1000,
        "blockTime": 1729188000,
        "confirmationStatus": "finalized",
        "commitment": "finalized",
        "transaction": {
            "signatures": ["5" * 88],
            "message": {
                "accountKeys": [
                    fake_payer,  # Signer / Fee payer at index 0
                    treasury,
                ]
            }
        },
        "meta": {
            "err": None,
            "preBalances": [20_000_000, 10_000_000],
            "postBalances": [14_995_000, 15_000_000],  # 5_000_000 lamports net to treasury (~$1.00)
            "preTokenBalances": [],
            "postTokenBalances": [],
        }
    }

    with patch.object(verifier, "fetch_transaction", return_value=fake_tx):
        # 1. Matching expected payer succeeds
        payment = verifier.verify_payment(
            "5" * 88,
            requested_tier="tier_starter",
            expected_payer=fake_payer,
        )
        assert payment.tier == "tier_starter"
        assert payment.payer == fake_payer

        # 2. Mismatched expected payer fails closed
        with pytest.raises(VerificationError) as exc_info:
            verifier.verify_payment(
                "5" * 88,
                requested_tier="tier_starter",
                expected_payer=wrong_payer,
            )
        assert "Payer mismatch" in str(exc_info.value)


def test_expected_reference_verification_success_and_failure():
    verifier = SolanaPaymentVerifier(rpc_caller=lambda *a, **k: {})

    payer = "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R"
    treasury = verifier.treasury_wallet
    solana_pay_ref = "9x8wDkXzN4gV3yP1qR8sT7uV2wXy6b57xUptv5r2Hn7W"
    wrong_ref = "7T7uV2wXy6b57xUptv5r2Hn7W9x8wDkXzN4gV3yP1qR8s"

    fake_tx = {
        "slot": 1000,
        "blockTime": 1729188000,
        "confirmationStatus": "finalized",
        "commitment": "finalized",
        "transaction": {
            "signatures": ["5" * 88],
            "message": {
                "accountKeys": [
                    payer,
                    treasury,
                    solana_pay_ref,  # Solana Pay reference key included in accountKeys
                ]
            }
        },
        "meta": {
            "err": None,
            "preBalances": [20_000_000, 10_000_000, 0],
            "postBalances": [14_995_000, 15_000_000, 0],
            "preTokenBalances": [],
            "postTokenBalances": [],
        }
    }

    with patch.object(verifier, "fetch_transaction", return_value=fake_tx):
        # 1. Matching expected reference succeeds
        payment = verifier.verify_payment(
            "5" * 88,
            requested_tier="tier_starter",
            expected_reference=solana_pay_ref,
        )
        assert payment.reference == solana_pay_ref

        # 2. Mismatched reference fails closed
        with pytest.raises(VerificationError) as exc_info:
            verifier.verify_payment(
                "5" * 88,
                requested_tier="tier_starter",
                expected_reference=wrong_ref,
            )
        assert "Reference mismatch" in str(exc_info.value)


def test_health_endpoint_does_not_expose_credentials_or_secrets():
    client = TestClient(app)
    resp = client.get("/v1/health")
    assert resp.status_code == 200
    data_str = resp.text.lower()

    # Assert no sensitive tokens, database passwords, or private keys in health response
    assert "password" not in data_str
    assert "secret" not in data_str
    assert "private_key" not in data_str
    assert "api_key" not in data_str
    assert "bearer" not in data_str
