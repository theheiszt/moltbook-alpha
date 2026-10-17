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

2. **HTTP 402 Monetized API Gateway (`api_server.py`):**
   * Built on **FastAPI + Uvicorn**.
   * Serves real-time distilled briefings to other autonomous agents and human developers.
   * Returns **`402 Payment Required`** with on-chain settlement details when unauthenticated.
   * On-chain **Solana RPC transaction verification** (`POST /v1/payments/verify-solana`) for automated API key minting via SOL/USDC.

3. **Substack / Newsletter Draft Engine (`newsletter_generator.py`):**
   * Automatically compiles scraped alpha into publish-ready editions of *"The Agent Underground: What 140,000+ AI Agents Are Actually Building and Trading"*.

4. **Autonomous Token Infrastructure (`token_manager.py`):**
   * Integrates with the **Clawnch** agent launchpad on **Robinhood Chain** (Chain ID: `4663`).
   * Manages EIP-712 cryptographic launch tickets, zero-fee Bags deployments, and automated fee collections.

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

### 3. Provision and Manage Keys via Administrative CLI
Admin credentials and key management operations run explicitly out-of-band:
```bash
# Provision an administrator key
python cli.py create-admin-key --credits 999999

# Revoke a compromised or inactive key
python cli.py revoke-key --prefix molt_test_

# Inspect recent security audit logs
python cli.py view-audit-logs --limit 20
```

### 4. Configure Credentials
Save your Moltbook API key at `~/.config/moltbook/credentials.json`:
```json
{
  "api_key": "moltbook_sk_xxx",
  "agent_name": "your_agent_name"
}
```

### 5. Run the Collector
```bash
python intel_collector.py
```

### 6. Start the Commercial API Server
```bash
python api_server.py
```

---

## 📄 License
MIT License. Created by [@theheiszt](https://github.com/theheiszt) & [@antigravityandrew](https://www.moltbook.com/u/antigravityandrew).
