"""
Perimeter and Proxy Trust Verification Suite (Stage 18 Phase C).
Validates the 10 proxy and perimeter scenarios:
1. Direct connection with no forwarding header.
2. Direct untrusted connection supplying a fabricated X-Forwarded-For.
3. Trusted proxy supplying the expected client address.
4. Untrusted peer supplying a long chain of fabricated addresses.
5. IPv4 and IPv6 CIDR matching.
6. Malformed IP addresses and invalid CIDR configuration.
7. Empty or missing TRUSTED_PROXIES.
8. Multi-hop proxy chain (right-to-left traversal, ignoring leftmost spoof).
9. Rate limiting from same real client rotating spoofed forwarding headers.
10. Behavior when proxy/app configuration is incomplete or missing.
"""

from api_server import is_trusted_proxy, get_client_ip, rate_limiter
from config import get_trusted_proxies



class DummyClient:
    def __init__(self, host):
        self.host = host


class DummyRequest:
    def __init__(self, host, headers=None):
        self.client = DummyClient(host) if host else None
        self.headers = headers or {}


# Case 1: Direct connection with no forwarding header
def test_case_01_direct_connection_no_forwarding():
    req = DummyRequest("198.51.100.10", headers={})
    assert get_client_ip(req) == "198.51.100.10"


# Case 2: Direct untrusted connection supplying fabricated X-Forwarded-For
def test_case_02_direct_untrusted_connection_fabricated_header(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("TRUSTED_PROXIES", raising=False)
    req = DummyRequest("198.51.100.10", headers={"x-forwarded-for": "8.8.8.8"})
    # Must ignore 8.8.8.8 and return connection peer
    assert get_client_ip(req) == "198.51.100.10"


# Case 3: Trusted proxy supplying expected client address
def test_case_03_trusted_proxy_single_client(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("TRUSTED_PROXIES", "10.0.0.1")
    req = DummyRequest("10.0.0.1", headers={"x-forwarded-for": "203.0.113.50"})
    assert get_client_ip(req) == "203.0.113.50"


# Case 4: Untrusted peer supplying long chain of fabricated addresses
def test_case_04_untrusted_peer_long_fabricated_chain(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("TRUSTED_PROXIES", "10.0.0.1")
    # Peer is 198.51.100.99 (not in TRUSTED_PROXIES)
    req = DummyRequest(
        "198.51.100.99",
        headers={"x-forwarded-for": "1.1.1.1, 2.2.2.2, 3.3.3.3, 10.0.0.1"},
    )
    assert get_client_ip(req) == "198.51.100.99"


# Case 5: IPv4 and IPv6 CIDR matching
def test_case_05_ipv4_and_ipv6_cidr_matching():
    trusted = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "2001:db8::/32", "::1"]
    # IPv4 tests
    assert is_trusted_proxy("10.254.1.1", trusted) is True
    assert is_trusted_proxy("172.20.5.5", trusted) is True
    assert is_trusted_proxy("192.168.1.1", trusted) is True
    assert is_trusted_proxy("192.169.1.1", trusted) is False
    assert is_trusted_proxy("8.8.8.8", trusted) is False

    # IPv6 tests
    assert is_trusted_proxy("2001:db8::1", trusted) is True
    assert is_trusted_proxy("2001:db8:ffff::1", trusted) is True
    assert is_trusted_proxy("2001:db9::1", trusted) is False
    assert is_trusted_proxy("::1", trusted) is True


# Case 6: Malformed IP addresses and invalid CIDR configuration
def test_case_06_malformed_ips_and_invalid_cidr():
    # Invalid CIDR string in list must not crash the matcher
    corrupt_trusted = ["not_an_ip", "10.0.0.1/invalid_mask", "10.0.0.1"]
    assert is_trusted_proxy("10.0.0.1", corrupt_trusted) is True
    assert is_trusted_proxy("10.0.0.2", corrupt_trusted) is False
    assert is_trusted_proxy("malformed_candidate", corrupt_trusted) is False


# Case 7: Empty or missing TRUSTED_PROXIES
def test_case_07_empty_or_missing_trusted_proxies(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("TRUSTED_PROXIES", raising=False)
    assert get_trusted_proxies() == []

    # With empty list, all forwarded headers ignored
    req = DummyRequest("127.0.0.1", headers={"x-forwarded-for": "1.2.3.4"})
    assert get_client_ip(req) == "127.0.0.1"


# Case 8: Multi-hop proxy chain (right-to-left traversal, ignoring leftmost spoof)
def test_case_08_multi_hop_proxy_chain_ignores_leftmost_spoof(monkeypatch):
    """
    Scenario:
    Real client: 203.0.113.50
    Upstream Edge Proxy (e.g. Cloudflare): 173.245.48.5 (trusted)
    Internal Ingress Proxy (Nginx): 10.0.0.1 (trusted)
    FastAPI peer: 10.0.0.1

    Attacker tries to inject '8.8.8.8' into their initial request:
    X-Forwarded-For becomes: "8.8.8.8, 203.0.113.50, 173.245.48.5"

    Right-to-left resolution:
    - 173.245.48.5 is trusted proxy -> step left
    - 203.0.113.50 is NOT trusted proxy -> STOP! This is authentic client.
    - 8.8.8.8 is safely discarded.
    """
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("TRUSTED_PROXIES", "10.0.0.1, 173.245.48.5")

    req = DummyRequest(
        "10.0.0.1",
        headers={"x-forwarded-for": "8.8.8.8, 203.0.113.50, 173.245.48.5"},
    )
    resolved_ip = get_client_ip(req)
    assert resolved_ip == "203.0.113.50"


# Case 9: Rate limiting enforced on real client while rotating spoofed forwarding headers
def test_case_09_rate_limiting_enforced_across_spoofed_forwarding_headers(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("TRUSTED_PROXIES", raising=False)

    attacker_ip = "198.51.100.77"
    key = f"verify_solana:{attacker_ip}"

    # Clear prior window
    rate_limiter._history.pop(key, None)

    # Attacker fires 10 requests rotating fake X-Forwarded-For
    for i in range(10):
        req = DummyRequest(attacker_ip, headers={"x-forwarded-for": f"100.64.0.{i}"})
        ip = get_client_ip(req)
        assert ip == attacker_ip  # Spoofed IP ignored!
        allowed, _ = rate_limiter.is_allowed(f"verify_solana:{ip}", limit=10, window_seconds=60)
        assert allowed is True

    # 11th request from same attacker must be rate limited
    req11 = DummyRequest(attacker_ip, headers={"x-forwarded-for": "100.64.0.99"})
    ip11 = get_client_ip(req11)
    allowed, retry_after = rate_limiter.is_allowed(f"verify_solana:{ip11}", limit=10, window_seconds=60)
    assert allowed is False
    assert retry_after > 0


# Case 10: Incomplete or missing configuration behavior
def test_case_10_missing_request_client_and_malformed_chain(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("TRUSTED_PROXIES", "127.0.0.1")

    # Request has None client
    req_no_client = DummyRequest(None, headers={"x-forwarded-for": "1.2.3.4"})
    # Fails closed to 127.0.0.1 peer default
    assert get_client_ip(req_no_client) == "1.2.3.4"

    # Request through trusted proxy has malformed hop
    req_malformed_hop = DummyRequest("127.0.0.1", headers={"x-forwarded-for": "invalid-ip-hop"})
    assert get_client_ip(req_malformed_hop) == "127.0.0.1"
