# Moltbook Alpha — Production Traffic Investigation
## Traffic Test Plan: Verification Matrix & Regression Safeguards

**Audit Artifact File:** `audit_output/TRAFFIC_TEST_PLAN.md`  
**Test Mode:** Local & Isolated Runner Testing (Non-Destructive)  
**Execution Condition:** Pre-Implementation Validation Suite (Runs Only Upon User Approval)  

---

## 1. Test Suite Objectives

This test plan defines the automated and manual verification procedures required before and after applying any remediation. It ensures:
1. Significant reduction in dashboard polling and CORS overhead.
2. Complete preservation of payment processing, invoice verification, and credit issuance invariants.
3. Enforcement of authentication and rate limiting without regressing legitimate agent workflows.
4. Clean cache invalidation without stale data persistence across operator actions.

---

## 2. Test Matrix

| Test ID | Test Category | Target Component | Description & Procedure | Expected Result | Acceptance Criteria |
|---|---|---|---|---|---|
| **TEST-01** | **CORS Preflight** | `api_server.py` (`CORSMiddleware`) | Issue `OPTIONS /v1/metrics/dashboard` with origin `https://theheiszt.github.io` and headers `Authorization, Accept`. | Response returns HTTP 200 with header `Access-Control-Max-Age: 86400`. | Subsequent requests within 24h reuse preflight cache in browser. |
| **TEST-02** | **Cache Freshness** | `api_server.py` (`_DASHBOARD_CACHE`) | Query `/v1/metrics/dashboard` 10 times consecutively within 2 seconds using valid admin bearer token. | First request computes and caches payload; subsequent 9 requests return identical payload in < 0.5ms without executing SQLite queries. | Database query counter increments by only 11 queries instead of 110 queries. |
| **TEST-03** | **Cache TTL Expiry** | `api_server.py` (`_DASHBOARD_CACHE`) | Wait 11 seconds (TTL = 10s) and query `/v1/metrics/dashboard` again. | Response returns updated payload with refreshed timestamp. | Cache refreshes automatically after TTL expiry. |
| **TEST-04** | **Rate Limiting** | `api_server.py` (`dashboard_metrics`) | Send 35 requests within a 60-second window to `/v1/metrics/dashboard` using valid token. | First 30 requests return HTTP 200; requests 31–35 return HTTP 429 with `Retry-After` header and structured error contract. | Throttling protects server from denial-of-service loops. |
| **TEST-05** | **Metrics Auth** | `api_server.py` (`/metrics`) | 1. Query `GET /metrics` with no headers when `METRICS_BEARER_TOKEN` is set.<br>2. Query `GET /metrics` with valid Bearer token. | 1. Returns HTTP 401 with `UNAUTHORIZED_METRICS` error code.<br>2. Returns HTTP 200 with full Prometheus text format exposition. | Unauthenticated public scraping of operational metrics is blocked. |
| **TEST-06** | **Health Sanitization** | `api_server.py` (`/v1/health`) | Query `GET /v1/health`. | Returns `{"status":"ok","service":"moltbook-alpha-api","version":"1.2.0"}` without `subsystems`, `journal_mode`, or `treasury_wallet`. | Liveness check works without exposing internal architecture or wallet addresses. |
| **TEST-07** | **Visibility Pausing** | `dashboard.html` (Frontend UI) | Load dashboard in browser, simulate tab hide via `Object.defineProperty(document, 'hidden', { value: true }); document.dispatchEvent(new Event('visibilitychange'));`. | Network activity halts completely; no `fetch` requests dispatched while tab remains hidden. | Zero background polling while operator is viewing another tab or application. |
| **TEST-08** | **Payment Invariants** | `payment_pipeline.py` & `api_server.py` | Run existing regression suite: `tests/test_gateway_reconcile_and_samples.py` and `tests/test_quant_trader.py`. | All 285 automated unit and integration tests pass with 100% success. | Zero regression in invoice creation, Solana verification, Nano settlement, or credit ledger WAL. |
| **TEST-09** | **Agent Job Board** | `job_board.py` & `/v1/jobs` | Verify 4-axis witness verification and run nonce generation. | `POST /v1/jobs/issue-run-nonce` and `POST /v1/jobs/verify-witness` succeed without degradation. | Agent job board contracts remain fully functional. |

---

## 3. Test Execution Script (Standalone Mock Runner)

A dedicated non-production test runner will be staged to execute the entire matrix locally:
```bash
# Isolated pytest execution against local SQLite fixture (no production impact)
python -m pytest tests/test_dashboard_metrics.py -v
python -m pytest tests/test_gateway_reconcile_and_samples.py -v
```

---

## 4. Rollback and Disaster Recovery Protocol

If any test fails during pre-deployment staging:
1. **Immediate Abort:** Do not promote modified files to the production ProLiant deployment.
2. **Git Revert:** Run `git checkout -- dashboard.html api_server.py` to restore working tree to commit `1eb369f`.
3. **Verification:** Re-verify Prometheus `/metrics` and `/v1/health` against the running gateway to confirm baseline state.
