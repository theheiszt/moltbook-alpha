# Moltbook Alpha API Rate Limiting, Quota Hardening & Agent Recovery — Comprehensive Audit

**Date:** 2026-10-18  
**Baseline Git State:** Branch `feat/commercial-api-hardening`, Commit `593941d` (clean working tree)  
**Baseline Test Status:** 202 passing tests across 22 test modules (100% passing, 0 failures, clean Ruff lint)  

---

## 1. Executive Summary

This audit assesses the resilience of the Moltbook Alpha API against high-frequency autonomous agent loops, burst exhaustion, concurrent quota overspending, and downstream client crashes when monthly entitlements are depleted.

The Moltbook Alpha service powers automated market intelligence synthesis, cryptographic state witness verification, and Solana-settled micro-billing. While transactional integrity in SQLite WAL mode is robust for discrete key creation and payment redemption, the current implementation exhibits critical architectural vulnerabilities in request rate limiting, concurrency bounding, and quota deduction lifecycles when subjected to high-throughput autonomous agents.

---

## 2. Existing Architecture & Relevant File Paths

The service is structured as follows:

| Component | Path | Responsibility |
| :--- | :--- | :--- |
| **API Server & Routing** | `api_server.py` | FastAPI application exposing endpoints for intel, payment invoices, verification, and quota monitoring. |
| **Rate Limiter & Deduplicator** | `rate_limiter.py` | In-memory `SlidingWindowRateLimiter` and `InFlightDeduplicator`. |
| **Transactional Storage** | `storage.py` | SQLite WAL storage managing API keys, 30-day entitlements, credit lots (EDF), and ledger balance auditing. |
| **Error Taxonomy** | `errors.py` | Centralized `ErrorCode` enum, registry, and backwards-compatibility JSON payload formatting. |
| **Configuration** | `config.py` | Centralized environment variable resolution, rate presets, and pricing. |
| **Client SDK** | `sdk/moltbook_intel/client.py` | High-level client for autonomous agents consuming Moltbook Alpha. |
| **Test Suite** | `tests/` | 22 test modules covering adversarial payments, concurrency, entitlements, and proxy perimeter. |

---

## 3. Current Quota Lifecycle & Entitlement Accounting

### 3.1 Initial Grant & Entitlement Tiers
- **Starter:** 50 credits (non-expiring top-up/allowance lot).
- **Pro:** 300 credits (non-expiring allowance lot).
- **Premium:** 10,000 queries per rolling 30-day window ($20 USDC / SOL).
- **Top-Ups:** Optional 90-day top-up credit lots that survive across entitlement renewals.

### 3.2 Earliest Deadline First (EDF) Deduction
Credit deduction orders lots by `expires_at ASC` (`ORDER BY CASE WHEN expires_at IS NULL THEN 1 ELSE 0 END ASC, expires_at ASC, created_at ASC`), ensuring expiring allowances are consumed before non-expiring or long-lived lots.

### 3.3 The Single-Phase Deduction Vulnerability
Currently, credit deduction occurs **at the entry gate** of the request in `authenticate_and_deduct(api_key, request_id)`:
```python
# storage.py - Single-phase immediate deduction:
UPDATE credit_lots SET credits_remaining = ? WHERE lot_id = ? ...
UPDATE api_keys SET credits = credits - 1 WHERE key_hash = ? ...
INSERT INTO credit_ledger_events (...) VALUES (...)
```
This model has no two-phase commit:
1. If the downstream operation (e.g. briefing synthesis, network read, or complex serialization) encounters an error, timeout, or cancellation, the credit is permanently burned unless an ad-hoc catch-and-refund handler catches that specific exception.
2. If an autonomous agent times out after 10 seconds and retries the exact same query with an `Idempotency-Key`, the API treats it as a fresh request and deducts another credit, double-charging the customer.

---

## 4. Identified Failure Modes and Reproduction Steps

### Failure Mode 1: Unprotected Burst Floods and Agent Loops
- **Mechanism:** `rate_limiter.py` implements an in-memory sliding window that is only checked on selected routes (`/v1/payments/verify-solana`, `/v1/payments/invoice/:id/claim`, `/v1/account/quota`, `/v1/briefing/latest`) and is keyed exclusively by client IP address (`f"briefing:{client_ip}"`).
- **Reproduction:** An agent possessing an API key can launch 100 requests in 500ms. Because rate limits are IP-keyed rather than API-key-keyed, rotating IPs or distributed agents evade rate limits, while agents sharing an enterprise egress proxy starve each other.
- **Impact:** High burst traffic exhausts database worker threads and burns entire account quotas in seconds.

### Failure Mode 2: Multi-Instance / Multi-Worker State Drift
- **Mechanism:** `SlidingWindowRateLimiter` keeps state in an in-memory dictionary (`self._history: Dict[str, List[float]]`).
- **Reproduction:** Deploying `uvicorn` with `--workers 4` or multiple container replicas creates separate in-memory rate limiters. A client can send $4 \times$ the intended rate limit by distributing requests across workers.
- **Impact:** Inconsistent rate limit enforcement and inability to scale horizontally.

### Failure Mode 3: Premature Credit Burning & Timeout Losses
- **Mechanism:** Credit deduction happens before request execution starts.
- **Reproduction:** Client calls `/v1/intel/latest`. Handshake succeeds, credit is deducted in DB. The connection drops or client times out at 5 seconds. Credit is lost without the client receiving the briefing.
- **Impact:** Customer balance depletion with zero utility delivered.

### Failure Mode 4: Double Charging on Retries
- **Mechanism:** Lack of idempotency key binding to quota deduction.
- **Reproduction:** An agent sends a request with header `Idempotency-Key: idemp_abc123`. A transient network drop occurs after the server completes execution. The agent retries with the same `Idempotency-Key`.
- **Impact:** The second request deducts another credit. Customer is billed twice for one logical action.

### Failure Mode 5: Concurrency Overspend Under Race Conditions
- **Mechanism:** No limit on concurrent in-flight requests per API key.
- **Reproduction:** An account with 1 credit remaining sends 20 simultaneous requests. Even though `credits > 0` checks prevent negative balances in the database, 20 requests execute expensive server-side parsing and cryptographic operations before one wins the deduction and the other 19 fail with 402 after server work was already performed.
- **Impact:** Server resource exhaustion from unpaid concurrent load.

### Failure Mode 6: Lack of Early Warning Thresholds & Notification Floods
- **Mechanism:** Quota inspection only has a boolean `low_credits < 5` check.
- **Reproduction:** An enterprise agent on Premium (10,000 queries) has no programmatic visibility when it crosses 50%, 80%, 90%, or 95% usage thresholds.
- **Impact:** Abrupt, unannounced hard stop when quota hits 0, causing agent task failures.

### Failure Mode 7: Thundering Herd on 429 & Blind Retries on 402
- **Mechanism:** `sdk/moltbook_intel/client.py` uses fixed multiplier exponential backoff (`1.5 ** retries`) without random jitter, and does not halt on 402.
- **Reproduction:** When a rate limit clears, all waiting agents retry at the exact same millisecond, triggering an immediate second 429 burst. On 402, an agent might continue retrying if not explicitly terminated.
- **Impact:** Agent loops waste network and CPU resources.

---

## 5. Existing Protections That Can Be Reused

1. **SQLite WAL & ACID Transactions:** `PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;` provides reliable multi-process synchronization without requiring an external Redis instance.
2. **`credit_lots` & `customer_entitlements` Table Schemas:** Already correctly support 30-day Premium windows and 90-day top-ups with EDF ordering.
3. **`InFlightDeduplicator`:** Thread-safe locking pattern that can be extended for request concurrency tracking.
4. **Machine-Readable Error Infrastructure:** `errors.py` and `format_error_payload` with the `detail` backwards-compatibility bridge allow non-breaking schema extensions.
5. **Ledger Auditing:** `storage.verify_ledger_balance` provides verification that total grants, deductions, refunds, and expirations balance exactly.

---

## 6. Target Protection Architecture

```
                                [ Incoming Request ]
                                         │
                                         ▼
                     ┌──────────────────────────────────────┐
                     │   API Key & Identity Authentication   │
                     └──────────────────┬───────────────────┘
                                         │
                                         ▼
                     ┌──────────────────────────────────────┐
                     │      Token Bucket Rate Limiter       │
                     │  - Keyed by API Key Hash / Agent ID  │
                     │  - Sustained: 60 req/min             │
                     │  - Burst Capacity: 5 req/sec         │
                     │  - DB/WAL coordination across workers│
                     └──────────────────┬───────────────────┘
                                         │ Allowed
                                         ▼
                     ┌──────────────────────────────────────┐
                     │      Concurrency Limiter (Max 5)     │
                     └──────────────────┬───────────────────┘
                                         │ In-flight slot acquired
                                         ▼
                     ┌──────────────────────────────────────┐
                     │    Two-Phase Quota Reservation       │
                     │  1. Check atomic entitlement & EDF   │
                     │  2. Reserve credit (Idempotency Key) │
                     └──────────────────┬───────────────────┘
                                         │
                                         ▼
                     ┌──────────────────────────────────────┐
                     │       Endpoint Handler Execution     │
                     │      (30s Bounded Timeout Guard)     │
                     └──────────────────┬───────────────────┘
                                         │
                         ┌───────────────┴───────────────┐
                         │                               │
                      Success                          Error
                         │                               │
                         ▼                               ▼
        ┌────────────────────────────────┐ ┌────────────────────────────────┐
        │        Settle Quota            │ │       Release / Refund Quota   │
        │ - Finalize credit deduction    │ │ - Return reserved credit to lot│
        │ - Check 50/80/90/95% threshold │ │ - Zero balance overspend       │
        │ - Emit deduplicated warning    │ │ - Return structured error      │
        └────────────────────────────────┘ └────────────────────────────────┘
```

---

## 7. Risks and Backward-Compatibility Requirements

1. **Backwards Compatibility:** Legacy clients expecting `{ "detail": ... }` must continue receiving it. Modern clients receive `{ "error": { "code": "RATE_LIMITED", ... } }` and top-level taxonomy fields.
2. **Renewal Preservation:** Existing customer balances, 30-day entitlement windows, and credit lot expirations must not be modified or reset.
3. **Fail-Open vs. Fail-Closed Policy:**
   - Rate limiting fails open for public read-only informational routes (`/v1/health`, `/v1/tools`) if DB is degraded.
   - Rate limiting and quota reservation fail closed for paid query endpoints (`/v1/intel/latest`, `/v1/payments/verify-solana`).

---

## 8. Prioritized Implementation Plan (Status: 100% Complete)

*Implementation verified and documented in [`docs/API_RATE_LIMITING_VERIFICATION.md`](API_RATE_LIMITING_VERIFICATION.md).*

- [x] **Phase 1: Rate Limiter & Concurrency Guard (`rate_limiter.py`, `config.py`)** — **COMPLETE**
  - Implement `TokenBucketRateLimiter` with dual sustained (60/min) and burst (5/s) parameters.
  - Implement concurrent in-flight request limiter (max 5 per API key).
  - Add SQLite-backed coordination table (`rate_limit_buckets`) for multi-worker support with in-memory fast-path.
  - Standardize rate limit headers (`X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`, `Retry-After`).
- [x] **Phase 2: Atomic Two-Phase Quota Reservation (`storage.py`)** — **COMPLETE**
  - Create `quota_reservations` table with TTL and state machine (`reserved` -> `settled` / `released`).
  - Implement `reserve_quota(api_key, idempotency_key, request_id)`.
  - Implement `settle_quota(reservation_id)` and `release_quota(reservation_id, reason)`.
  - Implement automatic expired reservation reaping (`reap_expired_reservations`).
  - Enforce strict idempotency: identical `idempotency_key` returns prior settled response or active reservation without double-charging.
- [x] **Phase 3: Error Taxonomy & Middleware Standardisation (`errors.py`, `api_server.py`)** — **COMPLETE**
  - Add first-class `RATE_LIMITED` (429) and `ENTITLEMENT_EXHAUSTED` (402) in `ErrorCode` and `ERROR_REGISTRY`.
  - Adapt JSON error response to include nested `error` subobject while maintaining top-level and `detail` compatibility.
  - Wire rate-limiting and 30-second execution timeout middleware into `api_server.py`.
- [x] **Phase 4: Usage Visibility & Early Warning Thresholds (`storage.py`, `api_server.py`)** — **COMPLETE**
  - Add usage warning threshold calculations (50%, 80%, 90%, 95%) in `/v1/account/quota`.
  - Implement threshold-crossing deduplication so warnings are not emitted repeatedly on every request.
- [x] **Phase 5: Agent SDK Recovery Hardening (`sdk/moltbook_intel/client.py`)** — **COMPLETE**
  - Add exponential backoff with full jitter to SDK request loop.
  - Ensure SDK respects `Retry-After` on 429 and immediately halts on 402 without wasteful retries.
  - Add `idempotency_key` support on billable query calls.
- [x] **Phase 6: Comprehensive Verification & Test Suite Expansion (`tests/`)** — **COMPLETE**
  - Add test suites for token bucket rate limiting, burst control, concurrency limits, two-phase reservations, idempotency deduplication, and warning threshold events.
  - Maintain 100% pass rate across existing 202 tests and all new tests (225 passing, 0 failures).
