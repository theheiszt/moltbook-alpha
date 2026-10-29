# Moltbook Alpha & Autonomous Agent Suite 🦞

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg)](https://fastapi.tiangolo.com)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)

An autonomous multi-agent intelligence and decentralized monetization pipeline designed for **[Moltbook](https://www.moltbook.com)** (the AI-only social network) and Web3 micro-settlement rails.

---

## ⚡ Features

1. **Automated Intelligence Scraping (`intel_collector.py`):**
   * Programmatically indexes 5 critical submolts: `m/trading`, `m/crypto`, `m/agentfinance`, `m/builds`, and `m/infrastructure`.
   * Filters signal-dense discussions (order-queue depletion, partial fill resistance, 3PL IRT psychometrics, heartbeat latency derivatives).
   * Generates timestamped markdown executive summaries.

2. **HTTP 402 Monetized Commercial API (`api_server.py`):**
   * Built on **FastAPI + Uvicorn**.
   * Serves real-time distilled briefings to other autonomous agents and human developers.
   * Trustless **Solana Mainnet settlement** (native SOL or canonical SPL USDC).
   * Strict `finalized` commitment verification with multi-provider RPC failover and consensus cross-checking.
   * Automated key minting with ACID transactional SQLite storage, zero backdoors, and sliding window rate limiting.
   * Zero-dependency Prometheus `/metrics` exposition with telemetry cardinality guards.
   * Full documentation: [Customer Onboarding Guide](docs/CUSTOMER_ONBOARDING.md).

3. **Substack / Newsletter Draft Engine (`newsletter_generator.py`):**
   * Automatically compiles scraped alpha into publish-ready editions of *"The Agent Underground: What 140,000+ AI Agents Are Actually Building and Trading"*.

4. **Autonomous Token Infrastructure (`token_manager.py`):**
   * Integrates with the **Clawnch** agent launchpad on **Robinhood Chain** (Chain ID: `4663`).
   * Manages EIP-712 cryptographic launch tickets, zero-fee Bags deployments, and automated fee collections.

---

## 💰 Commercial API & Pricing Tiers

Access is metered via cryptographic API keys minted upon verified on-chain settlement:

| Tier ID | USD Price | Credits Granted | Accepted Rails & Amounts | Expiration & Rules | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`tier_micro`** | **$0.25** | 15 queries | Nano (0.25 XNO / 0.25 raw), SOL (~0.00125 SOL), USDC (0.25 USDC) | Non-expiring | Micro-query defensive checks |
| **`tier_starter`** | **$1.00** | 50 queries | Nano (1 XNO), SOL (~0.005 SOL), USDC (1.00 USDC) | Non-expiring | Developer trial & evaluation |
| **`tier_pro`** | **$5.00** | 300 queries | SOL (~0.025 SOL), USDC (5.00 USDC) | Non-expiring | Autonomous trading agents |
| **`tier_premium`** | **$20.00** | 10,000 queries | SOL (~0.100 SOL), USDC (20.00 USDC) | **30 calendar days** | Fleet-wide access & WebSocket stream |

### Credit Top-Up Packages (For Active Accounts)
- **Top-Up 500:** $8.00 (500 queries, 90-day expiry) — 8 USDC or ~0.040 SOL
- **Top-Up 1500:** $20.00 (1,500 queries, 90-day expiry) — 20 USDC or ~0.100 SOL
- **Top-Up 5000:** $50.00 (5,000 queries, 90-day expiry) — 50 USDC or ~0.250 SOL

* **Solana Treasury:** `BU5zBur46YjnCaY34XGBTJ8KSAG9EExjpZA58wDo7wAx`
* **Canonical USDC Mint:** `EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v`
* **Nano Treasury:** `nano_3t1sxtuxyjgdabj6miwn6st58p8x553i8ybkikoc9ozn7mra7kk71iysfyn1`
* **Detailed Policy:** See **[`docs/CREDIT_AND_ENTITLEMENT_POLICY.md`](docs/CREDIT_AND_ENTITLEMENT_POLICY.md)** and **[`docs/CUSTOMER_ONBOARDING.md`](docs/CUSTOMER_ONBOARDING.md)**.

---

## 🚀 Quickstart

### 1. Prerequisites & Installation
```bash
git clone https://github.com/theheiszt/moltbook-alpha.git
cd moltbook-alpha
pip install -r requirements.txt
pip install -r requirements-dev.txt
cp .env.example .env
```

### 2. Run Test Suite
All tests run offline using synthetic transaction fixtures and mocked RPC endpoints:
```bash
python -m pytest
python -m ruff check .
```

### 3. Start the Commercial API Server
```bash
python api_server.py
```

### 4. Client Integration Example (Curl)
```bash
# 1. Fetch current pricing and treasury wallet
curl -s http://127.0.0.1:8080/v1/payments/config

# 2. Create invoice with Solana Pay reference & claim_secret
curl -X POST http://127.0.0.1:8080/v1/payments/invoice \
  -H "Content-Type: application/json" \
  -d '{"target_tier": "tier_starter"}'

# 3. Verify on-chain payment & mint API key
curl -X POST http://127.0.0.1:8080/v1/payments/verify-solana \
  -H "Content-Type: application/json" \
  -d '{"transaction_signature": "<SOLANA_TX_SIGNATURE>", "invoice_id": "<INVOICE_ID>", "claim_secret": "<CLAIM_SECRET>"}'

# 4. Access latest distilled intelligence briefing (supports X-API-KEY or Bearer)
curl -s http://127.0.0.1:8080/v1/briefing/latest \
  -H "Authorization: Bearer <YOUR_MINTED_API_KEY>"

# 5. Check account quota without burning a credit
curl -s http://127.0.0.1:8080/v1/account/quota \
  -H "Authorization: Bearer <YOUR_MINTED_API_KEY>"

# 6. Scrape Prometheus telemetry (when METRICS_BEARER_TOKEN is configured)
curl -s http://127.0.0.1:8080/metrics \
  -H "Authorization: Bearer <METRICS_BEARER_TOKEN>"

# 6. Run automated end-to-end client demonstration
python examples/client_demo.py --mode mock
```

### 5. Provision and Manage Keys via Administrative CLI
Admin credentials and key management operations run explicitly out-of-band:
```bash
# Provision an administrator key
python cli.py create-admin-key --credits 999999

# Revoke a compromised or inactive key
python cli.py revoke-key --prefix molt_test_

# Inspect recent security audit logs
python cli.py view-audit-logs --limit 20
```

### 6. Configure Credentials
Save your Moltbook API key at `~/.config/moltbook/credentials.json`:
```json
{
  "api_key": "moltbook_sk_xxx",
  "agent_name": "your_agent_name"
}
```

### 7. Run the Collector
```bash
python intel_collector.py
```

---

## 📄 License
MIT License. Created by [@theheiszt](https://github.com/theheiszt) & [@antigravityandrew](https://www.moltbook.com/u/antigravityandrew).
