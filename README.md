# MoltALPHA — Autonomous Intelligence & Risk Portal

[![License: Proprietary EULA](https://img.shields.io/badge/License-Proprietary_EULA_(Ontario)-red.svg)](LICENSE)
[![Portal](https://img.shields.io/badge/Portal-www.moltalpha.dev-0ea5e9.svg)](https://www.moltalpha.dev/)
[![OpenAPI 3.1](https://img.shields.io/badge/OpenAPI_3.1-api.moltalpha.dev%2Fopenapi.json-10b981.svg)](https://api.moltalpha.dev/openapi.json)

Official developer portal and integration reference for **MoltALPHA** (`https://www.moltalpha.dev/`) — autonomous market intelligence, DEX microstructure risk telemetry, cryptographic Ed25519 state witnesses, and multi-rail settlement (Solana USDC/SOL & Zero-Fee Nano).

---

## 🔓 Public Evaluation vs. Paid Execution Matrix

Developers can inspect the full integration surface, schemas, and sample payloads before committing even `$0.25`:

| Resource | Public | Paid | Endpoint / Location |
| :--- | :---: | :---: | :--- |
| **Product overview & API capabilities** | **Yes** | **Yes** | `GET /v1/capabilities`, `GET /v1/quickstart` |
| **Endpoint descriptions & response examples** | **Yes** | **Yes** | `GET /v1/intel/sample`, [`www.moltalpha.dev`](https://www.moltalpha.dev/) |
| **Basic OpenAPI 3.1 schema & docs** | **Yes** | **Yes** | `GET /openapi.json`, `GET /docs` |
| **SDK installation instructions** | **Yes** | **Yes** | See [Quickstart](QUICKSTART.md) & below |
| **Live authenticated API calls** | **No** | **Yes** | `GET /v1/briefing/latest`, `/v1/intel/*`, `/v1/quant/*` |
| **Premium Sentinel telemetry** | **No** | **Yes** | `GET /v1/sentinel/*` (`SENTINEL_MEMBER`+ tier) |
| **Specialized agent / MCP bundles** | **Optional** | **Yes** | `GET /v1/account/sdk-access` (`X-API-KEY` required) |
| **Account-specific SDK configuration** | **No** | **Yes** | `GET /v1/account/sdk-access` (`X-API-KEY` required) |

---

## 💰 Subscription & Access Tiers

| Tier ID | USD Price | Credits Granted | Accepted Rails | Validity |
| :--- | :--- | :--- | :--- | :--- |
| **`tier_micro`** | **$0.25** | 25 queries | Nano (XNO), SOL, USDC (SPL) | Non-expiring |
| **`tier_starter`** | **$1.00** | 150 queries | Nano (XNO), SOL, USDC (SPL) | Non-expiring |
| **`tier_pro`** | **$5.00** | 1,500 queries | SOL, USDC (SPL) | Non-expiring (Unlocks Sentinel Member) |
| **`tier_premium`** | **$20.00** | 10,000 queries | SOL, USDC (SPL) | 30 calendar days (Unlocks Sentinel Pro) |

---

## ⚡ Public Evaluation & SDK Quickstart

### 1. Inspect Capabilities, Sample Briefing & OpenAPI Schema (0 Credits, No Key Required)
```bash
# Inspect machine-readable capabilities & pricing
curl -s https://api.moltalpha.dev/v1/capabilities | jq .

# Fetch a realistic, witness-signed sample briefing payload
curl -s https://api.moltalpha.dev/v1/intel/sample | jq .

# Inspect the OpenAPI 3.1 specification
curl -s https://api.moltalpha.dev/openapi.json | jq .info
```

### 2. SDK Installation & Integration (Python)
```bash
pip install httpx pynacl
```

```python
import httpx

GATEWAY = "https://api.moltalpha.dev"

# 1. Unmetered evaluation (no API key required)
sample = httpx.get(f"{GATEWAY}/v1/intel/sample", timeout=10.0).json()
print("Sample Witness:", sample["state_witness"]["witness_id"])

# 2. Live authenticated execution (requires active paid X-API-KEY)
headers = {"X-API-KEY": "molt_your_active_paid_key"}
opps = httpx.get(
    f"{GATEWAY}/v1/intel/opportunities",
    params={"min_profit_pct": 0.05},
    headers=headers,
    timeout=15.0,
).json()
print(f"Live arbitrage opportunities: {opps['count']}")
```

### 3. Purchase a Key & Unlock Account-Specific SDK / MCP Config
```bash
# 1. Create a stateful invoice ($0.25 Nano or $1.00+ Solana USDC/SOL)
curl -s -X POST https://api.moltalpha.dev/v1/payments/invoice \
  -H "Content-Type: application/json" \
  -d '{"target_tier": "tier_starter", "asset": "USDC", "rail": "solana"}'

# 2. Verify finalized settlement and claim your API key
curl -s -X POST https://api.moltalpha.dev/v1/payments/verify-solana \
  -H "Content-Type: application/json" \
  -d '{"transaction_signature": "<SOLANA_TX_SIG>", "invoice_id": "<INVOICE_ID>", "claim_secret": "<CLAIM_SECRET>"}'

# 3. Retrieve your account-specific SDK configuration & specialized MCP bundle (0 credits deducted)
curl -s https://api.moltalpha.dev/v1/account/sdk-access \
  -H "X-API-KEY: <YOUR_PAID_API_KEY>" | jq .
```

---

## 📄 License

Proprietary End-User License Agreement (EULA) — Governed by the laws of the Province of Ontario and Canada. See [LICENSE](LICENSE), [LICENSE.txt](LICENSE.txt), and [End_User_License_Agreement_Ontario.pdf](End_User_License_Agreement_Ontario.pdf).
