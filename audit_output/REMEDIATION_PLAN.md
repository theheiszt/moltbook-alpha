# Moltbook Alpha — Production Traffic Investigation
## Minimal Remediation Plan: Evidence-Backed Architecture & Operational Refinements

**Investigation Status:** Investigation Complete. **Awaiting User Authorization.**  
**Deployment Target:** Moltbook Alpha Production (`theheiszt/moltbook-alpha`)  
**Audit Artifact File:** `audit_output/REMEDIATION_PLAN.md`  

---

## 1. Prioritized Remediation Summary

The following five remediations are arranged in descending order of impact-to-risk ratio. Each recommendation directly targets empirical findings from the ~11,000-request audit without introducing new infrastructure dependencies or third-party paid services.

| Priority | Remediation Item | Target File / Layer | Observed Problem Addressed | Expected Impact | Risk Level |
|---|---|---|---|---|---|
| **P1** | **Page Visibility & Adaptive Polling** | `dashboard.html` | Background browser tabs polling every 5s indefinitely. | **85%–95% reduction** in dashboard requests. | **Zero** (Client UI only) |
| **P2** | **CORS Preflight Caching (`max_age`)** | `api_server.py`, `dashboard.html` | Every 5s poll issues 1 OPTIONS + 1 GET. | **Eliminates 50% of requests** (4,974 OPTIONS removed). | **Very Low** |
| **P3** | **In-Memory TTL Caching for Metrics** | `api_server.py` | 54,714 SQLite queries under lock across 7 hours. | **90%+ reduction** in SQLite lock acquisitions. | **Low** |
| **P4** | **Rate Limiting on Dashboard Endpoint** | `api_server.py` | No rate limit on `/v1/metrics/dashboard`. | Prevents rogue scripts from lock-starving the database. | **Low** |
| **P5** | **Prometheus Auth & Health Sanitization** | `api_server.py`, `config.py` | Unauthenticated access to `/metrics`; stack leak in `/v1/health`. | Eliminates operational reconnaissance risk. | **Low** |

---

## 2. Detailed Technical Remediations

### Remediation P1: Page Visibility API & Default Poll Interval Increase
- **Evidence:** `dashboard.html` polls on a fixed 5-second `setInterval` without listening to `visibilitychange`. 9,948 requests were logged while the dashboard tab was open.
- **Implementation Scope:**
  1. In `dashboard.html`, change default polling `<option value="5000" selected>` to `<option value="30000" selected>` (30 seconds) or `15000` (15 seconds).
  2. Implement `document.addEventListener('visibilitychange')`:
     - When `document.hidden === true`, clear `pollTimer` (pause polling).
     - When `document.hidden === false`, trigger an immediate `fetchMetrics()` and restart `pollTimer`.
- **Expected Reduction:** A user leaving a background tab open for 7 hours will generate **0 requests** while hidden instead of 9,948 requests.
- **Rollback Procedure:** Revert `dashboard.html` git commit.
- **Acceptance Criteria:** Minimizing tab stops network activity in browser dev tools; switching back resumes polling immediately.

---

### Remediation P2: CORS Preflight Cache Header (`max_age=86400`)
- **Evidence:** 4,974 `OPTIONS /v1/metrics/dashboard` requests were logged, exactly matching the 4,974 `GET` requests.
- **Implementation Scope:**
  1. In `api_server.py`:
     ```python
     app.add_middleware(
         CORSMiddleware,
         allow_origins=["https://theheiszt.github.io"],  # Replace wildcard with exact origin
         allow_methods=["GET", "POST", "OPTIONS"],
         allow_headers=["Authorization", "Content-Type", "Accept", "X-Request-ID"],
         max_age=86400,  # Cache CORS preflights for 24 hours
     )
     ```
  2. In `dashboard.html`, remove `cache: "no-store"` from the metrics `fetch()` options to prevent browser cache bypass on preflight verification.
- **Expected Reduction:** Reduces dashboard HTTP request count by exactly **50%** (eliminating 4,974 preflights per 7-hour session).
- **Rollback Procedure:** Restore default middleware in `api_server.py`.
- **Acceptance Criteria:** Browser network panel shows only 1 `OPTIONS` preflight followed by recurring `GET` requests without recurring `OPTIONS`.

---

### Remediation P3: In-Memory TTL Caching on `/v1/metrics/dashboard`
- **Evidence:** `storage.get_dashboard_metrics()` executes 11 relational SQLite queries while holding `self._lock` on every single request.
- **Implementation Scope:**
  1. In `api_server.py`, wrap the call to `storage.get_dashboard_metrics()` with a lightweight in-memory TTL cache (e.g. 5–10 seconds):
     ```python
     _DASHBOARD_CACHE = {"timestamp": 0, "payload": None}
     _DASHBOARD_CACHE_TTL = 10.0  # seconds

     @app.get("/v1/metrics/dashboard")
     def get_dashboard_metrics_endpoint(request: Request):
         # ... authentication checks ...
         now = time.time()
         if _DASHBOARD_CACHE["payload"] and (now - _DASHBOARD_CACHE["timestamp"]) < _DASHBOARD_CACHE_TTL:
             return _DASHBOARD_CACHE["payload"]
         data = storage.get_dashboard_metrics()
         # enrich ...
         _DASHBOARD_CACHE["timestamp"] = now
         _DASHBOARD_CACHE["payload"] = data
         return data
     ```
- **Expected Reduction:** Even if multiple dashboard tabs poll concurrently, the SQLite database is queried at most once every 10 seconds (max 360 queries/hour instead of 7,800+ queries/hour).
- **Rollback Procedure:** Remove the dictionary caching wrapper.
- **Acceptance Criteria:** Metrics update every 10s; database query volume under concurrent requests drops by >90%.

---

### Remediation P4: Enforce Rate Limiting on `/v1/metrics/dashboard`
- **Evidence:** No rate limiter currently wraps `/v1/metrics/dashboard`.
- **Implementation Scope:**
  1. In `api_server.py`:
     ```python
     client_ip = get_client_ip(request)
     allowed, retry_after = rate_limiter.is_allowed(f"dashboard_metrics:{client_ip}", limit=30, window_seconds=60)
     if not allowed:
         record_rate_limit("/v1/metrics/dashboard")
         raise HTTPException(
             status_code=status.HTTP_429_TOO_MANY_REQUESTS,
             detail=f"Dashboard polling rate limit exceeded. Retry in {retry_after}s.",
             headers={"Retry-After": str(retry_after)}
         )
     ```
- **Expected Impact:** Guarantees protection against rogue client loops and runaway automated scripts.
- **Acceptance Criteria:** Sending >30 req/min from a single IP triggers structured `HTTP 429 RATE_LIMIT_EXCEEDED` response.

---

### Remediation P5: Enforce Authentication on `/metrics` & Sanitize `/v1/health`
- **Evidence:** `/metrics` is accessible publicly without authentication. `/v1/health` discloses `journal_mode: WAL` and `treasury_wallet` address.
- **Implementation Scope:**
  1. Set `METRICS_BEARER_TOKEN` in production systemd environment (`/etc/systemd/system/moltbook-api.service`).
  2. In `api_server.py`, simplify `GET /v1/health` response to:
     ```python
     @app.get("/v1/health")
     def health_check():
         return {"status": "ok", "service": "moltbook-alpha-api", "version": "1.2.0"}
     ```
- **Expected Impact:** Completely closes operational telemetry reconnaissance vector and prevents technology fingerprinting.
- **Acceptance Criteria:** Anonymous curl to `/metrics` returns `HTTP 401 Unauthorized`; `/v1/health` returns minimal JSON payload without database internals.

---

## 3. Implementation Safety & Phasing

- **Phase 1 (Client Fixes):** P1 (`dashboard.html` visibility and default interval). Requires zero backend changes and zero downtime.
- **Phase 2 (CORS & Caching):** P2 & P3 in `api_server.py`. Can be deployed and validated in local staging before reloading production systemd unit.
- **Phase 3 (Hardening):** P4 & P5 in `api_server.py`.

**Stop Condition:** Do not execute any code modifications or production changes until explicit approval is granted by the user.
