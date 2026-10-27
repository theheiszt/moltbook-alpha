# Conversion Funnel Telemetry & Privacy Specification
**Moltbook Alpha — Commercial Analytics & Funnel Tracking Architecture**
*Document Version:* 1.0.0 | *Last Updated:* 2026-10-27 | *Status:* Implemented & Active

---

## 1. Objectives & Architectural Principles

To transition Moltbook Alpha from a free prototype into a commercially sustainable API platform, we require rigorous, real-time measurement of the developer journey—from prospective evaluation to paying customer and repeat usage.

### Core Tenets
1. **Zero Personally Identifiable Information (PII):** Telemetry must never record IP addresses, user agents with tracking fingerprints, or arbitrary query parameters that could leak customer intelligence.
2. **Strict Cryptographic Credential Redaction:** Never persist raw API keys, claim secrets, or unhashed authentication tokens in analytics.
3. **Public Key Privacy:** Full blockchain wallet addresses are never persisted in analytics; addresses are strictly truncated to a 4-character prefix and 4-character suffix (`7xKX...4bQ`).
4. **Local, Non-Custodial SQLite Persistence:** Telemetry records live in the local, hardened SQLite database on the ProLiant host; no external tracking beacons, third-party analytics scripts, or cloud ad-trackers are ever loaded.

---

## 2. Event Taxonomy & Funnel Lifecycle

The conversion funnel tracks 8 distinct lifecycle events:

```
[1. sample_viewed] (Unmetered Evaluation)
        │
        ▼
[2. invoice_created] (Purchase Intent: Tier / Asset / Rail)
        │
        ▼
[3. payment_verified] (On-Chain Settlement Confirmed)
        │
        ▼
[4. key_delivered] (Immediate Key Mint or Claim Secret Recovery)
        │
        ▼
[5. first_query] (Activation: First Live Paid Request)
        │
        ├───► [6. quota_warning] (Retention Alert: 80% Quota Consumed)
        │            │
        │            ▼
        │     [7. quota_exhausted] (Boundary: 100% Quota Consumed)
        │            │
        └────────────┴──────► [8. topup_purchased] (LTV Expansion: Addon / Renewal)
```

### Event Definitions

| Event Name | Trigger Condition | Emitting Subsystem | Sanitized Properties |
| :--- | :--- | :--- | :--- |
| `sample_viewed` | Developer or agent accesses `GET /v1/intel/sample` without auth. | `api_server.py` | `{"endpoint": "/v1/intel/sample", "user_agent": "..."}` |
| `invoice_created` | Developer requests a payment invoice via `POST /v1/payments/invoice`. | `storage.py` (`create_invoice`) | `{"invoice_id": "...", "tier": "...", "rail": "solana", "asset": "USDC", "amount_raw": 1000000, "credits": 50}` |
| `payment_verified` | Valid on-chain transaction matching invoice reference confirmed. | `storage.py` (`fulfill_invoice_and_redeem`) | `{"invoice_id": "...", "tier": "...", "asset": "USDC", "payer_wallet": "7xKX...4bQ", "credits_granted": 50, "is_topup": false}` |
| `key_delivered` | Raw API key successfully returned to client (at mint or via claim). | `storage.py` (`fulfill_invoice_and_redeem` / `claim_invoice_credential`) | `{"invoice_id": "...", "tier": "...", "delivery_method": "immediate_fulfillment" \| "claim_secret_recovery"}` |
| `first_query` | First paid API query reserved and deducted against key's credit lot. | `storage.py` (`_authenticate_and_deduct_conn`) | `{"key_hash": "a1b2c3d4...", "tier": "tier_starter"}` |
| `quota_warning` | Total credit lot consumption reaches or exceeds 80% threshold. | `storage.py` (`_check_and_record_quota_thresholds_conn`) | `{"key_hash": "a1b2c3d4...", "threshold": 0.80}` |
| `quota_exhausted` | Key balance drops to 0 remaining credits across all active lots. | `storage.py` (`_authenticate_and_deduct_conn`) | `{"key_hash": "a1b2c3d4...", "tier": "tier_starter"}` |
| `topup_purchased` | Existing key purchases additional credit package or renewal. | `storage.py` (`fulfill_invoice_and_redeem`) | `{"invoice_id": "...", "tier": "topup_500", "asset": "USDC", "credits_granted": 500, "key_hash": "a1b2c3d4..."}` |

---

## 3. Database Schema

The `funnel_events` table is created in SQLite with indexed lookup on event names and timestamps:

```sql
CREATE TABLE IF NOT EXISTS funnel_events (
    event_id TEXT PRIMARY KEY,
    event_name TEXT NOT NULL,
    timestamp_utc TEXT NOT NULL,
    properties_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_funnel_events_name_time 
ON funnel_events(event_name, timestamp_utc);
```

---

## 4. Privacy Enforcement Implementation

In `storage.py`, `_record_funnel_event_conn` enforces automatic sanitization on all incoming properties before serialization:

```python
sanitized: Dict[str, Any] = {}
for k, v in props.items():
    # Strip raw credentials and network identifiers
    if k in ("key", "api_key", "secret", "claim_secret", "ip", "client_ip", "ip_address"):
        continue
    # Truncate cryptographic hashes
    if k in ("key_hash", "hash"):
        sanitized[k] = str(v)[:8] + "..." if v else None
        continue
    # Truncate public wallet addresses (preserve start and end for correlation without deanonymization)
    if "wallet" in k or k in ("payer", "payer_wallet", "address"):
        if isinstance(v, str) and len(v) > 8:
            sanitized[k] = f"{v[:4]}...{v[-4:]}"
        else:
            sanitized[k] = v
        continue
    sanitized[k] = v
```

---

## 5. Metrics Exposition & Reporting API

### Internal / Admin Telemetry Endpoint
`GET /v1/metrics/funnel`
- Optional Bearer token authorization (`METRICS_BEARER_TOKEN`).
- Returns real-time aggregate counts and the 25 most recent privacy-sanitized events.

#### Example Request:
```bash
curl -s "https://api.moltbook.xyz/v1/metrics/funnel" | jq .
```

#### Example Response:
```json
{
  "success": true,
  "funnel_metrics": {
    "sample_viewed": 42,
    "invoice_created": 12,
    "payment_verified": 4,
    "key_delivered": 4,
    "first_query": 3,
    "quota_warning": 1,
    "quota_exhausted": 0,
    "topup_purchased": 1,
    "total_events": 67
  },
  "recent_events": [
    {
      "event_id": "fnl_8a9b0c1d2e3f4a5b",
      "event_name": "first_query",
      "timestamp_utc": "2026-10-27T16:35:12.104521+00:00",
      "properties": {
        "key_hash": "a1b2c3d4...",
        "tier": "tier_starter"
      }
    }
  ]
}
```

---

## 6. Key Conversion Performance Indicators (KPIs)

From the raw counts, Antigravity and operators calculate four core conversion ratios:

1. **Evaluation-to-Intent Ratio:**
   $$\text{Intent Rate} = \frac{\text{invoice\_created}}{\text{sample\_viewed}}$$
   *Target Benchmark:* $\ge 15\%$

2. **Checkout Completion Ratio:**
   $$\text{Payment Success Rate} = \frac{\text{payment\_verified}}{\text{invoice\_created}}$$
   *Target Benchmark:* $\ge 60\%$

3. **Activation Ratio:**
   $$\text{Activation Rate} = \frac{\text{first\_query}}{\text{key\_delivered}}$$
   *Target Benchmark:* $\ge 80\%$

4. **Retention / Repeat Usage Ratio:**
   $$\text{Repeat Rate} = \frac{\text{topup\_purchased}}{\text{payment\_verified}}$$
   *Target Benchmark:* $\ge 30\%$
