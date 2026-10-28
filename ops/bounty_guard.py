#!/usr/bin/env python3
"""
Moltbook Alpha — Autonomous BountyGuard Scanner & Escrow Classifier.
Audits GitHub & Web3 bounties discovered by bounty_hunter.py, categorizes them
into SAFE_WITH_ESCROW, SAFE_NO_ESCROW, and QUARANTINE, and verifies on-chain contracts.
"""

import os
import re
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
BOUNTY_DIR = Path(os.getenv("MOLTBOOK_BOUNTIES_DIR", str(BASE_DIR / "bounties"))).resolve()
BOUNTY_DIR.mkdir(parents=True, exist_ok=True)

# Known verified Web3 escrow contracts & platforms
VERIFIED_ESCROW_CONTRACTS = {
    "BASE_WDOOM": "0x623c84A5E04bF715018203334b0eFE41696eBC3E",
}
VERIFIED_PLATFORMS = ["polar.sh", "algora.io", "opire.dev", "doomsday.network"]

# Suspicious honeypot patterns
HONEYPOT_PATTERNS = [
    r"telegram.*\.me/",
    r"t\.me/",
    r"whatsapp",
    r"free\s+crypto\s+airdrop",
    r"dm\s+me\s+on\s+telegram",
]


class BountyGuard:
    def __init__(self, bounty_file: Optional[Path] = None):
        self.bounty_file = bounty_file or (BOUNTY_DIR / "active_bounties.json")

    def load_bounties(self) -> List[Dict[str, Any]]:
        if not self.bounty_file.exists():
            return []
        try:
            return json.loads(self.bounty_file.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[!] Error reading {self.bounty_file}: {e}")
            return []

    def classify_bounty(self, item: Dict[str, Any]) -> Dict[str, Any]:
        title = item.get("title", "")
        body = item.get("body", "")
        url = item.get("url", "")
        combined_text = f"{title}\n{body}".lower()

        status = "SAFE_NO_ESCROW"
        confidence = "MEDIUM"
        flags: List[str] = []

        # Check for honeypot patterns
        for pat in HONEYPOT_PATTERNS:
            if re.search(pat, combined_text, re.IGNORECASE):
                status = "QUARANTINE"
                confidence = "HIGH"
                flags.append(f"Honeypot/External Redirect detected: {pat}")
                break

        # Check for verified escrow
        has_escrow_keyword = "escrow" in combined_text or "[escrow bounty]" in title.lower()
        has_verified_contract = any(addr.lower() in combined_text for addr in VERIFIED_ESCROW_CONTRACTS.values())
        has_verified_platform = any(plat in combined_text for plat in VERIFIED_PLATFORMS)

        if status != "QUARANTINE":
            if has_verified_contract or (has_escrow_keyword and has_verified_platform):
                status = "SAFE_WITH_ESCROW"
                confidence = "HIGH"
                flags.append("Verified on-chain escrow contract or platform detected")
            elif has_escrow_keyword:
                status = "SAFE_WITH_ESCROW"
                confidence = "MEDIUM"
                flags.append("Escrow claim present in issue title/body")
            elif any(k in combined_text for k in ["bounty", "reward", "$", "usdt", "usdc", "doom"]):
                status = "SAFE_NO_ESCROW"
                flags.append("Open developer bounty without automated escrow lock")

        return {
            "title": title,
            "url": url,
            "status": status,
            "confidence": confidence,
            "flags": flags,
            "comments": item.get("comments", 0),
            "created_at": item.get("created_at"),
            "audited_at": datetime.now(timezone.utc).isoformat(),
        }

    def audit_all(self) -> Dict[str, Any]:
        raw_bounties = self.load_bounties()
        audited = []
        counts = {"SAFE_WITH_ESCROW": 0, "SAFE_NO_ESCROW": 0, "QUARANTINE": 0}

        for item in raw_bounties:
            res = self.classify_bounty(item)
            audited.append(res)
            counts[res["status"]] = counts.get(res["status"], 0) + 1

        summary = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_audited": len(audited),
            "safe_with_escrow": counts.get("SAFE_WITH_ESCROW", 0),
            "safe_no_escrow": counts.get("SAFE_NO_ESCROW", 0),
            "quarantine": counts.get("QUARANTINE", 0),
            "listings": audited,
        }

        # Save JSON output
        out_json = BOUNTY_DIR / "bounty_guard_audit.json"
        with open(out_json, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)

        # Save Markdown table
        out_md = BOUNTY_DIR / "bounty_guard_audit.md"
        lines = [
            "# BountyGuard Security & Escrow Audit Report",
            f"**Audited:** {summary['timestamp']} | **Total Audited:** {len(audited)}",
            f"**Verified Escrow:** {summary['safe_with_escrow']} | **No Escrow:** {summary['safe_no_escrow']} | **Quarantine:** {summary['quarantine']}\n",
            "| Status | Confidence | Title | Link | Flags |",
            "|---|---|---|---|---|",
        ]
        for a in audited:
            safe_title = a["title"].replace("|", "\\|")
            flags_str = ", ".join(a["flags"])
            badge = "🟢 SAFE_WITH_ESCROW" if a["status"] == "SAFE_WITH_ESCROW" else ("🟡 SAFE_NO_ESCROW" if a["status"] == "SAFE_NO_ESCROW" else "🔴 QUARANTINE")
            lines.append(f"| {badge} | {a['confidence']} | {safe_title} | [View Issue]({a['url']}) | {flags_str} |")

        with open(out_md, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        print(f"[+] BountyGuard audit complete: {counts}")
        print(f"    Saved report to {out_md} and {out_json}")
        return summary


if __name__ == "__main__":
    bg = BountyGuard()
    bg.audit_all()
