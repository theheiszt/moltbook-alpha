"""
Generates a fresh suite of payment invoices for Moltbook Alpha pilot members and testing across all rails:
- Solana Starter (0.005 SOL)
- Solana Micro (0.0012 SOL)
- Solana Starter USDC (1.00 USDC)
- Feeless Nano Micro ($0.25 XNO)
- Feeless Nano Starter ($1.00 XNO)
- Solana Pro (0.025 SOL)
"""

import urllib.request
import json
import sys
from typing import Dict, Any, List

sys.stdout.reconfigure(encoding="utf-8")

BASE_URL = "https://mel-tear-diffs-data.trycloudflare.com"

INVOICE_SPECS: List[Dict[str, Any]] = [
    {"target_tier": "tier_starter", "asset": "SOL", "rail": "solana", "label": "Pilot Starter - Solana (0.005 SOL)"},
    {"target_tier": "tier_micro", "asset": "SOL", "rail": "solana", "label": "Pilot Micro - Solana (0.0012 SOL)"},
    {"target_tier": "tier_starter", "asset": "USDC", "rail": "solana", "label": "Pilot Starter - USDC ($1.00)"},
    {"target_tier": "tier_micro", "asset": "XNO", "rail": "nano", "label": "Pilot Micro - Feeless Nano ($0.25)"},
    {"target_tier": "tier_starter", "asset": "XNO", "rail": "nano", "label": "Pilot Starter - Feeless Nano ($1.00)"},
    {"target_tier": "tier_pro", "asset": "SOL", "rail": "solana", "label": "Pilot Pro - Solana (0.025 SOL)"},
]

def create_invoices(base_url: str = BASE_URL) -> List[Dict[str, Any]]:
    results = []
    print(f"Creating fresh invoices via gateway: {base_url}\n")
    for spec in INVOICE_SPECS:
        payload = {
            "target_tier": spec["target_tier"],
            "asset": spec["asset"],
            "rail": spec["rail"],
        }
        req = urllib.request.Request(
            f"{base_url}/v1/payments/invoice",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "MoltbookInvoiceManager/1.0"}
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                data["_label"] = spec["label"]
                results.append(data)
                ref_or_merchant = data.get("reference") or data.get("recipient")
                print(f"[CREATED] {spec['label']}")
                print(f"  Invoice ID: {data.get('invoice_id')}")
                print(f"  Rail:       {data.get('rail')}")
                print(f"  Amount:     {data.get('amount_formatted', data.get('amount_raw'))}")
                print(f"  Reference:  {ref_or_merchant}")
                print(f"  Expires:    {data.get('expires_at')}")
                print(f"  Claim Sec:  {data.get('claim_secret')[:16]}...\n")
        except Exception as e:
            print(f"[FAILED] {spec['label']}: {e}\n")
    return results

if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else BASE_URL
    create_invoices(url)
