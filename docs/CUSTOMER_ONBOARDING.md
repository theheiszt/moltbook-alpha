# Moltbook Alpha API — Customer Onboarding & Integration Guide 🦞

Welcome to the **Moltbook Alpha Commercial API**. This guide provides autonomous agents, algorithmic trading desks, and developers with everything needed to integrate with our HTTP 402 monetized intelligence pipeline.

---

## 1. Overview & Architecture

The Moltbook Alpha API delivers distilled, high-signal intelligence indexed from the Moltbook ecosystem (the autonomous AI-agent social network), covering submolts like `m/trading`, `m/crypto`, `m/agentfinance`, `m/builds`, and `m/infrastructure`.

Key technical characteristics:
- **Trustless Settlement:** Pay-per-use access settled on Solana mainnet using native SOL or canonical SPL USDC.
- **Instant Key Minting:** Fully automated on-chain verification that mints cryptographic API keys upon settlement without manual human approval.
- **Fail-Closed Finality:** Payments require cryptographic proof of `finalized` commitment on Solana mainnet-beta, with RPC multi-provider failover and consensus verification.
- **Zero Backdoors:** ACID transactional storage in SQLite with WAL mode, SHA-256 hashed API keys, and comprehensive security audit logging.

---

## 2. Pricing Tiers & Conversion Math

Payments are accepted in either **USDC** (canonical SPL token) or **SOL** (native lamports). Tiers are server-authoritative and determined by net on-chain transfer to the official treasury.

| Tier ID | USD Price | Credits Granted | Minimum USDC Transfer | Minimum SOL Transfer |
| :--- | :--- | :--- | :--- | :--- |
| `tier_starter` | **$1.00** | 50 queries | 1,000,000 micro-USDC (1.00 USDC) | 5,000,000 lamports (0.005 SOL) |
| `tier_pro` | **$5.00** | 300 queries | 5,000,000 micro-USDC (5.00 USDC) | 25,000,000 lamports (0.025 SOL) |
| `tier_unlimited` | **$20.00** | 999,999 (Unlimited) | 20,000,000 micro-USDC (20.00 USDC) | 100,000,000 lamports (0.100 SOL) |

### Settlement Parameters
- **Solana Cluster:** `mainnet-beta`
- **Treasury Address:** `DQkseq8m92h9mQbcQjDRSESAxphpAroKjqyGeSAoKCiC`
- **Canonical USDC Mint:** `EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v` (Decimals: 6)
- **Settlement Commitment:** `finalized` (maximum Solana confirmation tier; `confirmed` or `processed` transactions are rejected)
- **Transaction Expiration:** Payments must be verified within 86,400 seconds (24 hours) of block generation.

---

## 3. Step-by-Step Integration Walkthrough

### Step 1: Query Payment Configuration
Fetch current pricing rates and active treasury destination dynamically:

```bash
curl -s http://127.0.0.1:8080/v1/payments/config
```

**Example Response (200 OK):**
```json
{
  "success": true,
  "treasury_wallet": "DQkseq8m92h9mQbcQjDRSESAxphpAroKjqyGeSAoKCiC",
  "accepted_assets": ["SOL", "USDC (Solana SPL)"],
  "pricing_tiers": {
    "tier_starter": {"usd": 1.0, "credits": 50, "usdc_units": 1000000, "sol_lamports": 5000000},
    "tier_pro": {"usd": 5.0, "credits": 300, "usdc_units": 5000000, "sol_lamports": 25000000},
    "tier_unlimited": {"usd": 20.0, "credits": 999999, "usdc_units": 20000000, "sol_lamports": 100000000}
  },
  "verification_guide": "Send SOL/USDC to treasury_wallet and post the signature to /v1/payments/verify-solana"
}
```

---

### Step 2: Broadcast Payment On-Chain
From your Solana wallet or agent keypair, execute a standard SOL or SPL USDC transfer to the treasury address:

```bash
# Example using Solana CLI for a $1 Starter Tier (0.005 SOL):
solana transfer DQkseq8m92h9mQbcQjDRSESAxphpAroKjqyGeSAoKCiC 0.005 \
  --url https://api.mainnet-beta.solana.com \
  --fee-payer ~/.config/solana/id.json
```
Save the resulting base58 transaction signature (e.g. `5ABC...xyz`).

---

### Step 3: Verify Payment & Mint API Key
Post the transaction signature to `/v1/payments/verify-solana`. The server queries Solana RPC nodes, verifies finality, checks recipient and amounts, and mints your API key.

```bash
curl -X POST http://127.0.0.1:8080/v1/payments/verify-solana \
  -H "Content-Type: application/json" \
  -d '{
    "transaction_signature": "5ABC...your_solana_signature...xyz",
    "target_tier": "tier_starter"
  }'
```

**Example Success Response (200 OK):**
```json
{
  "success": true,
  "status": "newly_minted",
  "tx_signature": "5ABC...",
  "asset": "SOL",
  "amount_raw": 5000000,
  "tier": "tier_starter",
  "credits": 50,
  "key_prefix": "molt_live_a1b2c3d4",
  "api_key": "molt_live_a1b2c3d4_9f8e7d6c5b4a3...",
  "message": "Payment verified and API key minted successfully. Store your api_key securely!"
}
```

> [!IMPORTANT]
> **Store `api_key` immediately.** For security, only the SHA-256 hash and non-sensitive `key_prefix` are stored permanently in the database. The raw token cannot be retrieved later. Subsequent requests for the same transaction signature return `status: "already_redeemed"` without exposing the raw secret token.

---

### Step 4: Query the Intelligence Briefing
Authenticate with your minted key via the `x-api-key` header:

```bash
curl -s http://127.0.0.1:8080/v1/briefing/latest \
  -H "x-api-key: molt_live_a1b2c3d4_9f8e7d6c5b4a3..."
```

**Example Response (200 OK):**
```json
{
  "success": true,
  "user_tier": "tier_starter",
  "credits_remaining": 49,
  "briefing_markdown": "# Moltbook Alpha Executive Briefing\n\nGenerated: 2026-10-17T12:00:00Z\n\n## 1. Executive Summary..."
}
```

Each successful request to `/v1/briefing/latest` decrements 1 credit until exhausted (unlimited tier keys never expire or decrement).

---

### Step 5: Check Payment Status / Audit Redemption
Check whether a signature was already redeemed or remains pending:

```bash
curl -s http://127.0.0.1:8080/v1/payments/status/5ABC...your_signature...xyz
```

**Example Response (200 OK):**
```json
{
  "success": true,
  "status": "redeemed",
  "tx_signature": "5ABC...",
  "asset": "SOL",
  "tier": "tier_starter",
  "credits_granted": 50,
  "remaining_credits": 49,
  "key_prefix": "molt_live_a1b2c3d4",
  "is_active": true,
  "redeemed_at": "2026-10-17T17:30:00+00:00"
}
```

---

## 4. Rate Limits & Quotas

The API enforces strict per-IP sliding window rate limits to prevent denial-of-service and RPC exhaustion:

| Endpoint | Method | Rate Limit | Purpose |
| :--- | :--- | :--- | :--- |
| `/v1/briefing/latest` | `GET` | 60 requests / minute | General intelligence queries |
| `/v1/payments/verify-solana` | `POST` | 10 requests / minute | Payment verification & key minting |
| `/v1/payments/status/{signature}` | `GET` | 60 requests / minute | Transaction status lookup |
| `/v1/payments/config` | `GET` | 60 requests / minute | Pricing configuration |
| `/v1/keys/generate-demo` | `POST` | 5 requests / minute | Demo key generation (when enabled) |
| `/metrics` | `GET` | 30 requests / minute | Prometheus metrics scrape |

When a rate limit is exceeded, the server returns **`HTTP 429 Too Many Requests`** with a `Retry-After: <seconds>` header.

---

## 5. HTTP Status Codes & Error Handling

| Status Code | Meaning | Cause | Client Action |
| :--- | :--- | :--- | :--- |
| **200 OK** | Success | Request succeeded. | Process response data. |
| **400 Bad Request** | Verification Failed | Transaction failed on-chain, wrong recipient, insufficient payment, or invalid asset. | Inspect error message. Do **not** blindly retry. |
| **401 Unauthorized** | Invalid API Key | Missing or unknown `x-api-key` header. | Verify key prefix and token. |
| **402 Payment Required** | Credits Depleted | API key has 0 remaining credits. | Purchase a new key via `/v1/payments/verify-solana`. |
| **403 Forbidden** | Key Inactive or Disabled | API key revoked by admin or demo key generation disabled. | Contact admin or generate a paid key. |
| **404 Not Found** | Resource Missing | Briefing not yet generated. | Wait for next collector run. |
| **422 Unprocessable Content** | Validation Error | Malformed Base58 signature or invalid payload syntax. | Correct request parameters. |
| **429 Too Many Requests** | Rate Limit Exceeded | Exceeded requests per minute quota. | Wait for `Retry-After` seconds before retrying. |
| **502 Bad Gateway** | RPC Provider Error | Solana RPC cluster timeout or connection error during failover. | Safe to retry with exponential backoff (1s, 2s, 4s). |

### Safe Retry Strategy
```
+-------------------------------------------------------+
| HTTP 429: Sleep for Retry-After seconds, then retry    |
| HTTP 502: Exponential backoff (1s, 2s, 4s) up to 3x    |
| HTTP 400 / 401 / 402 / 422: DO NOT RETRY (fix payload) |
+-------------------------------------------------------+
```

---

## 6. Key Administration & Forensic Auditing

Administrators can inspect keys, create high-privilege keys, revoke tokens, and inspect audit logs out-of-band using `cli.py`:

```bash
# Generate an admin key (out-of-band)
python cli.py create-admin-key --credits 999999

# Revoke a compromised or obsolete key
python cli.py revoke-key --prefix molt_live_a1b2c3d4

# List all active keys in the database
python cli.py list-keys

# Inspect security audit trail (rate limits, failed payments, redemptions)
python cli.py view-audit-logs --limit 50
```

---

## 7. Commercial Launch Checklist & Readiness

Before opening the API to external paying customers, verify the following operational requirements:

- [x] **Solana Finality Hardening:** Only `finalized` transactions are accepted. `confirmed` and `processed` statuses fail closed.
- [x] **Multi-Provider RPC Failover:** Configured with primary RPC and fallback endpoints with consensus verification.
- [x] **Idempotency & Replay Protection:** Re-submitting the same signature never double-mints credits or creates duplicate database rows.
- [x] **Constant-Time Metrics Security:** `/metrics` endpoint is protected by `METRICS_BEARER_TOKEN` with constant-time comparison.
- [x] **Cardinated Telemetry Defense:** Prometheus metrics clamp unbounded labels, normalize URIs, and strip query parameters.
- [ ] **Production RPC API Keys:** Replace public endpoints with private RPC providers (e.g. Helius, Triton, QuickNode) in `payment_config.json` or `.env` for production volume.
- [ ] **Reverse Proxy SSL:** Run behind Nginx, Caddy, or Cloudflare with TLS termination and DDoS mitigation.
