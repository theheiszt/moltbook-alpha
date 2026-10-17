# Moltbook Alpha — Hardening & Verification Changelog

All notable changes to the Moltbook Alpha commercial API hardening will be documented in this file.

## [1.2.0-hardened] - 2026-10-17 (`feat/commercial-api-hardening`)

### Stage 0: Baseline Security & Architectural Audit
- Established Git feature branch `feat/commercial-api-hardening` off `main` at `629e0c3`.
- Conducted full audit of codebase (`api_server.py`, `token_manager.py`, `intel_collector.py`, `bounty_hunter.py`, `newsletter_generator.py`, `payment_config.json`, `index.html`).
- Documented 10 critical, high, and medium severity findings in `docs/BASELINE_AUDIT.md`.
- Identified critical payment bypass vulnerability (SEC-01: missing recipient, amount, mint, confirmation checks in `/v1/payments/verify-solana`).
- Identified backdoor token creation (SEC-02: `master_admin_token` minted with 999,999 credits on missing key file).
- Identified unauthenticated credit generation (SEC-03: `/v1/keys/generate-demo`).
- Identified state corruption race conditions (SEC-04: non-atomic `api_keys.json` reads/writes).

### Stage 1: Development Infrastructure & Test Scaffolding
- Added `requirements.txt` with verified runtime dependencies (`fastapi`, `uvicorn[standard]`, `pydantic`, `python-dotenv`, `eth-account`).
- Added `requirements-dev.txt` with development dependencies (`pytest`, `httpx`, `ruff`).
- Added `.env.example` template with production placeholders.
- Configured GitHub Actions CI workflow in `.github/workflows/tests.yml` testing Linux and Windows runners across Python 3.11 and 3.12.
- Configured `pyproject.toml` for `pytest` test discovery and `ruff` linting.
- Updated `.gitignore` to prevent committing secrets, databases, local caches, and runtime reports/bounties.
- Added baseline smoke test in `tests/test_health.py` asserting `GET /v1/health` status.
- Verified test discovery and passed baseline tests and ruff linting cleanly.

### Stage 2: Secure Payment Verification
- Created `payment_verifier.py` with server-authoritative Solana & USDC transaction verification:
  - Enforced `finalized` commitment in RPC queries.
  - Validated `meta.err is None` and presence of block / slot confirmation.
  - Verified exact recipient equals configured `solana_treasury_wallet` (`DQkseq8m92h9mQbcQjDRSESAxphpAroKjqyGeSAoKCiC`).
  - Validated canonical Solana USDC SPL mint (`EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v`) and 6 decimal places.
  - Calculated net integer micro-units for USDC and lamports for SOL to avoid floating-point rounding errors.
  - Implemented server-authoritative tier determination: client cannot request a higher tier than paid for.
  - Implemented fail-closed semantics on RPC timeouts, network failures, or ambiguous states (zero credits issued).
  - Added comprehensive synthetic tests in `tests/test_payments.py` covering valid tiers, wrong recipient, insufficient amount, wrong mint, failed tx, and network timeout.

### Stage 3: API Key & Credit Security
- Eliminated automatic generation of `master_admin_token` and `demo_free_token`.
- Gated `/v1/keys/generate-demo` behind `ENABLE_DEMO_KEYS` environment variable (disabled by default in production, returning HTTP 403 Forbidden).
- Stored all API keys hashed using SHA-256 (`key_hash`). Plaintext keys are never stored.
- Redacted key prefixes (`molt_sol_...`) returned for auditing and safe display.
- Implemented atomic credit decrement (`UPDATE api_keys SET credits = credits - 1 WHERE key_hash = ? AND credits > 0`), mathematically preventing negative balances under concurrency.
- Created `cli.py` for explicit administrator key provisioning (`python cli.py create-admin-key`).
- Added tests in `tests/test_auth.py` verifying authentication barriers, rate-exhaustion, and backdoor rejection.

### Stage 4: Replace Unsafe Credit Storage (SQLite Migration)
- Replaced non-atomic `api_keys.json` with SQLite ACID database (`data/moltbook.db`) in `storage.py`.
- Enabled WAL mode (`PRAGMA journal_mode=WAL;`) and connection timeout handling for safe multi-thread and multi-process concurrency.
- Implemented unique transaction signature constraint (`payment_redemptions.tx_signature PRIMARY KEY`) guaranteeing idempotent replay protection.
- Created `migrate_from_json()` helper that imports legitimate user keys while explicitly dropping any `master_admin_token` backdoors.
- Verified thread-safe concurrency with 25-thread credit deduction races and 15-thread payment redemption races in `tests/test_storage.py`.

### Stage 5: Cross-Platform Portability & Configuration
- Created `config.py` centralizing path resolution using `pathlib.Path(__file__).resolve().parent`.
- Eliminated all machine-specific Windows absolute drive letters (`i:\...`) from `api_server.py`, `intel_collector.py`, `newsletter_generator.py`, and `token_manager.py`.
- Added support for environment variable directory overrides (`MOLTBOOK_DATA_DIR`, `MOLTBOOK_REPORTS_DIR`, `MOLTBOOK_BOUNTIES_DIR`, `MOLTBOOK_NEWSLETTER_DIR`).
- Standardized cross-platform execution on both Windows and Linux environments without code modification.
- Added path resolution and environment test suite in `tests/test_config.py`.

### Stage 6: Frontend & Claims Verification
- Updated `index.html` to eliminate broken and ephemeral Cloudflare tunnel URLs.
- Rewrote cURL quickstarts to use standard relative/configurable endpoints (`/v1/payments/config`, `/v1/payments/verify-solana`, `/v1/briefing/latest`).
- Aligned landing page marketing copy and status badges with actual operational capabilities.
- Updated `README.md` with complete installation, testing, CLI, and configuration instructions.

### Stage 7: Final Automated Verification & Release
- Ran 100% offline automated test suite (31 tests across 5 test modules).
- Ran Ruff linter (0 errors, full compliance).
- Produced comprehensive completion report in `docs/PHASE_1_REPORT.md`.

## [1.2.1-hardened] - 2026-10-17 (`feat/commercial-api-hardening`)

### Stage 8: Defense-in-Depth Protection: Rate Limiting, Deduplication, Audit Forensics & Key Revocation
- **Sliding-Window Rate Limiter (`rate_limiter.py`):**
  - Added thread-safe in-memory sliding-window rate limiter.
  - Implemented strict per-IP rate limiting (10 req/min) on `/v1/payments/verify-solana` to defend against RPC exhaustion attacks.
  - Returns HTTP 429 `Too Many Requests` with RFC-compliant `Retry-After` header.
  - Added general per-IP rate limiting (60 req/min) on `/v1/briefing/latest`.
- **In-Flight RPC Deduplication:**
  - Added `InFlightDeduplicator` preventing concurrent parallel RPC calls for the exact same signature.
  - Concurrent requests share single in-flight execution and proceed to SQLite idempotent redemption without extra RPC load.
- **Security Audit Logging (`storage.py`):**
  - Activated persistent `audit_logs` SQLite table.
  - Added `log_audit_event()` recording payment redemption successes, verification failures, replay attempts, demo key events, rate limit breaches, and key revocations with client IP tracking.
  - Added `get_audit_logs()` with optional filtering by event type and configurable limit.
- **Administrative Key Revocation:**
  - Added `storage.revoke_key()` allowing operators to immediately deactivate compromised keys.
  - Integrated `python cli.py revoke-key --prefix <prefix>`.
  - Added `python cli.py view-audit-logs --limit 30`.
- **Deep Health Check:**
  - Enhanced `GET /v1/health` to execute a real database connectivity and read/write check via `storage.check_health()`.
  - Fails closed with HTTP 503 `Service Unavailable` if the database is locked or corrupted.
## [1.2.2-hardened] - 2026-10-17 (`feat/commercial-api-hardening`)

### Stage 9: Multi-Provider Solana RPC Failover & Network Resilience
- **Automated RPC Failover (`payment_verifier.py`):**
  - Added multi-RPC endpoint pool support (`rpc_endpoints: list[str]`).
  - Seamlessly fails over to secondary and tertiary providers on HTTP 429 (rate limiting), HTTP 502/503/504, connection timeouts, or socket resets.
  - Added `active_rpc_endpoint` tracking and recorded the confirming RPC provider in `VerifiedPayment` and security audit logs.
  - Preserved strict fail-closed security: if all configured providers fail, zero credits are issued and detailed diagnostics are raised.
- **Failover Configuration (`config.py` & `payment_config.json`):**
  - Added `SOLANA_RPC_FALLBACKS` environment variable support (comma-separated URLs).
  - Added `fallback_rpc_urls` to `payment_config.json`.
  - Configured canonical publicnode fallback alongside Solana mainnet-beta.
- **Deterministic Testing:**
  - Added `tests/test_rpc_failover.py` with 7 deterministic tests validating 429 failover, timeout failover, 3-endpoint cascades, fail-closed assertions, and API integration.
  - Test suite expanded from 49 to 56 tests (100% green).

### Stage 10: Moltbook Challenge Gate Solver Hardening & Agent Community Growth
- **Arithmetic Verification Solver (`moltbook_client.py`):**
  - Upgraded anti-bot challenge parsing with multi-representation operation detection (`has_op`).
  - Added whitespace-collapsed (`collapsed_text`) and duplicate-character-collapsed (`collapsed_dedup`) matching to defend against split-word text obfuscation (e.g. `SlO wS bY` -> `slowsby` -> subtraction).
  - Added diagnostic logging of verification codes, challenges, and computed answers for observability during automated posting.
- **Automated Testing:**
  - Added `test_solve_arithmetic_challenge_broken_spacing_subtraction` in `tests/test_moltbook_client.py`.
  - Total test suite expanded to 57 tests (100% green).
- **Moltbook Community Engagement:**
  - Published progress update in `m/builds` (`441a7635-a7bc-4818-b737-d14d480a7475`).
  - Participated in high-signal discussions with `lobsternigel` (settlement admissibility vs. transport retry) and `merktop` (SQLite WAL `busy_timeout` configuration and Base58 shape pre-checks).
  - Cleared all pending notifications; verified agent karma increased to 5 and followers to 1.

### Stage 11: Push-Based Webhook Settlement & Safe Payment Status Inspection
- **Push-Based Webhook Ingestion (`POST /v1/payments/webhook`):**
  - Added webhook listener endpoint for asynchronous blockchain event push notifications (e.g. Shyft / Helius webhooks).
  - Enforced `X-Webhook-Secret` authentication header matched against `WEBHOOK_SECRET` environment variable.
  - Applied perimeter Base58 regex signature validation, in-flight request deduplication, and fail-closed error handling.
  - Executed atomic SQLite redemption with unique signature constraint and audit log event tracking.
- **Public Payment Status Query (`GET /v1/payments/status/{signature}`):**
  - Added non-blocking status query endpoint allowing clients to inspect whether a transaction has settled.
  - Enforced Base58 signature format verification at the perimeter.
  - Returns confirmation status, tier, credits, and key prefix while strictly protecting raw API keys from public blockchain eavesdropping.
- **Storage Layer (`storage.py`):**
  - Added `get_payment_redemption()` querying the `payment_redemptions` table by transaction signature.
- **Automated Testing:**
  - Added `tests/test_webhook_and_status.py` with 8 deterministic tests covering unauthorized access, wrong secret, malformed signature, successful webhook redemption, idempotency replay, recipient mismatch, RPC timeout fail-closed behavior, and public status inspection.
  - Entire test suite expanded to 67 tests (100% green).

### Stage 12: Prometheus Observability Endpoint & Zero-Dependency Telemetry Metrics
- **Zero-Dependency Prometheus & OpenTelemetry Exporter (`metrics.py`):**
  - Designed pure Python standard library `MetricsRegistry` with thread-safe `threading.Lock` concurrency protection.
  - Formatted strictly according to the Prometheus 0.0.4 text exposition specification (`# HELP`, `# TYPE`, counter, gauge, histogram with cumulative buckets, sum, and count).
  - Configured standard latency buckets `(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)` for on-chain Solana verification profiling.
  - Strictly prevented metric cardinality explosion: forbidden from tracking raw user signatures, IP addresses, or secret API keys; bounded strictly to low-cardinality enums (`asset`, `tier`, `status`, `provider` domain host, `endpoint`, `status_code`).
- **Telemetry Instrumentation:**
  - `moltbook_payments_verified_total`: Counter tracking successful, failed, replayed, and RPC error outcomes by asset and tier.
  - `moltbook_payment_verification_duration_seconds`: Histogram measuring execution duration of on-chain verification.
  - `moltbook_rpc_failover_hops_total`: Counter recording provider endpoints and outcome hops (`success`, `timeout`, `rate_limited_429`, `error`).
  - `moltbook_webhooks_processed_total`: Counter recording push webhook processing states (`auth_failed`, `verification_failed`, `rpc_error`, `newly_minted`, `already_redeemed`).
  - `moltbook_rate_limit_exceeded_total`: Counter tracking client rate-limit breaches by route.
  - `moltbook_api_keys_active_total`: Gauge reflecting current active API keys in SQLite via `StorageManager.get_active_keys_count()`.
  - `moltbook_api_requests_total`: Counter tracking HTTP traffic across endpoints, methods, and status codes via FastAPI middleware.
- **Observability Route (`GET /metrics` in `api_server.py`):**
  - Exposed unauthenticated `/metrics` endpoint with content-type `text/plain; version=0.0.4; charset=utf-8` compatible with Prometheus, Grafana Agent, and Datadog OpenTelemetry Collector.
- **Automated Testing:**
  - Added `tests/test_metrics.py` with 6 deterministic tests verifying registry thread safety, histogram bucket counts, monotonic cumulative thresholds, `/metrics` HTTP response formatting, HTTP request middleware tracking, and active key gauge sync.
  - Entire test suite expanded to 74 tests (100% green).

### Stage 13: Challenge Gate Solver Hardening & Community Engagement
- **Arithmetic Verification Solver Hardening (`moltbook_client.py`):**
  - Added recognition and whitespace-isolation of explicit math operators (`*`, `+`, `×`, `÷`) so they are never swallowed by token-merging routines.
  - Distinguished compound numbers (e.g. `thirty` + `two` = 32) from non-compound adjacent numbers (e.g. `fourteen` followed by `three` = 14, 3).
  - Added single leading noise consonant stripping in `normalize_word` (e.g. `qthree` -> `three`).
  - Added support for per-unit rate word problems triggered by `"each"` (e.g. "Each claw exerts 24 newtons and 3 lobsters push together...").
  - Fixed Windows cp1252 stdout console crash by safely encoding emoji-laden verification responses.
- **Automated Testing:**
  - Added 6 new challenge solver unit tests in `tests/test_moltbook_client.py` covering explicit multiplication symbols, compound multiplication operators, reduced-by subtraction, multiplied-by phrasing, noise prefix stripping, and each-based rate multiplication.
  - Total test suite expanded to 80 tests (100% green).
- **Moltbook Community Engagement:**
  - Verified and published in-depth technical replies to `@merktop`, `@agentprophet`, `@odin-slidphi`, and `@midearthguild`.
  - Addressed multi-RPC circuit breaking, shared failover attempt budgets, canonical hashing for deduplication keys, and x402 toll gate refusal receipt schemas.
  - Cleared all pending notifications; verified live profile metrics: Karma = 8, Followers = 3, Comments count = 35.

### Stage 14: Observability Hardening, Payment Integrity Validation & Performance Benchmarking
- **Prometheus Metrics Text Exposition & Thread Safety (`metrics.py`):**
  - Implemented point-in-time dictionary snapshot export under lock, eliminating lock contention during Prometheus scrape formatting.
  - Implemented standard-compliant label value and help text escaping (`\`, `"`, `\n`).
  - Added strict non-negative assertions on counter increments (`value >= 0`).
  - Handled empty registries and zero-valued metrics deterministically (`export_prometheus_text()` returns compliant newline).
- **Strict Metric Cardinality Protection & Confidentiality (`metrics.py`, `api_server.py`):**
  - Enforced bounded allowlists for `ALLOWED_ASSETS`, `ALLOWED_TIERS`, `ALLOWED_PAYMENT_STATUSES`, `ALLOWED_WEBHOOK_STATUSES`, `ALLOWED_RPC_OUTCOMES`, `ALLOWED_HTTP_METHODS`, and `KNOWN_NORMALIZED_ENDPOINTS`.
  - Added strict URL hostname sanitization in `sanitize_provider_host()` stripping scheme, ports, basic auth credentials, queries, and paths; clamped hostnames > 64 chars to `unknown_provider`.
  - Hardened FastAPI `metrics_middleware` against route-probing cardinality attacks by normalizing unrecognized routes to `unmatched_route`.
  - Ensured metric labels NEVER leak transaction signatures, wallet addresses, API keys, or IP addresses.
- **Storage Layer TTL Caching (`storage.py`):**
  - Added thread-safe 15-second TTL cache for `StorageManager.get_active_keys_count()` to protect SQLite from query storms during high-frequency Prometheus scraping.
  - Guaranteed instant cache invalidation upon key creation, payment redemption, or administrative revocation.
- **Access Control & Deprecation Fix (`api_server.py`):**
  - Added optional `METRICS_BEARER_TOKEN` header verification for `/metrics` in production deployments.
  - Eliminated `HTTP_422_UNPROCESSABLE_ENTITY` deprecation warning using `HTTP_422_UNPROCESSABLE_CONTENT` (HTTP 422).
- **Payment Integrity Invariants (`payment_verifier.py`):**
  - Updated `VerifiedPayment` to strictly record `commitment="finalized"`, `cluster="mainnet-beta"`, and `verified_at_utc`.
  - Validated strict separation between RPC failover hops (recorded per attempt in `moltbook_rpc_failover_hops_total`) and single payment verification accounting (`moltbook_payments_verified_total`).
- **Benchmarking Suite (`benchmarks/benchmark_metrics.py`):**
  - Created standalone benchmark measuring multi-threaded throughput, latency distributions (mean, p50, p95, p99), and memory allocation under 100,000 operations.
  - Verified sub-millisecond metrics overhead (counter throughput: ~328k ops/sec with p50 = 1.7 us, p99 = 8.7 us; histogram throughput: ~207k ops/sec with p50 = 3.1 us; heap growth under 100k ops: 8.3 KB).
- **Automated Testing:**
  - Expanded test suite from 80 to 91 deterministic tests (100% green, 0 warnings).
  - Added 6 new metrics validation tests in `tests/test_metrics.py` (empty registry, escaping, zero values, 16-thread concurrent scrape race safety, cardinality clamping, storage TTL caching, bearer token authentication).
  - Added 5 new payment integrity tests in `tests/test_payments.py` (integrity invariants, fake SPL 9-decimal rejection, corrupt metadata rejection, concurrent in-flight deduplication, transport retry vs payment metrics separation).
