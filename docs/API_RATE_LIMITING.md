# Moltbook Alpha — API Rate Limiting, Quota Hardening & Agent Recovery Specification

## Executive Summary

This document specifies the rate limiting, concurrency bounding, transactional quota reservation, and agent recovery architecture implemented in Moltbook Alpha API.

Moltbook Alpha provides real-time market intelligence and quantitative signals to autonomous trading agents and DeFi protocols. Autonomous agents operating in unconstrained feedback loops present distinct reliability challenges: rapid burst loops, high concurrency spikes, double-spending through race conditions, and catastrophic downstream crashes upon quota exhaustion.

The architecture documented herein addresses these failure modes through defense-in-depth:
1. **Separation of Concerns:** Short-term rate limiting is decoupled from monthly entitlement accounting.
2. **Token Bucket Rate Limiting:** Enforces an instantaneous burst ceiling (5 req) with sustained refill (60 req/min) per authenticated API key across distributed worker processes via SQLite WAL coordination.
3. **Concurrency Limiting:** Enforces a maximum of 5 concurrent execution slots per API key with automatic reaping of stale slots.
4. **Two-Phase Quota Reservation:** Replaces simple deduction with atomic `reserve` -> `execute` -> `settle` / `release` mechanics, preventing concurrent overspend and eliminating double charging via idempotency deduplication.
5. **Standardized Error Taxonomy:** Returns machine-readable JSON error payloads with `RATE_LIMITED` (HTTP 429) and `ENTITLEMENT_EXHAUSTED` (HTTP 402) while maintaining 100% backward compatibility with legacy clients.
6. **Early Warning Thresholds:** Tracks consumption milestones at 50%, 80%, 90%, and 95% with strict deduplication.
7. **Agent SDK Graceful Recovery:** Equips `sdk/moltbook_intel` with jittered exponential backoff for 429s, immediate non-retry termination for 402s, and automatic idempotency key propagation.

---

## 1. System Architecture & Component Interaction

```
                       +---------------------------------------+
                       |        Autonomous Agent / SDK         |
                       +---------------------------------------+
                                           |
                                 1. Authenticated Request
                                    (X-API-KEY / Bearer,
                                     Idempotency-Key)
                                           v
+-----------------------------------------------------------------------------------+
|                         Moltbook Alpha Perimeter Middleware                       |
|                                                                                   |
|   +--------------------------+   +-----------------------+   +----------------+   |
|   | 30s Execution Timeout    |   | Trusted Proxy Filter  |   | Request ID Gen |   |
|   +--------------------------+   +-----------------------+   +----------------+   |
|                                          |                                        |
|                                          v                                        |
|   +---------------------------------------------------------------------------+   |
|   |            Token Bucket Rate Limiter (Burst: 5, Sustained: 60/min)        |   |
|   |            - Rejects burst flooding (HTTP 429 RATE_LIMITED)               |   |
|   |            - Emits X-RateLimit-Limit, Remaining, Reset headers            |   |
|   +---------------------------------------------------------------------------+   |
|                                          |                                        |
|                                          v                                        |
|   +---------------------------------------------------------------------------+   |
|   |            Concurrency Limiter (Max 5 In-Flight Slots per Key)            |   |
|   |            - Rejects concurrency exhaustion (HTTP 429 RATE_LIMITED)       |   |
|   +---------------------------------------------------------------------------+   |
|                                          |                                        |
|                                          v                                        |
|   +---------------------------------------------------------------------------+   |
|   |            Two-Phase Quota Reservation & Idempotency Check                |   |
|   |            1. Check Idempotency Key -> Return cached if settled           |   |
|   |            2. Atomic Quota Reserve -> Earliest-Deadline-First (EDF)       |   |
|   +---------------------------------------------------------------------------+   |
|                                          |                                        |
|                                          v                                        |
|   +---------------------------------------------------------------------------+   |
|   |            Briefing & Signal Generation Core (Reports / Witnesses)        |   |
|   +---------------------------------------------------------------------------+   |
|                         /                                 \                       |
|                Success /                                   \ Failure / Timeout    |
|                       v                                     v                     |
|   +-----------------------------------+     +---------------------------------+   |
|   | Settle Quota Reservation          |     | Release Quota Reservation       |   |
|   | - Mark 'settled' in DB            |     | - Refund credit to lot & key    |   |
|   | - Cache response for idempotency  |     | - Record 'refund' ledger event  |   |
|   | - Trigger threshold warnings      |     | - Mark 'released' in DB         |   |
|   +-----------------------------------+     +---------------------------------+   |
+-----------------------------------------------------------------------------------+
                                           |
                                  Response / Headers
                                           v
                       +---------------------------------------+
                       |        Autonomous Agent / SDK         |
                       +---------------------------------------+
```

---

## 2. Separation of Entitlements and Rate Limits

Moltbook Alpha strictly decouples long-term paid entitlements from short-term traffic shaping:

| Dimension | Monthly Entitlement (Commercial Access) | Rate Limiting (Traffic Shaping) |
| :--- | :--- | :--- |
| **Time Horizon** | Rolling 30-day window from activation / renewal. | 1-second burst window; 60-second sliding refill. |
| **Accounting Metric** | Paid query credits (e.g., 10,000 for Premium, 300 for Pro). | Request tokens and active concurrency slots. |
| **Renewal Trigger** | On-chain Solana payment verification (SOL / USDC). | Continuous mathematical refill (token bucket). |
| **Zero Balance Impact** | HTTP 402 `ENTITLEMENT_EXHAUSTED` (non-retryable). | HTTP 429 `RATE_LIMITED` (retryable with backoff). |
| **Customer Balances**| Unexpired top-up credits survive; allowance resets. | Tokens reset continuously; non-accumulative past burst. |

### Rolling 30-Day Entitlement Preservation
- Entitlements are tied to the customer's activation timestamp (`activated_at`) and roll forward by 30 days (`expires_at = activated_at + 30 days`).
- The system **never** silently converts rolling 30-day entitlements into calendar-month quotas.
- Existing customer balances and lot lifecycles remain completely intact.

---

## 3. Rate Limiting & Concurrency Architecture

### Rate Limit Configuration Defaults
Configured via `config.py` and environment overrides:

| Parameter | Environment Variable | Default | Purpose |
| :--- | :--- | :--- | :--- |
| **Sustained Rate** | `RATE_LIMIT_SUSTAINED_PER_MIN` | `60` | Sustained throughput per API key (1.0 token/sec). |
| **Burst Capacity** | `RATE_LIMIT_BURST_CAPACITY` | `5` | Maximum instantaneous token reserve per key. |
| **Max Concurrency**| `RATE_LIMIT_MAX_CONCURRENT` | `5` | Maximum concurrent in-flight requests per key. |
| **Request Timeout** | `REQUEST_TIMEOUT_SECONDS` | `30.0`| Execution deadline per request. |
| **Threshold Alerts**| `QUOTA_WARNING_THRESHOLDS` | `0.50, 0.80, 0.90, 0.95` | Proactive exhaustion notification levels. |

### Token Bucket Mechanics & Burst Interaction
The rate limiter implements the classic Token Bucket algorithm:
- Bucket capacity $B = 5$ tokens.
- Refill rate $R = 60 \text{ tokens/minute} = 1.0 \text{ token/second}$.
- Each incoming request consumes 1.0 token.

**Interaction Dynamics:**
1. **Idle Client:** When a client has been idle for $\ge 5$ seconds, their bucket is full at 5 tokens.
2. **Instantaneous Burst:** The client can execute 5 requests concurrently or within milliseconds. All 5 are granted immediately.
3. **Sustained Operation:** Once the 5 burst tokens are spent, remaining tokens are 0. The bucket refills at exactly 1.0 token per second. Subsequent requests are granted at a steady pace of 1 req/sec.
4. **Rejection & Retry-After:** If an agent submits a 6th request immediately with 0 tokens available, the request is rejected with HTTP 429. The required `Retry-After` is calculated as $\lceil \frac{\text{cost} - \text{available}}{\text{refill\_rate}} \rceil = 1 \text{ second}$.

### Multi-Worker SQLite Coordination
In multi-worker production deployments (such as Uvicorn or systemd worker pools on Ubuntu ProLiant), rate limits are enforced across instances using transactional SQLite WAL state:
- Table: `rate_limit_tokens(key TEXT PRIMARY KEY, tokens REAL, last_refill REAL)`.
- Updates use `ON CONFLICT(key) DO UPDATE` to ensure atomic token deductions across operating system processes.
- An in-memory fast path protects against disk saturation during high-frequency checks.

### Fail-Open / Fail-Closed Policy
- **Policy:** Configurable per endpoint risk profile (`fail_open=True` by default for high-availability read endpoints).
- If the database is temporarily unreachable, `TokenBucketRateLimiter(fail_open=True)` grants the request to prevent customer outages, while logging an operational warning.
- If initialized with `fail_open=False` (e.g., for high-risk write endpoints), failures safely fail-closed, returning HTTP 429 with retry guidance.

---

## 4. Concurrency Limiter

Autonomous agents frequently execute multi-threaded or asynchronous task runners. If an agent fires 20 parallel requests, unconstrained concurrency can starve worker threads and deplete shared DB connections.

### Mechanics:
- Table: `rate_limit_concurrency(slot_id TEXT PRIMARY KEY, key TEXT, acquired_at REAL, expires_at REAL)`.
- Prior to request execution, the client key must acquire an active slot.
- Active in-flight slots are bounded by `DEFAULT_RATE_LIMIT_MAX_CONCURRENT = 5`.
- If 5 slots are already held by the key, the 6th request is rejected immediately with HTTP 429:
  ```json
  {
    "error": {
      "code": "RATE_LIMITED",
      "message": "Maximum concurrent requests reached (5). Please back off and retry.",
      "retryable": true,
      "retry_after_seconds": 1
    }
  }
  ```
- Upon request completion (or exception), the slot is explicitly released in a `finally:` block.
- Stale slots (from killed processes or lost connections) are automatically reaped using `expires_at = now + ttl_seconds` (default TTL: 60s).

---

## 5. Two-Phase Quota Reservation & Concurrency Safety

### The Concurrency Overspend Vulnerability
In a naive read-modify-write quota system, if an API key has 1 credit remaining and submits 5 simultaneous requests:
1. All 5 requests read `credits = 1`.
2. All 5 requests succeed in parallel.
3. Balance drops to negative or charges multiple downstream actions for a single paid query.

### The Two-Phase Reservation Protocol
Moltbook Alpha solves this using an atomic reservation lifecycle:

```
[Incoming Request]
       |
       v
1. Reserve Phase:
   - Check Idempotency Key -> Return cached response if already settled
   - Atomic conditional deduction:
     `UPDATE credit_lots SET credits_remaining = credits_remaining - 1 WHERE lot_id = ? AND credits_remaining > 0`
     `UPDATE api_keys SET credits = credits - 1 WHERE key_hash = ? AND credits > 0`
   - Insert row in `quota_reservations` with status = 'reserved', expires_at = now + 60s
   - Record 'deduct' event in `credit_ledger_events`
       |
       v
2. Execute Phase:
   - Read report / briefing, generate cryptographic witness
       |
       +------------------------------------+
       |                                    |
   (Success)                            (Failure)
       |                                    |
       v                                    v
3a. Settle Phase:                    3b. Release Phase:
   - UPDATE `quota_reservations`        - UPDATE `quota_reservations`
     SET status = 'settled',              SET status = 'released'
     response_cache = <payload>         - Restore credit to lot & key:
   - Evaluate threshold alerts            `credits_remaining = credits_remaining + 1`
                                        - Record 'refund' in ledger
```

### Idempotency Deduplication
- Clients can provide an `Idempotency-Key` or `X-Idempotency-Key` header (e.g., UUIDv4).
- **Settled Replay:** If an identical key was previously settled, the server returns the cached response payload immediately without deducting any credit.
- **In-Flight Protection:** If an identical key is currently executing, the server rejects the concurrent duplicate with HTTP 429 (`"A request with this idempotency key is currently in flight"`), preventing duplicate processing.

### Mathematical Balance Invariant
At all times, the system satisfies:
$$\text{granted} + \text{refunded} - \text{deducted} - \text{expired} = \text{remaining active credits}$$
Verified programmatically via `storage.verify_ledger_balance(key_hash)`.

---

## 6. Standardized Machine-Readable Error Taxonomy

Error responses are standardized to deliver predictable, machine-parseable metadata for autonomous agents:

### HTTP 429 — `RATE_LIMITED`
Emitted when client requests exceed short-term token-bucket capacity or maximum concurrency:
```http
HTTP/1.1 429 Too Many Requests
Content-Type: application/json
Retry-After: 5
X-RateLimit-Limit: 60
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 5

{
  "code": "RATE_LIMIT_EXCEEDED",
  "message": "Request rate exceeded.",
  "retryable": true,
  "retry_after": 5,
  "request_id": "req_8f192bca7e10",
  "docs_url": "https://api.moltbook.com/docs/errors#RATE_LIMITED",
  "detail": "Request rate exceeded. Please retry in 5 seconds.",
  "error": {
    "code": "RATE_LIMITED",
    "message": "Request rate exceeded.",
    "retryable": true,
    "retry_after_seconds": 5
  }
}
```

### HTTP 402 — `ENTITLEMENT_EXHAUSTED`
Emitted when an API key's paid quota or 30-day entitlement has depleted:
```http
HTTP/1.1 402 Payment Required
Content-Type: application/json

{
  "code": "CREDITS_EXHAUSTED",
  "message": "Key credits exhausted. Top up your balance via Solana USDC.",
  "retryable": false,
  "request_id": "req_10ab9c87d2ef",
  "docs_url": "https://api.moltbook.com/docs/errors#ENTITLEMENT_EXHAUSTED",
  "detail": "Key credits exhausted. Top up your balance via Solana USDC.",
  "error": {
    "code": "ENTITLEMENT_EXHAUSTED",
    "message": "Key credits exhausted. Top up your balance via Solana USDC.",
    "retryable": false,
    "retry_after_seconds": null
  }
}
```

*Note: The dual representation provides modern agent parsing (`response.json()["error"]["code"]`) while maintaining 100% backward compatibility for legacy clients asserting top-level `code` and `detail`.*

---

## 7. Usage Visibility & Threshold Warning Engine

### Non-Deducting Inspection: `GET /v1/account/quota`
Agents can inspect their account state at any time without burning credits:

```json
{
  "success": true,
  "tier": "tier_premium",
  "credits_remaining": 8420,
  "is_active": true,
  "low_credit_warning": false,
  "entitlement": {
    "tier": "tier_premium",
    "status": "active",
    "expires_at": "2026-11-17T05:30:00+00:00",
    "days_remaining": 29.8
  },
  "usage": {
    "quota_limit": 10000,
    "consumed": 1580,
    "remaining": 8420,
    "percent_consumed": 15.8,
    "warning_threshold_crossed": null,
    "active_alerts": [],
    "configured_thresholds": [0.5, 0.8, 0.9, 0.95]
  },
  "rate_limit_state": {
    "sustained_limit_per_min": 60,
    "burst_capacity": 5,
    "max_concurrent": 5,
    "remaining_tokens": 4.85,
    "in_flight_requests": 0,
    "retry_after_seconds": 0
  }
}
```

### Threshold Warning Deduplication
Configured warning thresholds: `50%`, `80%`, `90%`, and `95%`.
- When an account crosses a threshold milestone (e.g. 50% consumed), an alert is recorded in `quota_threshold_alerts` and the audit log.
- **Deduplication:** Subsequent requests within the 50%-79% band do NOT emit duplicate alerts.
- When the entitlement is renewed via payment verification, `DELETE FROM quota_threshold_alerts WHERE key_hash = ?` resets the warning milestones for the next billing cycle.

---

## 8. Agent SDK Graceful Recovery (`sdk/moltbook_intel`)

The official Python Client SDK (`sdk/moltbook_intel`) embeds hardened recovery algorithms:

### 1. HTTP 429 Handling: Exponential Backoff with Jitter
- Extracts `Retry-After` header or `error.retry_after_seconds` from body.
- Adds randomized jitter ($\pm 50 \text{ ms}$ to $250 \text{ ms}$) to prevent the **thundering herd problem** when multiple agents wake up simultaneously.
- If no header is present, computes exponential backoff: $t_{\text{sleep}} = \min(15.0, 1.5^{\text{retry}}) \pm \text{jitter}$.
- Bounded by a total retry deadline (`retry_deadline = 30.0` seconds).

### 2. HTTP 402 Handling: Immediate Non-Retry Termination
- Raises `EntitlementExhaustedError` on the first encounter.
- **Never retries** an exhausted entitlement, preventing wasteful agent loop storms.

### 3. Idempotency Key Injection
- Accepts optional `idempotency_key` argument in `get_latest_briefing()`.
- Passes `Idempotency-Key: <key>` header on all requests and retries, guaranteeing at-most-once processing even across network dropouts.

### Python SDK Recovery Example:
```python
from sdk.moltbook_intel import (
    MoltbookIntelClient,
    RateLimitExceededError,
    EntitlementExhaustedError,
)

client = MoltbookIntelClient(
    base_url="https://moltbook-alpha.duckdns.org",
    api_key="molt_live_key_xyz",
    timeout=15.0,
    max_retries=3,
)

try:
    # Safe query execution with automatic backoff and idempotency
    briefing = client.get_latest_briefing(idempotency_key="job_task_20261018_01")
    print("Intelligence received:", briefing["user_tier"])
except EntitlementExhaustedError:
    # Quota exhausted: Halt polling and request renewal
    print("Entitlement exhausted. Pausing agent workflow until balance renewal.")
except RateLimitExceededError as e:
    print(f"Transient rate limit exceeded even after retries. Retry after {e.retry_after}s.")
```

---

## 9. Verification & Compliance Matrix

| Requirement | Implementation Component | Test Verification | Status |
| :--- | :--- | :--- | :--- |
| **Separation of Quota & Rate Limit** | `storage.py`, `config.py` | `test_quota.py`, `test_entitlements_and_topups.py` | Verified (PASS) |
| **Burst (5) & Sustained (60/min)** | `rate_limiter.py:TokenBucketRateLimiter` | `test_token_bucket_burst_allowance_and_sustained_refill` | Verified (PASS) |
| **Multi-Worker Synchronization** | SQLite table `rate_limit_tokens` | `test_token_bucket_multi_instance_coordination` | Verified (PASS) |
| **Fail-Open / Closed Handling** | `TokenBucketRateLimiter(fail_open=...)` | `test_token_bucket_fail_open_and_closed` | Verified (PASS) |
| **Max Concurrent Requests (5)** | `rate_limiter.py:ConcurrencyLimiter` | `test_concurrency_limiter_slots_and_cleanup` | Verified (PASS) |
| **Atomic Quota Reservation** | `storage.py:reserve_quota` | `test_atomic_quota_reservation_and_settlement` | Verified (PASS) |
| **Release Quota on Error/Timeout**| `storage.py:release_quota` | `test_quota_reservation_release_on_error` | Verified (PASS) |
| **Idempotency Deduplication** | `quota_reservations.response_cache` | `test_quota_reservation_idempotency_replay` | Verified (PASS) |
| **Standardized Error Taxonomy** | `errors.py:format_error_payload` | `test_error_handling.py` | Verified (PASS) |
| **Usage & Rate Limit Inspection** | `GET /v1/account/quota` | `test_account_quota_enriched_usage_and_rate_limit_state` | Verified (PASS) |
| **Warning Thresholds & Dedup** | `storage.py:_check_and_record_quota...` | `test_quota_threshold_warning_crossing_and_deduplication` | Verified (PASS) |
| **SDK Jitter Backoff (429)** | `sdk/moltbook_intel/client.py` | `test_sdk_rate_limit_retry_with_backoff_and_jitter` | Verified (PASS) |
| **SDK Halt on Exhaustion (402)** | `sdk/moltbook_intel/client.py` | `test_sdk_entitlement_exhausted_halts_retries` | Verified (PASS) |
| **SDK Idempotency Propagation** | `sdk/moltbook_intel/client.py` | `test_sdk_idempotency_key_propagation` | Verified (PASS) |
