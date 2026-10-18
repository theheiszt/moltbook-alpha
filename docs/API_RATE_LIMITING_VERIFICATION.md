# Moltbook Alpha v1.9.0 — Adversarial Production-Readiness Verification Report

**Date:** 2026-10-18  
**Verification Scope:** Rate limiting, SQLite WAL multi-worker coordination, EDF quota reservation, refunds, idempotency deduplication, timeout recovery, and SDK resilience.  
**Branch:** `feat/commercial-api-hardening`  
**Git Baseline Commit:** `593941da3d39dc21989c0dc7d59daf07dbdf9a57`  
**Final Verification Result:** **PASS (225 / 225 tests passing, 0 linter errors)**

---

## 1. Executive Summary & Verification Outcomes

An independent, adversarial verification of the Moltbook Alpha v1.9.0 commercial hardening suite was executed across the rate limiting, concurrency coordination, EDF quota accounting, idempotency, and timeout subsystems.

### Key Outcomes
1. **Defect Identified & Remediated (Concurrent Idempotency Double-Spend):** Under race conditions with identical idempotency keys across threads, non-reentrant locking and lack of a SQLite-level partial unique index permitted two simultaneous requests to reserve quota and deduct credits. This was reproduced, fixed with `threading.RLock`, a partial unique constraint `idx_active_idemp`, and atomic reservation/refund rollback. Verified with 10 concurrent threads: exactly 1 succeeded, 9 received `in_flight`, exactly 1 credit deducted.
2. **Defect Identified & Remediated (Timeout Cleanup Gap):** The request execution timeout middleware (30s) previously lacked tracking references to active `concurrency_slot_id` and `quota_reservation_id`. On a 504 timeout, slots and reserved credits were orphaned until reaper execution. `request.state` tracking was added; on 504, slots and reservations are immediately released, restoring customer credits with zero leakage.
3. **Multi-Worker Single-Host Coordination Verified:** SQLite in Write-Ahead Logging (WAL) mode (`PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;`) coordinates token buckets, execution slots, and quota reservations with 100% data consistency across Uvicorn worker processes on the host.
4. **Multi-Host Architectural Assessment:** SQLite coordinates processes on a *single host*. If Moltbook Alpha scales horizontally to multiple physical servers without a shared database, independent local SQLite databases would allow per-node rate limit multiplication. Multi-host scaling requires an authoritative distributed coordinator (e.g., Redis with Lua scripts or centralized Postgres/CockroachDB).
5. **Ledger Balance Equation Mathematically Reconciled:** The core accounting invariant `granted + refunded - deducted - expired == current active remaining balance` was verified and holds true across every adversarial concurrency, timeout, and reaper scenario.

---

## 2. Baseline & Post-Verification Metrics

| Metric | Baseline (Start of Audit) | Post-Verification (Final State) | Status |
| :--- | :--- | :--- | :--- |
| **Git Working Tree** | Clean tracked, 3 untracked docs | Clean tracked, test & verification docs added | **VERIFIED** |
| **Pytest Suite** | 215 passed, 1 warning (36.6s) | **225 passed, 2 warnings (40.3s)** | **PASS** |
| **Ruff Check** | 0 errors | **0 errors (100% clean)** | **PASS** |
| **Adversarial Test Suite** | None | 10 comprehensive tests in `test_adversarial_readiness.py` | **PASS** |
| **Concurrent Double-Spend**| **Vulnerable** (2 credits burnt on race) | **Remediated & Verified** (1 credit burnt, 0 leak) | **PASS** |
| **504 Quota Recovery** | Orphaned until reaper runs | **Immediate release on timeout** | **PASS** |

---

## 3. Architecture & Distributed Coordination Analysis

### Deployment Architecture Topology

```
+-----------------------------------------------------------------------------------------+
| Single Production Host (10.0.0.190 - HP ProLiant ML150 G6)                              |
|                                                                                         |
|  +-------------------+       +-------------------+       +-------------------+          |
|  | Uvicorn Worker 1  |       | Uvicorn Worker 2  |       | Uvicorn Worker 3  |          |
|  | - TokenBucket     |       | - TokenBucket     |       | - TokenBucket     |          |
|  | - ConcurrencySlot |       | - ConcurrencySlot |       | - ConcurrencySlot |          |
|  +---------+---------+       +---------+---------+       +---------+---------+          |
|            |                           |                           |                    |
|            +---------------------------+---------------------------+                    |
|                                        |                                                |
|                                        v                                                |
|               +--------------------------------------------------+                      |
|               | Authoritative SQLite DB (WAL Mode)               |                      |
|               | File: data/moltbook_intel.db                     |                      |
|               | Tables: rate_limit_tokens,                       |                      |
|               |         rate_limit_concurrency,                  |                      |
|               |         quota_reservations,                      |                      |
|               |         credit_lots, credit_ledger_events        |                      |
|               +--------------------------------------------------+                      |
+-----------------------------------------------------------------------------------------+
```

### Multi-Worker Coordination (Single Host)
- **Authoritative Shared State:** Workers coordinate rate limit tokens (`rate_limit_tokens`) and execution concurrency (`rate_limit_concurrency`) directly through SQLite with `PRAGMA journal_mode=WAL` and `PRAGMA synchronous=NORMAL`.
- **Lock Contention:** `PRAGMA busy_timeout=5000;` ensures workers wait up to 5,000ms for busy write locks rather than aborting immediately.
- **Fail-Open vs. Fail-Closed:** If SQLite is locked or unavailable during rate limiting, the limiter falls back to process in-memory tracking with an audit log. If SQLite is unavailable during credit deduction, the system fails closed (503 Service Unavailable) to prevent unauthorized quota overspend.

### Multi-Host Scaling Gap & Recommendation
- **Current Limitation:** SQLite WAL coordination operates via OS-level file locking (POSIX / Windows locks). If Moltbook Alpha is scaled horizontally across multiple distinct physical servers (nodes) with independent local disks, each node would maintain an independent SQLite file. This would permit an agent to achieve `N * 60 req/min` across `N` nodes.
- **Recommended Coordinator for Multi-Host Scale:**
  1. **Option A (Redis / KeyDB):** Deploy a shared Redis cluster using standard token-bucket Lua scripts for sub-millisecond atomic decrement, with SQLite remaining the durable accounting database.
  2. **Option B (PostgreSQL / CockroachDB):** Replace the storage backend with distributed PostgreSQL utilizing row-level locks (`SELECT ... FOR UPDATE`) and ACID transactions across hosts.
  *Note: For single-host operation (current ML150 G6 deployment), the existing SQLite WAL design is completely sound, low-overhead, and zero-dependency.*

---

## 4. Rate-Limit Mathematics Verification

The token-bucket rate limiter enforces a continuous-refill token algorithm:

$$\text{Tokens}(t) = \min\left(\text{Capacity}, \text{Tokens}(t_{\text{last}}) + (t - t_{\text{last}}) \times \frac{\text{RefillPerMin}}{60}\right)$$

### Verification Results
1. **Burst Capacity:** When initialized or idle, the bucket grants exactly `Capacity = 5` tokens in a rapid burst ($0 \text{ ms}$ interval).
2. **Refill Rate:** Configured for sustained $60 \text{ req/min}$ ($1.0 \text{ token/s}$). Advancing simulated time by exactly $1.0\text{ s}$ replenishes exactly $1.0\text{ token}$.
3. **Ceiling Invariant:** Advancing simulated time by $1,000,000\text{ s}$ (weeks of idle time) resulted in `get_remaining()` returning exactly $5.0$. The bucket never grants more than the configured maximum burst capacity.
4. **Retry-After Calculation:** When tokens are depleted, `Retry-After` is calculated as $\lceil \frac{1 - \text{tokens}}{\text{refill}} \rceil \ge 1$, returning integer seconds matching HTTP/1.1 RFC standards.
5. **Quota Separation:** HTTP 429 rate limit rejections occur before credit reservation. Adversarial stress tests confirmed that 429 responses consume $0$ monthly query credits.

---

## 5. EDF Quota Reservation Lifecycle Under Adversarial Concurrency

### Earliest Deadline First (EDF) Allocation
Credit lots are queried ordered by expiration date ascending:
```sql
SELECT lot_id, lot_type, credits_remaining, expires_at
FROM credit_lots
WHERE key_hash = ? AND status = 'active' AND credits_remaining > 0
  AND (expires_at IS NULL OR expires_at >= ?)
ORDER BY
  CASE WHEN expires_at IS NULL THEN 1 ELSE 0 END ASC,
  expires_at ASC,
  created_at ASC
LIMIT 1;
```

### Adversarial Scenarios Tested & Confirmed
1. **Competition for the Last Available Credit:**
   - Setup: Account funded with exactly 1 credit.
   - Attack: 25 threads concurrently call `reserve_quota`.
   - Result: Exactly 1 thread received `"ok"`; 24 threads received `"exhausted"`. Balance remained $0$ (never negative).
2. **Multi-Lot Expiration Rollover:**
   - Setup: Lot A (2 credits, expires in 2 days), Lot B (3 credits, expires in 10 days).
   - Execution: Consecutive requests consume Lot A first. When Lot A reaches $0$, subsequent requests seamlessly transition to Lot B.
3. **Failure After Reservation:**
   - When a request fails, `release_quota` restores the credit to the original lot, updates API key balance, and inserts a `'refund'` ledger event.
4. **Worker Crash & Automatic Reaper:**
   - Unsettled reservations older than the $60\text{s}$ TTL are reaped by `reap_expired_reservations()`.
   - The credit is restored and logged in the ledger.
   - A late-returning worker thread attempting `settle_quota` or `release_quota` receives `False` (0 rows updated), preventing double-credits.
5. **Ledger Mathematical Invariant:**
   - Tested across all adversarial scenarios using `verify_ledger_balance`:
     $$\text{Granted} + \text{Refunded} - \text{Deducted} - \text{Expired} \equiv \text{Active Lot Credits} \equiv \text{API Key Balance}$$
   - Returned `balanced == True` across all test suites.

---

## 6. Idempotency & Response Replay Verification

### Mechanics & Invariants
- Clients provide an `Idempotency-Key` (or `X-Idempotency-Key`) header.
- **In-Flight Protection:** If a request is already executing for that key, subsequent requests receive `HTTP 429` with machine-readable `"in_flight"` status.
- **Settled Replay:** Upon successful completion, the response payload is cached in `quota_reservations.response_cache`. Retrying the same key returns the cached response with `X-Cache: HIT`, burning $0$ additional credits.
- **Tenant Isolation:** Reservations are indexed on `(key_hash, idempotency_key)`. If User A and User B supply the identical key string, User B does not receive User A's cached response.
- **Failure Recovery:** If a previous attempt failed and was released, the idempotency key is freed (since `idx_active_idemp` only indexes status in `'reserved', 'settled'`), allowing an immediate clean retry.

---

## 7. Timeout Semantics & Concurrency Slot Recovery

### Handler Execution & Middleware
- **Middleware Boundary:** Requests are wrapped in `asyncio.wait_for(call_next(request), timeout=30.0)`.
- **Pre-Fix Defect:** If the 30-second deadline elapsed, FastAPI returned 504, but the concurrency slot and quota reservation remained allocated.
- **Post-Fix Behavior:**
  1. `request.state.concurrency_slot_id` and `request.state.quota_reservation_id` are populated upon acquisition.
  2. On `asyncio.TimeoutError`, the middleware immediately calls:
     ```python
     concurrency_limiter.release(slot_id, rate_key)
     storage.release_quota(res_id, reason="request_timeout_504")
     ```
  3. Customer credits are restored instantly, and concurrency counters do not leak.

---

## 8. Deterministic Stress Test (Simulated Agent Loop)

A deterministic stress test was executed simulating an autonomous trading agent running in a tight loop attempting to consume credits:
- **Attempted Requests:** 50
- **Successful Queries (200 OK):** 15 (exhausted the full 15 funded credits)
- **Rate-Limited Responses (429):** 24 (burst ceiling reached, agent backed off and waited for token refill)
- **Credits Exhausted Responses (402):** 11 (rejected after credits dropped to 0)
- **Account Balance Verification:** Remaining credits = 0; credits deducted = 15; credits refunded = 0.
- **Ledger Status:** `balanced == True`.

---

## 9. Pytest Warning Analysis & Resolution

Running `uv run python -m pytest` reports 2 warnings across 225 tests:

1. **`StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated; install httpx2 instead.`**
   - **Source:** `.venv\Lib\site-packages\fastapi\testclient.py:1`
   - **Root Cause:** FastAPI's current internal `TestClient` imports Starlette's deprecated testclient shim.
   - **Assessment:** Safe upstream framework warning; no impact on production Uvicorn runtime.
2. **`RuntimeWarning: coroutine 'BaseHTTPMiddleware.__call__.<locals>.call_next' was never awaited`**
   - **Source:** `tests/test_auth.py::test_missing_api_key_returns_402_with_payment_instructions`
   - **Root Cause:** When an endpoint or middleware terminates early with an `HTTPException` (e.g. 402 Payment Required for missing auth headers), Starlette's `BaseHTTPMiddleware` does not invoke `call_next`.
   - **Assessment:** Expected ASGI middleware lifecycle behavior; no memory leak or execution impact.

---

## 10. Operational Runbook Additions

### Prometheus Metrics to Monitor
- `moltbook_rate_limit_exceeded_total{endpoint="..."}`: Spikes indicate aggressive client agent loops or DDoS.
- `moltbook_active_keys_gauge`: Active authenticated clients.
- `moltbook_concurrency_slots_in_use`: Concurrency saturation per tier.

### Log Signatures
- `Rate limit burst capacity exceeded for key:<hash>`: Informational client throttling.
- `Reaped X abandoned quota reservations`: Triggered when client disconnects or handlers timeout.
- `Concurrent idempotency race detected for key:<hash>`: Indicates client multi-threading identical requests.

### Quota Threshold Webhooks / Email Alerts
Threshold alerts trigger at $50\%$, $80\%$, $90\%$, and $95\%$ quota consumption via `quota_threshold_alerts`.

---

## 11. Explicit Verification Checklist Table

| Verification Item | Specification Requirement | Verification Method | Status |
| :--- | :--- | :--- | :--- |
| **Baseline Established** | Record git tree, commit, pytest baseline | Git status & full pytest baseline run | **PASS** |
| **Distributed Multi-Worker** | Multi-worker SQLite WAL coordination | `test_adversarial_multi_instance_shared_sqlite_rate_limiting` | **PASS** |
| **Single-Host vs Multi-Host** | Document multi-host enforcement gap | Documented in Section 3 with Redis/Postgres recommendations | **PASS** |
| **Token Bucket Refill** | Refills at 60/min (1/s), never exceeds 5.0 | `test_token_bucket_mathematics_refill_and_cap` | **PASS** |
| **Rate Limit vs Quota** | 429 rejections consume 0 monthly credits | `test_deterministic_stress_loop_agent_quota_and_burst_exhaustion` | **PASS** |
| **EDF Multi-Lot Rollover** | Earliest expiring lot consumed first | `test_adversarial_edf_multi_lot_ordering` | **PASS** |
| **Last Credit Competition** | 25 concurrent threads for 1 credit, 0 overspend | `test_adversarial_competition_for_last_credit` | **PASS** |
| **Reservation Reaping** | Expired reservations restored to lot & key | `test_adversarial_reservation_lifecycle_reaper_and_idempotent_settle`| **PASS** |
| **Late Settle Rejection** | Settling expired reservation fails safely | `test_adversarial_reservation_lifecycle_reaper_and_idempotent_settle`| **PASS** |
| **Duplicate Settlement** | Calling settle twice is idempotent | `test_adversarial_reservation_lifecycle_reaper_and_idempotent_settle`| **PASS** |
| **Duplicate Refund** | Calling release twice is idempotent | `test_adversarial_reservation_lifecycle_reaper_and_idempotent_settle`| **PASS** |
| **Idempotency Multi-Thread Race**| 10 threads, 1 ok, 9 in_flight, 1 deduction | `test_adversarial_concurrent_idempotency_double_spend` | **PASS** |
| **Response Cache Replay** | Retrying completed request burns 0 credits | `test_adversarial_concurrent_idempotency_double_spend` | **PASS** |
| **Idempotency Isolation** | Idempotency keys isolated per API key | `test_adversarial_idempotency_cross_user_isolation` | **PASS** |
| **504 Timeout Quota Release**| Timed-out requests immediately restore credits | `test_adversarial_timeout_and_504_slot_and_quota_recovery` | **PASS** |
| **504 Slot Release** | Timed-out requests immediately release slot | `test_adversarial_timeout_and_504_slot_and_quota_recovery` | **PASS** |
| **Full Pytest Suite** | 100% pass across all tests | `uv run python -m pytest` (225 passed) | **PASS** |
| **Code Hygiene** | Ruff linter passes with 0 errors | `uv run ruff check .` | **PASS** |

---

## 12. Conclusion & Deployment Readiness

Moltbook Alpha v1.9.0 has completed adversarial production-readiness verification. The concurrent double-spend race condition and timeout cleanup gaps have been resolved, verified with deterministic concurrency tests, and confirmed against the mathematical ledger balance equation. The system is certified production-ready for single-host multi-worker deployment under high-frequency agent workloads.
