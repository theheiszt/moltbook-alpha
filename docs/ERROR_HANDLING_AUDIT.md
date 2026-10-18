# Moltbook Alpha — API Error Handling Audit Report

**Date:** 2026-10-18  
**Component:** Moltbook Alpha API & Autonomous Agent Gateway  
**Environment:** Staging / Local (`feat/commercial-api-hardening` at commit `cf951e2`)  
**Baseline Test Suite:** 165 passed across 17 test modules in 23.40s  
**Status:** Complete  

---

## 1. Executive Summary

Autonomous AI agents, programmatic trading bots, and developer SDKs interact with APIs fundamentally differently than human browser users. While human users can visually inspect ambiguous error messages, autonomous agents require:
1. **Deterministic, machine-readable error codes** that do not change based on string formatting.
2. **Explicit retryability semantics** (distinguishing deterministic client failures from transient infrastructure issues) with clear `retry_after` windows.
3. **Structured diagnostic details** (e.g. actionable remedies, precise field paths, and validation error arrays).
4. **End-to-end request tracing** (`request_id` / `X-Request-ID`) correlating client-side failures with immutable server-side audit logs.
5. **Absolute confidentiality** ensuring secrets, private keys, database paths, and raw stack traces are never exposed in error responses.

This audit evaluates Moltbook Alpha's existing API error handling across all 11 active routes, identifies structural inconsistencies, analyzes client dependencies, and establishes the architecture for a unified error taxonomy with a zero-breakage backwards-compatibility bridge.

---

## 2. Inventory of Current Error Response Formats

Prior to this initiative, Moltbook Alpha's error responses originated from disparate subsystems and produced inconsistent payload structures:

| Route / Subsystem | Status Code | Current Payload Structure | Origin & Mechanism |
|---|---|---|---|
| `GET /v1/briefing/latest` (Unauthenticated) | 402 Payment Required | `{"detail": {"error": "Payment Required", "message": "...", "price": "...", "purchase_instructions": {...}}}` | Dict inside FastAPI `HTTPException(detail=dict)` |
| `GET /v1/briefing/latest` (Invalid Key) | 403 Forbidden | `{"detail": "Invalid API key. Submit payment to /v1/payments/verify-solana or contact administrator."}` | Plain string inside FastAPI `HTTPException(detail=str)` |
| `GET /v1/briefing/latest` (Revoked Key) | 403 Forbidden | `{"detail": "API key has been revoked."}` | Plain string inside FastAPI `HTTPException(detail=str)` |
| `GET /v1/briefing/latest` (Entitlement Expired) | 402 Payment Required | `{"detail": {"error": "Entitlement Expired", "message": "...", "purchase_instructions": {...}}}` | Dict inside FastAPI `HTTPException(detail=dict)` |
| `GET /v1/briefing/latest` (Credits Exhausted) | 402 Payment Required | `{"detail": "Key credits exhausted. Top up your balance via Solana USDC."}` | Plain string inside FastAPI `HTTPException(detail=str)` |
| `GET /v1/briefing/latest` (Missing Report) | 404 Not Found | `{"detail": "No briefing generated yet."}` | Plain string inside FastAPI `HTTPException(detail=str)` |
| `GET /v1/briefing/latest` (File Read Failure) | 500 Internal Error | `{"detail": "Internal server error reading briefing."}` | Caught `Exception`, compensatory refund issued, plain string `HTTPException` |
| `GET /v1/account/quota` (Unauthenticated) | 401 Unauthorized | `{"detail": {"error": "Authentication Required", "message": "...", "remedy": {...}}}` | Dict inside `HTTPException` with `WWW-Authenticate: Bearer` header |
| `GET /v1/account/quota` (Invalid Key) | 403 Forbidden | `{"detail": {"error": "Invalid API Key", "message": "...", "remedy": {...}}}` | Dict inside `HTTPException` |
| `GET /v1/account/quota` (Revoked Key) | 403 Forbidden | `{"detail": {"error": "API Key Revoked", "message": "...", "key_prefix": "..."}}` | Dict inside `HTTPException` |
| `POST /v1/payments/invoice` (Rate Limited) | 429 Too Many Requests | `{"detail": "Too many invoice creation requests. Please retry in X seconds."}` | Rate limiter check with `Retry-After` header |
| `POST /v1/payments/invoice` (Unknown Tier/Asset) | 422 Unprocessable | `{"detail": [{"loc": ["body", "target_tier"], "msg": "...", "type": "value_error"}]}` | FastAPI / Pydantic default validation handler |
| `POST /v1/payments/invoice` (Target Key Not Found) | 400 Bad Request | `{"detail": "Target API key not found."}` | Plain string inside `HTTPException` |
| `GET /v1/payments/invoice/:id` (Not Found) | 404 Not Found | `{"detail": "Invoice '...' not found."}` | Plain string inside `HTTPException` |
| `POST /v1/payments/invoice/:id/claim` (Storage Error) | 400 Bad Request | `{"detail": "Invalid claim secret for invoice."}` | Caught `StorageError`, string `HTTPException` |
| `POST /v1/payments/verify-solana` (Unbound Payment) | 400 Bad Request | `{"detail": "Payment verification requires an active invoice..."}` | Plain string inside `HTTPException` |
| `POST /v1/payments/verify-solana` (Verification Failed) | 400 Bad Request | `{"detail": "Payment verification failed: ..."}` | Caught `VerificationError`, string `HTTPException` |
| `POST /v1/payments/verify-solana` (RPC Error) | 502 Bad Gateway | `{"detail": "Solana RPC communication error: ..."}` | Caught `RPCError`, string `HTTPException` |
| `POST /v1/payments/verify-solana` (Asset/Amount Mismatch) | 400 Bad Request | `{"detail": "Payment asset '...' does not match..."}` | Plain string inside `HTTPException` |
| `POST /v1/payments/webhook` (Auth Failed) | 401 Unauthorized | `{"detail": "Invalid or missing X-Webhook-Secret header."}` | Plain string inside `HTTPException` |
| `POST /v1/payments/webhook` (Verification/RPC) | 400 / 502 | `{"detail": "Webhook payment verification failed: ..."}` | Caught `VerificationError` / `RPCError` |
| `GET /v1/payments/status/:signature` (Malformed Sig) | 422 Unprocessable | `{"detail": "Solana transaction signature must be valid Base58..."}` | Manual string `HTTPException(422)` |
| `POST /v1/keys/generate-demo` (Disabled) | 403 Forbidden | `{"detail": "Demo key issuance is disabled..."}` | Plain string inside `HTTPException` |
| `GET /v1/health` (DB Failed) | 503 Unavailable | `{"detail": "Database health check failed: ..."}` | Caught `StorageError`, string `HTTPException` |
| `GET /metrics` (Unauthorized) | 401 Unauthorized | `{"detail": "Unauthorized access to metrics exposition endpoint."}` | Plain string inside `HTTPException` with `WWW-Authenticate` |

---

## 3. Inconsistencies & Architectural Deficiencies

1. **Mixed Detail Types (Strings vs. Dictionaries vs. Lists):**
   - Certain endpoints wrap a dictionary in `detail` (`/v1/briefing/latest` when unauthenticated, `/v1/account/quota`), while others wrap a string (`/v1/payments/verify-solana`, `/v1/keys/generate-demo`, auth exhaustion).
   - FastAPI validation errors return a list of dictionaries in `detail`.
   - Autonomous agents cannot reliably parse `detail` without runtime type sniffing.
2. **Absence of Machine-Readable Error Codes:**
   - Callers must inspect human-facing English strings or regex match messages (e.g. `"requires an active invoice" in res.json()["detail"]`) to determine the root cause. If phrasing changes, agent workflows break silently.
3. **Implicit vs. Explicit Retry Guidance:**
   - Only HTTP 429 endpoints currently return `Retry-After` headers. Transient RPC communication errors (HTTP 502) and database health failures (HTTP 503) indicate no explicit retry guidance, causing agents to either fail immediately or retry aggressively in tight loops.
4. **Missing Request Correlation Tracing:**
   - In `get_latest_briefing`, a request ID (`req_...`) is generated for internal storage refunds, but it is **never returned** to the client via response headers or JSON bodies.
   - Other endpoints generate no request ID at all. Correlating client errors with server audit logs requires searching timestamps and IP addresses.
5. **No Centralized Error Registry:**
   - There is no programmatic endpoint or exported registry from which autonomous agents can discover error codes, recovery instructions, or documentation links.

---

## 4. Client & Integration Dependency Analysis

We audited all internal and external consumers of Moltbook Alpha API:

1. **Automated Test Suite (17 modules, 165 tests):**
   - 21 tests specifically assert on `res.json()["detail"]`:
     - 7 tests assert `detail` is a dict with key `"error"` (e.g. `test_auth.py:16`, `test_quota.py:15, 26, 37`).
     - 14 tests assert substring containment in string `detail` (e.g. `test_adversarial_payments.py:373`, `test_rate_limiter.py:148`, `test_health.py:23`).
   - Multiple tests assert `res.status_code == 422` on validation failures.
2. **Commercial Client SDK Walkthrough (`examples/client_demo.py`):**
   - Step 3 asserts `resp.status_code == 402` and parses `resp.json()`.
   - Step 10 asserts `resp.status_code == 402` on exhausted balance.
   - Step 11 asserts `resp.status_code == 403` on invalid key.
   - Step 12 asserts `resp.status_code == 422` on malformed transaction signature.
   - Step 13 asserts `resp.status_code == 429` and checks `Retry-After` header.
3. **Moltbook Community Agent Client (`moltbook_client.py`):**
   - Interacts with Moltbook community API; does not directly consume Moltbook Alpha local endpoints, but shares common error handling conventions.
4. **External Developer & Autonomous Agent Integrations:**
   - Autonomous agents querying `/v1/briefing/latest` or `/v1/account/quota` need structured JSON to trigger payment verification, top-up invoices, or backoff delays.

---

## 5. Security Controls & Secret Redaction Review

- **Secret Handling:**
  - Full API keys (`molt_sol_...`, `molt_live_...`) are hashed using SHA-256 before database insertion; only truncated prefixes (`molt_sol_abc...`) appear in audit logs.
  - Claim secrets (`sec_...`) are hashed with PBKDF2-HMAC-SHA256 (600,000 iterations); raw secrets are never logged.
  - The webhook secret (`X-Webhook-Secret`) prefix is truncated to 4 characters in failure logs.
- **Redaction Requirement for Error Responses:**
  - Error responses must **never** leak raw exception stack traces, internal file paths (`I:\Scripts and Programs\...`), database credentials, or unmasked secrets.
  - When internal server errors (HTTP 500) occur, the raw exception details are logged securely to the audit table and stderr with a unique `request_id`, while the client receives a safe, generic message referencing the `request_id`.

---

## 6. Proposed Unified Error Contract Architecture

We propose a versioned, machine-readable schema for all error responses:

```json
{
  "code": "PAYMENT_REQUIRED",
  "message": "Access requires an active API key or payment.",
  "details": {
    "price": "Starter: $1 (50 queries), Pro: $5 (300 queries), Premium: $20 (10,000 queries / 30 days).",
    "purchase_instructions": {
      "treasury_wallet": "DQkseq8m92h9mQbcQjDRSESAxphpAroKjqyGeSAoKCiC",
      "rates": { ... },
      "verify_endpoint": "POST /v1/payments/verify-solana"
    }
  },
  "retryable": false,
  "retry_after": null,
  "request_id": "req_5a1e2f7b8c9d0e1f",
  "docs_url": "https://theheiszt.github.io/moltbook-alpha/docs/errors#PAYMENT_REQUIRED",
  "detail": { ... }
}
```

### Compatibility Bridge (`detail` field)
To maintain 100% backwards compatibility with existing clients and test suites:
- If legacy clients or existing tests inspect `res.json()["detail"]`, `detail` is dynamically populated:
  - If `details` contains legacy dictionary keys (e.g. `"error"`, `"remedy"`, `"purchase_instructions"`), `detail` provides that dictionary.
  - If legacy callers expect a string, `detail` matches `message`.
  - For validation errors (HTTP 422), `detail` retains the list of Pydantic validation error dicts (`loc`, `msg`, `type`).
- Response headers consistently include:
  - `X-Request-ID: req_...`
  - `Retry-After: <seconds>` (when `retryable` is true and a delay is known).
  - `Content-Type: application/json`.

---

## 7. Baseline Verification

- **Git Branch:** `feat/commercial-api-hardening`
- **Starting Commit:** `cf951e2` (`feat(billing): implement 30-day premium access, 90-day top-ups, and edf ledger accounting`)
- **Pytest Baseline:** **165 passed in 23.40s** across 17 test modules.
- **Client Demo Baseline:** **All 15 customer journey steps passed with 100% success**.
- **Working Tree:** Clean.
