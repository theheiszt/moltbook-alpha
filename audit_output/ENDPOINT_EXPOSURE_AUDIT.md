# Moltbook Alpha — Production Traffic Investigation
## Endpoint Exposure & Attack Surface Security Audit

**Target Environment:** Moltbook Alpha Production Edge Gateway  
**Audit Scope:** Public API Endpoints, Operator Surfaces, Discovery Contracts, and Error Handlers  
**Audit Artifact File:** `audit_output/ENDPOINT_EXPOSURE_AUDIT.md`  

---

## 1. Public Exposure Matrix

The table below catalogs every endpoint observed in the 10,349 request traffic window, detailing authentication requirements, data disclosure, computational cost, and security controls:

| Endpoint Path | Method(s) | Auth Required? | Public Discovery? | Information Disclosed | Processing / Database Cost | Existing Controls | Critical Gaps |
|---|---|---|---|---|---|---|---|
| `/v1/metrics/dashboard` | `GET`, `OPTIONS` | **Yes** (Admin Session Bearer) | No | Active user counts by tier, 24h event volume, sales revenue, recent transaction signatures, conversion funnel drop-offs. | **High:** 11 SQLite queries executed under `self._lock` per request. | Authenticated via `storage.validate_admin_session` or `METRICS_BEARER_TOKEN`. | **No rate limiting.** No IP restriction. No CORS preflight caching. |
| `/metrics` | `GET` | **No** (Optional if env unset) | No | Full Prometheus metric exposition: request counts by route, method, and status; active API keys count (`6`); rate limit rejections; RPC failover hops. | **Low:** Reads in-memory Prometheus counters. Calls `storage.get_active_keys_count()` (1 index scan). | Optional `METRICS_BEARER_TOKEN` check (currently bypassed because env var is unset). | **Unauthenticated public access.** Operational reconnaissance vector. |
| `/v1/health` | `GET` | **No** | Yes | Service liveness, version (`1.2.0`), database state, SQLite journal mode (`WAL`), Solana treasury wallet public key. | **Minimal:** 1 simple SQLite check (`SELECT 1`). | None (open health check). | Exposes internal technology stack and treasury wallet address. |
| `/gateway.json` | `GET` | **No** | **Yes (Intentional)** | Machine-readable API discovery: active gateway URL, canonical discovery URL, supported features, payment rails. | **Zero:** Static JSON serialization from memory. | None (Public discovery contract). | None. Operates as intended by agent discovery spec. |
| `/` | `GET` | **No** | **Yes (Intentional)** | Public HTML landing page, developer documentation links, SDK examples. | **Minimal:** Serves static `index.html` from local disk. | None. Public marketing and documentation portal. | None. |
| `/v1/admin/login` | `POST`, `OPTIONS` | **No** (Credentials in Body) | No | On success: 24h session bearer token (`adm_sess_...`). On failure: generic 401 error. | **Low:** Verifies PBKDF2/Argon2 password hash against SQLite `admin_users` table. Logs audit event. | **SlidingWindowRateLimiter (10 req/5min per IP).** Audit logging on success/failure. | None identified. Adequate brute-force defense for current scale. |
| `/v1/jobs/:job_id` | `POST` | **Yes** (API Key or Token) | Yes | Agent job dispatch status, Ed25519 witness verification proof. | **Medium:** Validates job signature and updates SQLite job board table. | Credit checks, idempotency verification, signature checks. | None. Robust error contract and atomic state transitions. |
| `unmatched_route` | `GET`, `HEAD` | **No** | No | Generic standardized `RESOURCE_NOT_FOUND` error JSON payload. | **Minimal:** Rejected at FastAPI router level before hitting any business logic or database. | Standard 404 response handler. Short-circuits execution. | None. |

---

## 2. In-Depth Vulnerability & Exposure Analysis

### 2.1 `/v1/metrics/dashboard` — High DB Load Without Rate Limiting
- **Observation:** The endpoint correctly enforces `HTTP 401 Unauthorized` when requested without credentials. However, once authenticated, there is **zero rate limiting applied**.
- **Impact:** An operator keeping a tab open with 5s polling caused **54,714 SQLite query executions** across 7 hours. A compromised or buggy client could poll at 50 Hz and completely exhaust SQLite write locks (`self._lock`), starving the payment verification and invoice processing engine.
- **Classification:** **Denial of Service / Lock Contention Vulnerability (Internal)**.

### 2.2 `/metrics` — Unauthenticated Prometheus Exposition
- **Observation:** In `api_server.py`:
  ```python
  metrics_token = os.getenv("METRICS_BEARER_TOKEN", "").strip()
  if metrics_token:
      # enforce token
  ```
  Because `METRICS_BEARER_TOKEN` is not defined in the live environment, `/metrics` is completely open to the world.
- **Information Disclosed:**
  1. Complete inventory of private and public routes.
  2. Number of active API keys (`moltbook_api_keys_active_total 6`).
  3. Traffic volume, error counts, and peak usage periods.
- **Classification:** **Information Disclosure / Reconnaissance Vector (CWE-200)**.

### 2.3 `/v1/health` — Stack & Configuration Fingerprinting
- **Observation:** A `GET /v1/health` returns:
  ```json
  {
    "status": "ok",
    "service": "moltbook-alpha-api",
    "version": "1.2.0",
    "database": "healthy",
    "subsystems": {
      "database": { "status": "ok", "journal_mode": "WAL" },
      "payments": {
        "status": "ok",
        "treasury_wallet": "BU5zBur4...[REDACTED]"
      }
    }
  }
  ```
- **Information Disclosed:** Confirms exact SQLite backend engine, reveals WAL persistence mode, and advertises the hot treasury wallet address on an unauthenticated endpoint.
- **Classification:** **Unnecessary Operational Metadata Exposure (Low Risk)**.

### 2.4 `/v1/admin/login` — Brute Force Controls Assessment
- **Rate Limit Invariant:**
  ```python
  allowed, retry_after = rate_limiter.is_allowed(f"admin_login:{client_ip}", limit=10, window_seconds=300)
  ```
  Enforces a strict ceiling of 10 attempts per 5 minutes per IP.
- **Audit Verification:** SQLite `audit_logs` confirmed exactly 2 successful logins and 0 failed attempts during the 7-hour period, confirming that the 4 recorded login requests were legitimate operator actions.

---

## 3. Recommended Security Controls

1. **Apply Strict Rate Limiting to `/v1/metrics/dashboard`:**  
   Cap requests at 30 requests/minute per authenticated session or IP.
2. **Restrict `/metrics`:**  
   Require `METRICS_BEARER_TOKEN` in production or configure Cloudflare WAF / Nginx rules to restrict `/metrics` strictly to internal scrape IPs or loopback.
3. **Sanitize `/v1/health`:**  
   Strip internal database topology (`journal_mode`) and treasury wallet addresses from public health probes.
4. **Origin-Restricted CORS:**  
   Replace `allow_origins=["*"]` with explicit allowed origins (`https://theheiszt.github.io`).
