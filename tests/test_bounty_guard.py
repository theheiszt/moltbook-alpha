"""
Unit tests for BountyGuard Scanner & Escrow Classifier (ops/bounty_guard.py).
"""

from ops.bounty_guard import BountyGuard


def test_classify_safe_with_escrow():
    bg = BountyGuard()
    sample = {
        "title": "[ESCROW BOUNTY] 2,000 DOOM ($wDOOM on Base) — Integrate BountyGuard",
        "body": "Reward 2,000 wDOOM on Base contract 0x623c84A5E04bF715018203334b0eFE41696eBC3E. Verified escrow on doomsday.network.",
        "url": "https://github.com/doomsday-network/bounty-guard/issues/7",
        "comments": 5,
        "created_at": "2026-10-20T00:00:00Z"
    }
    res = bg.classify_bounty(sample)
    assert res["status"] == "SAFE_WITH_ESCROW"
    assert res["confidence"] == "HIGH"
    assert any("escrow" in f.lower() for f in res["flags"])


def test_classify_quarantine_honeypot():
    bg = BountyGuard()
    sample = {
        "title": "Claim $5,000 USDT Free Crypto Bounty Now",
        "body": "Contact me on Telegram https://t.me/fakebot for instant payout!",
        "url": "https://github.com/fake/scam/issues/1",
        "comments": 0,
        "created_at": "2026-10-20T00:00:00Z"
    }
    res = bg.classify_bounty(sample)
    assert res["status"] == "QUARANTINE"
    assert res["confidence"] == "HIGH"
    assert any("honeypot" in f.lower() for f in res["flags"])


def test_classify_safe_no_escrow():
    bg = BountyGuard()
    sample = {
        "title": "Bug in API authentication token parsing",
        "body": "Offering $50 bounty via GitHub for fixing this issue.",
        "url": "https://github.com/example/repo/issues/100",
        "comments": 2,
        "created_at": "2026-10-20T00:00:00Z"
    }
    res = bg.classify_bounty(sample)
    assert res["status"] == "SAFE_NO_ESCROW"


def test_audit_all_generates_outputs(tmp_path):
    test_json = tmp_path / "test_bounties.json"
    test_json.write_text("""[
        {"title": "[ESCROW BOUNTY] 1000 DOOM", "body": "Base contract 0x623c84A5E04bF715018203334b0eFE41696eBC3E", "url": "https://github.com/a/b/1"},
        {"title": "Open issue with $20 reward", "body": "Fix bug", "url": "https://github.com/a/b/2"}
    ]""", encoding="utf-8")

    bg = BountyGuard(bounty_file=test_json)
    res = bg.audit_all()
    assert res["total_audited"] == 2
    assert res["safe_with_escrow"] == 1
    assert res["safe_no_escrow"] == 1
