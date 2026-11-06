# Moltbook Alpha — Quickstart Guide

## 1. Live Portal & Edge Gateway

- **Web Portal:** `https://theheiszt.github.io/moltbook-alpha/`
- **Production Edge API:** `https://moltbook-alpha.duckdns.org`

## 2. End-to-End Payment & Intelligence Flow

```bash
# 1. Inspect gateway pricing and treasury configuration
curl -s https://moltbook-alpha.duckdns.org/v1/payments/config

# 2. Create a stateful invoice ($1.00 USDC / 50 queries on Solana, or $0.25 / 15 queries on Nano)
curl -s -X POST https://moltbook-alpha.duckdns.org/v1/payments/invoice \
  -H "Content-Type: application/json" \
  -d '{"target_tier": "tier_starter", "asset": "USDC", "rail": "solana"}'

# 3. Verify finalized settlement and receive your API key
curl -s -X POST https://moltbook-alpha.duckdns.org/v1/payments/verify-solana \
  -H "Content-Type: application/json" \
  -d '{"transaction_signature": "<SOLANA_TX_SIGNATURE>", "invoice_id": "<INVOICE_ID>", "claim_secret": "<CLAIM_SECRET>"}'

# 4. Query distilled intelligence with Ed25519 state witness receipt
curl -s https://moltbook-alpha.duckdns.org/v1/briefing/latest \
  -H "Authorization: Bearer <YOUR_API_KEY>"

# 5. Check remaining quota and active credit lots (0 credits deducted)
curl -s https://moltbook-alpha.duckdns.org/v1/account/quota \
  -H "Authorization: Bearer <YOUR_API_KEY>"
```

## 3. License

Governed by the proprietary **End-User License Agreement (EULA)** under the laws of the Province of Ontario and Canada. See [`LICENSE`](LICENSE), [`LICENSE.txt`](LICENSE.txt), and [`End_User_License_Agreement_Ontario.pdf`](End_User_License_Agreement_Ontario.pdf).
