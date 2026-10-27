# Moltbook Alpha — Client SDKs & Agent Integration Suite 🦞

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.0+-blue.svg)](https://www.typescriptlang.org/)
[![Model Context Protocol](https://img.shields.io/badge/MCP-Compatible-green.svg)](https://modelcontextprotocol.io)

Official client libraries, Model Context Protocol (MCP) server, and integration tools for consuming **Moltbook Alpha** — the real-time Solana DEX concentrated liquidity microstructure and autonomous agent market intelligence API.

🌐 **Live Gateway & Documentation Portal:** [https://theheiszt.github.io/moltbook-alpha](https://theheiszt.github.io/moltbook-alpha)

---

## ⚡ What is Moltbook Alpha?

Moltbook Alpha provides autonomous agents, algorithmic taker bots, and quantitative researchers with high-frequency market intelligence:
1. **Solana DEX Microstructure Engine:** Real-time Concentrated Liquidity (CLMM) orderbook depth parsing, 50-bps bid-ask imbalance analysis, and flash-loan manipulation detection across Raydium CLMM, Orca Whirlpools, and Meteora DLMM.
2. **Deterministic Manipulation Detectors:** Catch `TICK_VACUUM` liquidity pulls (drains >$50k within $\le 3	ext{s}$) and `SPOOFED_WALL` orders before routing swaps.
3. **Multi-Rail On-Chain Settlement (HTTP 402):** Atomic invoice binding with single-use Ed25519 references for Solana (native SOL / canonical SPL USDC) and zero-fee Nano microqueries ($0.25 USD / 15 credits).
4. **Cryptographic State Witnesses:** Every observation and briefing is anchored with an Ed25519 signature verifiable via `POST /v1/witnesses/verify`.
5. **Real-Time Sub-100ms Streaming:** Low-latency WebSocket delta feed (`/v1/ws/microstructure`) and HMAC-SHA256 signed webhooks (`/v1/webhooks/subscribe`).

---

## 📦 Packages & Components

This public distribution repository contains the client toolkits:

| Directory | Component | Language / Format | Description |
| :--- | :--- | :--- | :--- |
| **[`sdk/`](sdk/)** | `moltbook-alpha-sdk` | Python 3.10+ | Official Python async/sync client library with automatic retry & quota management |
| **[`sdk-ts/`](sdk-ts/)** | `@moltbook/alpha-sdk` | TypeScript / Node.js | Official TypeScript client with type definitions for all intelligence signals |
| **[`mcp/`](mcp/)** | Model Context Protocol Server | Python / Node.js | Seamless MCP integration for Claude Desktop, Cursor, and agent runtimes |
| **[`examples/`](examples/)** | Quickstart Guides | Python | Complete sample workflows for autonomous trading and risk monitoring |
| **[`index.html`](index.html)** | Interactive Portal | Static HTML5 / JS | Interactive documentation, rate discovery, and playground hosted via GitHub Pages |

---

## 🚀 Quickstarts

### 1. Python SDK
```bash
pip install ./sdk
```
```python
from moltbook_intel import MoltbookIntelClient

# Initialize client
client = MoltbookIntelClient(
    base_url="http://10.0.0.190:8080",  # Or your Moltbook Alpha gateway URL
    api_key="molt_your_key_here"
)

# Fetch latest synthesized briefing with Ed25519 witness
briefing = client.get_latest_briefing()
print("Latest Briefing ID:", briefing["briefing_id"])
print("State Witness:", briefing["state_witness_id"])

# Query high-conviction microstructure anomalies
signals = client.get_signals(category="market_microstructure", min_confidence="HIGH")
for s in signals["signals"]:
    print(f"[{s['confidence']}] {s['headline']}")
```

### 2. TypeScript / Node.js SDK
```bash
npm install ./sdk-ts
```
```typescript
import { MoltbookClient } from "@moltbook/alpha-sdk";

const client = new MoltbookClient({
  baseUrl: "http://10.0.0.190:8080",
  apiKey: "molt_your_key_here"
});

async function main() {
  const briefing = await client.getLatestBriefing();
  console.log("Briefing:", briefing.briefing_id);
}
main();
```

### 3. Model Context Protocol (MCP) Server for Agents
Connect Claude Desktop or an AI agent to Moltbook Alpha:
```json
{
  "mcpServers": {
    "moltbook-alpha": {
      "command": "python",
      "args": ["/path/to/moltbook-alpha/mcp/moltbook_mcp.py"],
      "env": {
        "MOLTBOOK_API_KEY": "molt_your_key_here",
        "MOLTBOOK_BASE_URL": "http://10.0.0.190:8080"
      }
    }
  }
}
```

---

## 💰 Settlement Rails & Pricing Tiers

Access is metered via cryptographic API keys minted upon verified on-chain settlement:

| Tier | Price (USD) | Queries / Credits | Settlement Rails | Description |
| :--- | :--- | :--- | :--- | :--- |
| **Micro** | **$0.25** | 15 credits | Nano (XNO, Zero-Fee) | Single-query defensive checks |
| **Starter** | **$1.00** | 50 credits | SOL, SPL USDC, Nano | Pilot evaluation & testing |
| **Pro** | **$5.00** | 300 credits | SOL, SPL USDC | High-frequency quantitative taker bots |
| **Top-Up 500** | **$8.00** | 500 credits | SOL, SPL USDC | Non-expiring quota reserve |
| **Premium** | **$20.00** | 10,000 queries / 30d | SOL, SPL USDC | Full fleet access & sustained WebSocket stream |

* **Solana Treasury:** `BU5zBur46YjnCaY34XGBTJ8KSAG9EExjpZA58wDo7wAx`
* **Canonical USDC Mint:** `EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v`
* **Nano Treasury:** `nano_3moltbookintel111111111111111111111111111111111111111111111111`

---

## 📄 License
This client integration suite is licensed under the [MIT License](LICENSE).
