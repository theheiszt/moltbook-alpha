# Developer Onboarding & API Integration Plan
**Moltbook Alpha — Autonomous Agent Market Intelligence & Quant Insights**
*Document Version:* 1.2.0 | *Last Updated:* 2026-10-27 | *Status:* Production Ready

---

## Executive Summary

The **Moltbook Alpha API** delivers structured, timestamped, cryptographically-witnessed market intelligence directly to AI agents, trading bots, and quant pipelines. It bridges the gap between raw decentralized protocol activity (Solana concentrated liquidity microstructure, tick vacuums, pool skew) and verified social/agentic protocol alpha.

This plan provides developers and autonomous AI agents with an end-to-end, friction-free integration pathway:
1. **Zero-Friction Evaluation:** Inspect live, schema-valid briefings instantly via the unmetered sample endpoint (`GET /v1/intel/sample`) without registration or upfront cost.
2. **Deterministic Micropayments:** Create stateful invoices, pay via Solana Pay (USDC/SOL) or zero-fee Nano (XNO), and mint API credentials with zero human intervention.
3. **Cryptographic State Assurances:** Validate every insight against Ed25519 witness state proofs and Atlas Provenance Guard records.
4. **Complete Multi-Language SDKs:** Drop-in integration for Python, TypeScript/Node.js, and raw cURL.

---

## 1. Quick Start: Zero-Friction Evaluation (No Key Required)

Autonomous agents and developers can evaluate the exact JSON schema and payload structure immediately without creating an invoice or burning credits.

### Unmetered Sample Endpoint: `GET /v1/intel/sample`
- **Authentication:** None required.
- **Rate Limit:** 60 requests/minute per IP.
- **Cost:** 0 credits.

```bash
# Evaluate sample market briefing via cURL
curl -s -X GET "https://api.moltbook.xyz/v1/intel/sample" | jq .
```

#### Sample Response Payload:
```json
{
  "success": true,
  "sample": true,
  "mode": "evaluation_unmetered",
  "generated_at": "2026-10-27T16:30:00Z",
  "credits_remaining": "unmetered",
  "briefing_markdown": "# Moltbook Alpha Intelligence Briefing [SAMPLE EVALUATION]\n\n## Executive Summary\nSynthesized market telemetry across Solana concentrated liquidity pools...",
  "signals": [
    {
      "signal_id": "sig_sample_001",
      "category": "dex_microstructure",
      "confidence": "HIGH",
      "title": "Orca Whirlpool SOL-USDC Tick Vacuum Detected",
      "summary": "Sub-tick volume divergence identified at lower tick boundary indicating upward volatility squeeze.",
      "sources": [
        {
          "source_name": "Orca Whirlpool",
          "source_type": "dex_clmm",
          "pool_id": "7qbRF6YsyGuLUVs6Y1q64bdVrfe4ZcUUz1JRdoVNUJnm",
          "verified": true
        }
      ],
      "observed_at": "2026-10-27T16:25:00Z"
    }
  ],
  "microstructure_summary": {
    "tracked_pools": 3,
    "anomalies_detected": 1,
    "aggregate_depth_usd_50bps": 14250000.00
  },
  "state_witness": {
    "action": "SAMPLE_EVALUATION",
    "witness_id": "wit_sample_e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "canonical_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "verified": true
  },
  "documentation_url": "https://theheiszt.github.io/moltbook-alpha",
  "api_status_url": "/v1/health",
  "pricing_url": "/v1/payments/config"
}
```

---

## 2. Canonical Pricing & Entitlement Matrix

| Tier Identifier | Display Name | Cost | Asset Rails | Allowance | Effective Duration | Renewal Model |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `tier_micro` | **Micro / Nano** | **$0.25** | Nano (XNO) zero-fee | 15 queries | Non-expiring balance | On-demand top-up |
| `tier_starter` | **Starter** | **$1.00** | USDC / SOL / XNO | 50 queries | Non-expiring balance | On-demand top-up |
| `tier_pro` | **Pro / Quant** | **$5.00** | USDC / SOL / XNO | 300 queries | Non-expiring balance | On-demand top-up |
| `tier_premium` | **Enterprise / Fleet** | **$20.00** | USDC / SOL / XNO | 10,000 queries | **30 Calendar Days** | Monthly renewal |

### Credit Top-Up Packages (Targeting Existing API Keys)
- `topup_500`: **$8.00** / 500 queries (Valid 90 days)
- `topup_1500`: **$20.00** / 1,500 queries (Valid 90 days)
- `topup_5000`: **$50.00** / 5,000 queries (Valid 90 days)

---

## 3. End-to-End Onboarding Runbook

### Step 1: Create a Payment Invoice
Autonomous agents and developers request a cryptographically bound invoice with an ephemeral Solana Pay reference and client-held `claim_secret`.

```bash
curl -s -X POST "https://api.moltbook.xyz/v1/payments/invoice" \
  -H "Content-Type: application/json" \
  -d '{
    "target_tier": "tier_starter",
    "asset": "USDC",
    "rail": "solana"
  }' | jq .
```

**Response:**
```json
{
  "success": true,
  "invoice_id": "inv_9b8c2f104d",
  "reference": "7d9...unique_pubkey",
  "target_tier": "tier_starter",
  "credits": 50,
  "asset": "USDC",
  "amount_raw": 1000000,
  "recipient": "MOLT...TREASURY_PUBKEY",
  "claim_secret": "sec_8f7b...SAVE_THIS_LOCALLY",
  "solana_pay_url": "solana:MOLT...?amount=1.00&spl-token=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v&reference=7d9...",
  "verify_endpoint": "POST /v1/payments/verify-solana",
  "expires_at": "2026-10-27T17:00:00Z"
}
```
> [!IMPORTANT]
> **Retain the `claim_secret`!** The API server only stores a SHA-256 hash of this secret. If your client loses its API key or drops its connection during settlement, the `claim_secret` allows instant, zero-knowledge key recovery via `POST /v1/payments/invoice/:id/claim`.

### Step 2: Settle On-Chain Payment
Transfer the exact asset amount including the `reference` public key in the Solana transaction accounts:
- **USDC Transfer:** 1.00 USDC to treasury with `reference` pubkey.
- **Solana Mobile / Phantom:** Simply scan or open the `solana_pay_url`.

### Step 3: Verify Payment & Mint API Key
Submit the transaction signature alongside your invoice and claim secret:

```bash
curl -s -X POST "https://api.moltbook.xyz/v1/payments/verify-solana" \
  -H "Content-Type: application/json" \
  -d '{
    "invoice_id": "inv_9b8c2f104d",
    "claim_secret": "sec_8f7b...",
    "tx_signature": "5vK...solana_tx_signature"
  }' | jq .
```

**Response:**
```json
{
  "success": true,
  "status": "newly_minted",
  "api_key": "molt_sol_9a8b7c6d5e4f3a2b1c0d",
  "key_prefix": "molt_sol_9a8b...",
  "tier": "tier_starter",
  "credits": 50,
  "message": "Payment confirmed! Minted 50 credits."
}
```

### Step 4: Make Your First Paid Query
Query the live market briefing using your freshly minted API key:

```bash
curl -s -X GET "https://api.moltbook.xyz/v1/intel/latest" \
  -H "X-API-Key: molt_sol_9a8b7c6d5e4f3a2b1c0d" | jq .
```

**Response:**
```json
{
  "success": true,
  "user_tier": "starter",
  "credits_remaining": 49,
  "briefing_markdown": "# Moltbook Alpha Intelligence Briefing\n...",
  "state_witness_id": "wit_20261027_a8b9c0d1e2"
}
```

### Step 5: Check Remaining Quota & Entitlement Status
Inspect your real-time balance, lot expiration, and consumption warnings:

```bash
curl -s -X GET "https://api.moltbook.xyz/v1/account/quota" \
  -H "X-API-Key: molt_sol_9a8b7c6d5e4f3a2b1c0d" | jq .
```

---

## 4. Multi-Language SDK Code Examples

### 4.1 Python 3 (`requests` or SDK)

```python
import os
import requests

API_BASE = os.getenv("MOLTBOOK_API_URL", "https://api.moltbook.xyz")
API_KEY = os.getenv("MOLTBOOK_API_KEY", "molt_sol_your_api_key_here")

def fetch_market_briefing():
    """Fetches the latest cryptographically-verified market briefing."""
    headers = {
        "X-API-Key": API_KEY,
        "Accept": "application/json",
    }
    response = requests.get(f"{API_BASE}/v1/intel/latest", headers=headers, timeout=10)
    
    if response.status_code == 200:
        data = response.json()
        print(f"[+] Briefing received! Remaining credits: {data.get('credits_remaining')}")
        print(f"[+] State Witness ID: {data.get('state_witness_id')}")
        return data["briefing_markdown"]
    elif response.status_code == 402:
        print("[!] 402 Payment Required: Balance exhausted or invalid tier.")
        print(response.json())
    else:
        print(f"[-] API error ({response.status_code}): {response.text}")
        response.raise_for_status()

if __name__ == "__main__":
    briefing = fetch_market_briefing()
```

### 4.2 TypeScript / Node.js (`fetch` / SDK)

```typescript
import { MoltbookClient } from "./sdk-ts/src";

async function main() {
  const client = new MoltbookClient({
    baseUrl: process.env.MOLTBOOK_API_URL || "https://api.moltbook.xyz",
    apiKey: process.env.MOLTBOOK_API_KEY || "molt_sol_your_api_key_here",
  });

  try {
    // 1. Fetch latest briefing
    const briefing = await client.getLatestBriefing();
    console.log(`[+] Credits remaining: ${briefing.credits_remaining}`);
    console.log(`[+] State witness ID: ${briefing.state_witness_id}`);

    // 2. Fetch DEX Microstructure anomalies
    const micro = await client.getMicrostructure({ depthBps: 50.0 });
    console.log(`[+] Tracked pools: ${micro.pools.length}`);
    for (const anomaly of micro.anomalies) {
      console.log(`[!] Alert on ${anomaly.pool_id}: ${anomaly.type} (${anomaly.severity})`);
    }
  } catch (error: any) {
    console.error(`[-] API Request failed: ${error.message}`);
  }
}

main();
```

---

## 5. Machine-Readable Error Contract & Recovery Taxonomy

Every error returned by the Moltbook Alpha API strictly complies with **RFC 7807 (Problem Details for HTTP APIs)** and includes machine-readable recovery semantics.

| HTTP Code | Error Code Identifier | Retryable? | Operation Outcome | Recovery Action for Agents |
| :--- | :--- | :--- | :--- | :--- |
| `400` | `INVALID_PAYLOAD` | No | `NOT_COMMITTED` | Validate JSON payload against schema; do not retry without schema fix. |
| `400` | `INSUFFICIENT_FUNDS` | No | `NOT_COMMITTED` | Transaction amount below required tier minimum. Submit invoice difference or create new invoice. |
| `402` | `PAYMENT_REQUIRED` | No | `NOT_COMMITTED` | Key balance is 0 or unauthenticated. Call `POST /v1/payments/invoice` to buy credits. |
| `402` | `ENTITLEMENT_EXPIRED` | No | `NOT_COMMITTED` | 30-day Premium window elapsed. Renew subscription via `POST /v1/payments/invoice`. |
| `403` | `KEY_REVOKED` | No | `NOT_COMMITTED` | Key disabled by administrator. Contact support or mint new key. |
| `404` | `INVOICE_NOT_FOUND` | No | `NOT_COMMITTED` | Check `invoice_id` formatting or generate a fresh invoice. |
| `409` | `PAYMENT_ALREADY_REDEEMED`| No | `IDEMPOTENT_REPLAY` | Transaction signature previously settled. Reuse existing minted key or recover via `claim_secret`. |
| `429` | `RATE_LIMIT_EXCEEDED` | Yes | `NOT_COMMITTED` | Token bucket limit reached. Back off by `Retry-After` seconds. |
| `429` | `CONCURRENCY_LIMIT_REACHED`| Yes | `NOT_COMMITTED` | >5 requests active concurrently for this key. Await pending request completion. |
| `502` | `RPC_GATEWAY_ERROR` | Yes | `INDETERMINATE` | Solana RPC temporarily degraded. Poll `/v1/payments/invoice/:id` with exponential backoff. |
| `503` | `CIRCUIT_BREAKER_ACTIVE` | Yes | `NOT_COMMITTED` | Upstream data provider unhealthy. Retry in 15-30 seconds. |

---

## 6. Setting Up Real-Time Webhooks

Rather than polling `/v1/intel/latest`, agents can register HTTP webhooks to receive push notifications whenever high-confidence signals or DEX microstructure manipulation anomalies are detected.

```bash
curl -s -X POST "https://api.moltbook.xyz/v1/webhooks/subscribe" \
  -H "X-API-Key: molt_sol_your_api_key_here" \
  -H "Content-Type: application/json" \
  -d '{
    "target_url": "https://my-trading-agent.internal/webhooks/moltbook",
    "secret_token": "whsec_supersecuresecrettoken",
    "subscribed_events": ["SIGNAL_ALERT", "MICROSTRUCTURE_ANOMALY"],
    "min_severity": "HIGH"
  }' | jq .
```

---

## 7. Zero-Knowledge Credential Recovery

If an agent or developer process crashes after submitting an on-chain transaction:
1. Call `POST /v1/payments/invoice/:invoice_id/claim`.
2. Provide the `claim_secret` generated during invoice creation.
3. The server validates the HMAC hash and returns the decrypted API key.
4. No admin intervention or custodial wallet access is required.
