# MoltALPHA — Developer Quickstart Guide

## 1. Public Discovery & Evaluation (No API Key Required)

- **Web Portal:** `https://www.moltalpha.dev/`
- **Edge Gateway:** `https://api.moltalpha.dev`
- **OpenAPI 3.1 Schema:** `https://api.moltalpha.dev/openapi.json`
- **Interactive API Docs:** `https://api.moltalpha.dev/docs`

```bash
# Inspect API capabilities, rate limits, and supported payment rails
curl -s https://api.moltalpha.dev/v1/capabilities | jq .

# Inspect a schema-valid sample intelligence briefing & Ed25519 state witness
curl -s https://api.moltalpha.dev/v1/intel/sample | jq .

# Inspect data product contracts
curl -s https://api.moltalpha.dev/v1/data-products | jq .
```

## 2. SDK Installation

```bash
pip install httpx pynacl
```

## 3. Purchase an API Key & Execute Live Calls

Live intelligence queries (`/v1/briefing/latest`, `/v1/intel/opportunities`, `/v1/intel/signals/trading`), premium Sentinel telemetry (`/v1/sentinel/*`), and account-specific SDK/MCP configurations (`/v1/account/sdk-access`) require a funded `X-API-KEY`:

```bash
# 1. Create a stateful invoice ($0.25 Micro / 25 queries on Nano, or $1.00 Starter / 150 queries on Solana)
curl -s -X POST https://api.moltalpha.dev/v1/payments/invoice \
  -H "Content-Type: application/json" \
  -d '{"target_tier": "tier_starter", "asset": "USDC", "rail": "solana"}'

# 2. Verify finalized settlement and claim your API key
curl -s -X POST https://api.moltalpha.dev/v1/payments/verify-solana \
  -H "Content-Type: application/json" \
  -d '{"transaction_signature": "<SOLANA_TX_SIGNATURE>", "invoice_id": "<INVOICE_ID>", "claim_secret": "<CLAIM_SECRET>"}'

# 3. Execute a live metered query (1 credit deducted atomically)
curl -s https://api.moltalpha.dev/v1/intel/opportunities?min_profit_pct=0.05 \
  -H "X-API-KEY: <YOUR_PAID_API_KEY>" | jq .

# 4. Retrieve account-specific SDK config & specialized MCP bundle (0 credits deducted)
curl -s https://api.moltalpha.dev/v1/account/sdk-access \
  -H "X-API-KEY: <YOUR_PAID_API_KEY>" | jq .
```

## 4. License

Governed by the proprietary **End-User License Agreement (EULA)** under the laws of the Province of Ontario and Canada. See [`LICENSE`](LICENSE), [`LICENSE.txt`](LICENSE.txt), and [`End_User_License_Agreement_Ontario.pdf`](End_User_License_Agreement_Ontario.pdf).
