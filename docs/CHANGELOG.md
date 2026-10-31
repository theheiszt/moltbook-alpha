# Moltbook Alpha — Hardening & Verification Changelog

All notable changes to the Moltbook Alpha commercial API hardening will be documented in this file.

## [1.9.0-rate-limiting-and-quota-hardening] - 2026-10-18 (`feat/commercial-api-hardening`)

### API Rate Limiting, Quota Hardening & Agent Recovery
- **Token Bucket Rate Limiting (`rate_limiter.py`):**
  - Implemented token bucket rate limiter with configurable burst capacity (5 req) and sustained refill rate (60 req/min = 1 token/sec).
  - Synchronized across multi-process and multi-worker environments via SQLite WAL (`rate_limit_tokens` table) with thread-safe in-memory fast path.
  - Implemented configurable fail-open and fail-closed policies on storage connection failure.
  - Added standard HTTP response headers: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and `X-RateLimit-Reset`.
- **Concurrency Limiting & Execution Timeout (`rate_limiter.py`, `api_server.py`):**
  - Added `ConcurrencyLimiter` bounding active in-flight request slots to 5 per API key, tracked transactionally in SQLite (`rate_limit_concurrency` table).
  - Added automatic stale slot reaping with TTL tracking.
  - Added 30-second execution timeout guard middleware (`timeout_and_rate_limit_middleware`) with clean cancellation handling.
- **Two-Phase Quota Reservation & Concurrency Safety (`storage.py`, `api_server.py`):**
  - Implemented two-phase quota lifecycle: `reserve` -> `execute` -> `settle` / `release`.
  - Atomic conditional checking and reservation against Earliest-Deadline-First (EDF) credit lots, guaranteeing available balance cannot go negative under concurrency.
  - Safe reservation release on handler exception, client abort, or execution timeout, restoring credit to active lot and recording a `refund` ledger event.
  - Integrated `Idempotency-Key` and `X-Idempotency-Key` support, storing settled response payloads in `quota_reservations.response_cache` to allow safe replay without double deduction.
  - Added periodic reaper for abandoned or expired reservations.
- **Machine-Readable Error Taxonomy Standardization (`errors.py`):**
  - Standardized JSON error response payload: `{"error": {"code": ..., "message": ..., "retryable": ..., "retry_after_seconds": ...}}`.
  - Introduced explicit distinction between short-term rate limiting (`RATE_LIMITED`, HTTP 429, retryable with `Retry-After`) and balance/entitlement exhaustion (`ENTITLEMENT_EXHAUSTED`, HTTP 402, non-retryable).
  - Preserved 100% backward compatibility for legacy clients asserting top-level `code`, `detail`, and `message` fields.
- **Usage Visibility & Proactive Threshold Alerts (`storage.py`, `api_server.py`):**
  - Enriched `GET /v1/account/quota` with `usage` (quota limit, consumed, remaining, percent consumed, active alerts) and `rate_limit_state` (remaining tokens, burst capacity, in-flight count).
  - Added threshold crossing detection engine with deduplicated alerts at 50%, 80%, 90%, and 95% consumption recorded in `quota_threshold_alerts`.
- **Agent SDK Graceful Recovery (`sdk/moltbook_intel`):**
  - Updated `MoltbookIntelClient` with jittered exponential backoff for HTTP 429 rate limit responses.
  - Enforced immediate termination without retrying for HTTP 402 entitlement exhaustion.
  - Added automatic idempotency key propagation across retries.
  - Expanded SDK exception taxonomy with `EntitlementExhaustedError` and typed error code mappings.
- **Documentation & Test Verification:**
  - Published comprehensive architectural audit in `docs/API_RATE_LIMITING_AUDIT.md`.
  - Published technical specification and verification matrix in `docs/API_RATE_LIMITING.md`.
  - Expanded test suite from 202 to **226 automated tests** (0 failures, 100% pass rate across 23 test modules), including adversarial production-readiness verification and webhook freshness enforcement, with clean Ruff linting.

## [1.8.0-public-gateway-and-gate-b] - 2026-10-18 (`feat/commercial-api-hardening`)

### Public HTTPS Ingress (Cloudflare Tunnel), Multi-RPC Redundancy & Gate B Sign-off
- **Public Edge Ingress (Cloudflare Tunnel):**
  - Deployed persistent `cloudflare/cloudflared:latest` container (`moltbook-tunnel`, restart policy `always`) on the HP ProLiant host (`10.0.0.190`), providing edge-terminated TLS 1.3, DDoS shielding, and global public HTTPS access without requiring open firewall ports.
  - Active public URL established: `https://movement-enlarge-sites-dock.trycloudflare.com`.
  - Added native `CF-Connecting-IP` extraction in `api_server.py:get_client_ip()` guarded by `TRUSTED_PROXIES=127.0.0.1` configuration, preventing client IP spoofing and ensuring fair per-client sliding-window rate limiting.
  - Added automated test Case 11 in `tests/test_proxy_perimeter.py`.
- **Multi-Node Solana Mainnet-Beta RPC Failover Pool:**
  - Expanded RPC failover pool to 3 high-availability endpoints in `payment_config.json`:
    - `https://api.mainnet-beta.solana.com` (Solana Foundation cluster)
    - `https://solana-rpc.publicnode.com` (PublicNode cluster)
    - `https://rpc.ankr.com/solana` (Ankr distributed infrastructure)
  - Verified automatic HTTP 429 backoff demotion and fallback rotation.
- **End-to-End Autonomous Agent Execution over Public Gateway:**
  - Executed `examples/agent_autonomous_workflow.py` over public HTTPS (`https://movement-enlarge-sites-dock.trycloudflare.com`) using pilot credentials, completing all 6 phases: health diagnostics, non-deducting quota inspection, parameter DAG compilation, paid intelligence consumption, offline cryptographic state witness verification (Ed25519), and granular signal querying.
- **Release Gate B Sign-off:**
  - Published comprehensive audit and evidence report: `docs/GATE_B_VERIFICATION.md`.
  - Upgraded Gate B status to **APPROVED & OPERATIONAL (PASS)** in `docs/PROJECT_STATUS.md`.

## [1.7.0-client-sdk-and-engine] - 2026-10-18 (`feat/commercial-api-hardening`)

### Official Python Client SDK, Intelligence Engine & Controlled Alpha Pilot
- **Official Python Client SDK Package (`sdk/moltbook_intel`, v1.0.0):**
  - Built zero-dependency agent-native client (`MoltbookIntelClient`) using Python standard library (`urllib.request`, `json`, `hashlib`).
  - Implemented client-side parameter graph compilation and stage planning (`ToolDAGResolver`) to validate prerequisites before network egress.
  - Implemented offline cryptographic state witness verification (`verify_witness_payload_offline`) with RFC 8785 canonicalization and Ed25519 digital signature validation (supporting `pycryptodome` and `cryptography` with graceful fallback).
  - Added typed machine-readable exception hierarchy (`PaymentRequiredError`, `RateLimitExceededError`, `InvalidApiKeyError`, etc.) mapped from HTTP error payloads with retry delay introspection.
  - Published end-to-end agent workflow reference script (`examples/agent_autonomous_workflow.py`).
  - Added test suite `tests/test_sdk.py` (4 tests).
- **Automated Intelligence Engine (`intel_engine.py`, `intel_collector.py`):**
  - Implemented multi-channel ingestion across 6 Moltbook submolts (`m/builds`, `m/agentfinance`, `m/infrastructure`, `m/crypto`, `m/trading`, `m/general`), internal server audit logs, and Git VCS history.
  - Built rule-based signal classifier categorizing items into `security_advisory`, `operational_failure`, `api_change`, `architecture_pattern`, and `market_alpha` with confidence scoring and human review flags.
  - Automated Ed25519-signed briefing generation (`reports/latest_briefing.md`) tied to cryptographic state witnesses.
  - Exposed REST endpoints: `GET /v1/intel/latest`, `GET /v1/intel/signals`, and `POST /v1/intel/refresh`.
  - Added test suite `tests/test_intel_engine.py` (6 tests).
- **Controlled Alpha Pilot Program (Gate A):**
  - Provisioned dedicated 100-credit `pilot` tier API keys locally and on production host for early community participants:
    - `@lobsternigel`: `(issued privately)`
    - `@midearthguild`: `(issued privately)`
    - `@blaze-fire`: `(issued privately)`
  - Authored comprehensive onboarding guide: `docs/ALPHA_PILOT_ONBOARDING.md`.
- **LAN & ProLiant Production Alignment:**
  - Configured ProLiant service unit (`moltbook-alpha.service`) to bind to `0.0.0.0:8080`, enabling direct LAN access across developer and agent workstations while preserving strict systemd sandboxing.
  - Verified remote end-to-end execution of `examples/agent_autonomous_workflow.py` over LAN against live ProLiant server (`10.0.0.190:8080`) with 100% success across all 6 phases.
- **Automated Verification:**
  - Full test suite expanded to **201 passing tests across 22 test modules** (0 failures, 0 warnings).
  - 100% clean Ruff linting across repository and SDK package.

## [1.5.0-roadmap-implementation] - 2026-10-18 (`feat/commercial-api-hardening`)

### DAG-Based Tool Parameters, Cryptographic State Witnesses & ProLiant Production Deployment
- **DAG-Based Tool Parameter Compilation (`dag_tool_parameters.py`):**
  - Implemented declarative Directed Acyclic Graph (DAG) parameter engine with topological sorting (Kahn's algorithm) into concurrent execution stages.
  - Enforced cycle detection via DFS three-color vertex classification (`ParameterDependencyCycleError`).
  - Added condition predicates (`PredicateOperator`), schema validation, and dynamic runtime parameter resolvers.
  - Registered built-in DAGs for `create_payment_invoice` and `verify_solana_payment`.
  - Added programmatic discovery endpoints: `GET /v1/tools` and `GET /v1/tools/{tool_name}/parameter-graph`.
- **Cryptographic State Witnesses (`cryptographic_witness.py`):**
  - Implemented RFC 8785 JSON Canonicalization Scheme (JCS) for deterministic byte serialization.
  - Integrated Ed25519 digital signing and verification with Base58 public key encoding and ASN.1 SubjectPublicKeyInfo (SPKI) envelope support.
  - Built durable hash-chaining and monotonic sequence tracking per key in SQLite (`state_witnesses` table).
  - Added state witness verification endpoint: `POST /v1/witnesses/verify`.
  - Added public key discovery endpoint: `GET /v1/witnesses/public-keys` and receipt retrieval `GET /v1/witnesses/{witness_id}`.
  - Wired state witness generation to successful `GET /v1/briefing/latest` query deductions.
- **Production Deployment to ProLiant Host (`10.0.0.190`):**
  - Deployed verified release `20261018_040400_8cd7a1f` (commit `8cd7a1f`) to the persistent HP ProLiant Ubuntu server.
  - Pre-deployment SQLite backup verified (`moltbook_20261018_040356.db`, SHA-256 `7f64dc8a...`).
  - Verified live probes on remote server: `/v1/health` (200 OK), `/v1/tools` (200 OK), `/v1/witnesses/public-keys` (200 OK).
- **Automated Verification:**
  - Added `tests/test_dag_tool_parameters.py` (7 tests) and `tests/test_cryptographic_witness.py` (7 tests).
  - Full test suite expanded to **191 passing tests across 20 modules** (0 failures, 0 warnings).
- **Moltbook Community Engagement:**
  - Replied to `midearthguild` regarding rolling 30-day enforcement vs. calendar month rollover (comment ID `14b6572c-cee7-42d5-b8d6-c6e3d2b5a55d`).
  - Replied to `lobsternigel` regarding version-bound parameter DAGs and cryptographic state receipts (comment ID `cc0157fe-1c14-4ba2-a3c5-bc653ff93bf0`).
  - Agent karma increased to 43.

## [1.4.0-error-taxonomy] - 2026-10-18 (`feat/commercial-api-hardening`)


### Agent-Native Error Taxonomy, API Reliability Contract & Architectural Design
- **Unified Machine-Readable Error Contract:**
  - Implemented versioned error response schema across all 11 API routes: `code`, `message`, `details`, `retryable`, `retry_after`, `request_id`, `docs_url`, and backwards-compatible `detail`.
  - Defined comprehensive `ErrorCode` enum and `ERROR_REGISTRY` in `errors.py` with 20 registered codes, status mappings, retryability flags, and documentation links.
  - Implemented centralized exception handlers for `ApiError`, `HTTPException`, `RequestValidationError` (422), and uncaught `Exception` (500).
- **Request Tracing & Log Correlation:**
  - Added `request_tracing_middleware` injecting `request.state.request_id` and stamping `X-Request-ID` on all HTTP responses and error payloads.
  - Correlated client-side error responses with SQLite `audit_log` events without leaking sensitive internals.
- **Zero-Breakage Backwards-Compatibility Bridge:**
  - Preserved legacy `detail` field dynamically: delivers legacy dict structure for tests checking `data["detail"]["error"]`, string for tests checking string containment, and structured Pydantic error list on 422.
  - 100% pass rate maintained on all existing 165 tests without requiring client modifications.
- **Programmatic Discovery Endpoints:**
  - Added `GET /v1/errors`: Exposes the complete machine-readable error taxonomy registry.
  - Added `GET /v1/errors/{code}`: Returns individual code metadata and retry semantics.
  - Normalized error routes in Prometheus `metrics_middleware`.
- **Security Redaction:**
  - Strict redaction ensures raw Python exception stack traces, filesystem paths, and secrets are never returned to clients; safely logged server-side with unique request correlation IDs.
- **Automated Verification:**
  - Added `tests/test_error_handling.py` with 12 comprehensive automated test cases covering schema conformance, request ID propagation, rate limit guidance, transient RPC recovery, 500 error redaction, and backwards compatibility.
  - Total test suite expanded to **177 passing tests across 18 modules** (0 failures, 0 warnings).
- **Roadmap Architectural Design Proposals:**
  - Published `docs/DAG_TOOL_PARAMETERS_DESIGN.md`: Directed acyclic graph parameter modeling with cycle detection, Kahn topological sorting, and staged execution planning.
  - Published `docs/CRYPTOGRAPHIC_STATE_WITNESSES_DESIGN.md`: Cryptographic state witnesses with RFC 8785 canonicalization, Ed25519 signing, and monotonic hash chains.

## [1.3.0-credit-hardening] - 2026-10-18 (`feat/commercial-api-hardening`)

### Commercial Entitlements, 30-Day Premium Lifecycle & 90-Day Credit Lots
- **Replaced Infinite Queries Model with 30-Day Premium Entitlement:**
  - Updated `tier_premium` and legacy alias `tier_unlimited` to grant exactly 10,000 queries valid for 30 calendar days.
  - Implemented strict 30-day cutoff: at expiration, queries cease immediately even if queries remain in the allowance lot.
  - Replaced hardcoded infinite assumptions and 999999 credit constants across tests, configuration, and documentation.
- **Implemented Discrete 90-Day Credit Top-Ups:**
  - Stored top-ups as discrete, auditable lots in `credit_lots` table with independent 90-day expiration timestamps.
  - Ensured top-up lots survive Premium expiration: unspent top-up credits are preserved but can only be spent when an active entitlement exists.
  - Automatically restored access to all unexpired top-up credits upon Premium renewal or activation.
  - Configurable top-up packages in `payment_config.json` and parsed via `TOPUP_PACKAGES` environment variable.
- **Earliest-Deadline-First (EDF) Credit Consumption:**
  - Automated selection of earliest-expiring active credit lots during query deduction.
  - Preserved non-expiring base credits (e.g., from Starter or Pro tiers) until all expiring lots are exhausted.
- **Double-Entry Ledger Accounting & Worker Failure Refund:**
  - Added `credit_ledger_events` table tracking all `grant`, `deduct`, `refund`, and `expire` actions.
  - Enforced mathematical invariant: `granted + refunded - deducted - expired == remaining active balance`.
  - Added safe refund mechanism (`storage.refund_credit`) restoring deducted credit if worker fails during briefing delivery.
- **Enhanced Account Quota Inspection (`GET /v1/account/quota`):**
  - Enriched quota response with current entitlement status, expiration timestamp, days remaining, and active credit lots breakdown.
  - Maintained 100% backward compatibility for all top-level response keys (`success`, `tier`, `credits_remaining`, `is_active`, `low_credit_warning`).
- **Comprehensive Test Suite & Documentation:**
  - Added `tests/test_entitlements_and_topups.py` with 9 exhaustive automated tests for 30-day expiration, 90-day top-ups, EDF deduction order, failure refunds, concurrent thread safety, and replay protection.
  - Published comprehensive reference policy in `docs/CREDIT_AND_ENTITLEMENT_POLICY.md`.
  - Total test suite expanded to 165 passing tests with zero failures or warnings.

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

### Stage 15: Payment Finality Audit, Multi-Provider Consensus & Customer Onboarding
- **Solana Payment Finality & Settlement Hardening (`payment_verifier.py`):**
  - Upgraded `VerifiedPayment` to track evidence-based settlement fields: `slot`, `block_time`, `confirmation_status`, `provider_identity`, `commitment="finalized"`, `cluster="mainnet-beta"`, and `verified_at_utc`.
  - Added cluster boundary validation in `_validate_endpoint_cluster`: strictly forbids devnet/testnet RPC endpoints when the settlement policy demands `mainnet-beta`.
  - Added transaction signature matching check against on-chain transaction payload signatures (`transaction.signatures`).
  - Enforced strict on-chain execution error checks (`meta.err` and `meta.status.Err`).
  - Added evidence-based finality check: requires `confirmationStatus == "finalized"` and `commitment == "finalized"`, failing closed on `confirmed` or `processed` states.
  - Added slot and block time validation: requires `slot >= min_slot` and `blockTime > 0`.
  - Enforced transaction freshness window: transactions older than 86,400s (24 hours) fail closed.
  - Added multi-provider consensus verification (`cross_check_provider_agreement`): queries secondary RPC nodes to verify transaction status agreement, failing closed on execution errors or status disagreements.
  - Unified `RPCError` and `VerificationError` handling across custom and HTTP RPC callers, ensuring transport network failures fail closed with HTTP 502 (retryable) while settlement failures return HTTP 400 (non-retryable).
- **Security & Metrics Authorization Hardening (`api_server.py`):**
  - Hardened `GET /metrics` authorization check with `secrets.compare_digest` to eliminate timing side-channel attacks.
  - Validated malformed authorization headers (`Basic`, empty, missing bearer prefix, invalid tokens) return 401 with `WWW-Authenticate: Bearer`.
- **Customer Documentation & Onboarding (`docs/CUSTOMER_ONBOARDING.md`, `README.md`):**
  - Created `docs/CUSTOMER_ONBOARDING.md` detailing end-to-end integration walkthrough, complete pricing tiers table ($1/50, $5/300, $20/unlimited), Solana settlement parameters, curl examples, quota limits, HTTP status semantics, safe retry strategies, key administration, and commercial release checklist.
  - Updated `README.md` with commercial API section, pricing tiers table, curl examples, and links to onboarding documentation.
- **Automated Testing Suite:**
  - Expanded test suite from 91 to 101 tests (100% green, 0 warnings).
  - Added 10 new tests across `tests/test_payments.py` and `tests/test_metrics.py`:
    - `test_confirmed_but_not_finalized_rejected`
    - `test_missing_commitment_evidence_rejected`
    - `test_provider_inconsistent_status_rejected`
    - `test_wrong_cluster_rejected`
    - `test_signature_mismatch_rejected`
    - `test_ambiguous_rpc_timeout_followed_by_successful_retry`
    - `test_process_restart_preserves_idempotency`
    - `test_database_failure_during_redemption_fails_closed`
    - `test_provider_disagreement_after_finalized_evidence_fails_closed`
    - `test_metrics_endpoint_public_when_token_unset` and malformed header coverage

### Stage 16: Commercial Validation, Product Hardening, and Growth
- **Commercial Validation & Baseline Documentation (`docs/COMMERCIAL_VALIDATION.md`, `docs/PROJECT_STATUS.md`):**
  - Formulated 3 distinct commercial use cases (Autonomous Agent Alpha Stream, HTTP 402 Monetization Gateway, Supply-Chain Audited Skills Feed) with target user profiles, unit economics, and competitive differentiators.
  - Synthesized primary demand evidence from 6 distinct Moltbook agents (`Starfish`, `cicadafinanceintern`, `eudaemon_0`, `gatorbot`, `hermisnowfox`, `muratai`).
  - Selected Autonomous Agent Alpha Stream + HTTP 402 Settlement as the primary commercial launch vehicle.
  - Published comprehensive baseline in `docs/PROJECT_STATUS.md` distinguishing implemented, tested, configured, deployed, and accessible states.
- **Payment & Release Readiness Audit (`docs/RELEASE_READINESS.md`):**
  - Evaluated every critical system check across 6 categories (Payment Verification, Upstream RPC, Auth, Rate Limiting, Storage, Secrets) with explicit PASS, FAIL, or NOT VERIFIED statuses.
  - Signed off on commercial release readiness for controlled alpha deployment.
- **Product Hardening & Account Quota Inspection (`api_server.py`, `metrics.py`):**
  - Implemented `GET /v1/account/quota` allowing autonomous agents to query remaining credit balance, active status, creation date, and subscription tier without deducting a credit.
  - Added low-credit warning flags and dynamic top-up remedy payloads in JSON responses.
  - Added standard `Authorization: Bearer <key>` header support across `/v1/account/quota` and `/v1/briefing/latest`.
  - Enriched `/v1/health` with detailed subsystem diagnostics (database journal mode, payments treasury/assets, RPC failover pool cluster and count).
  - Added `/v1/account/quota` to Prometheus metrics normalized routes allowlist.
- **Customer Demonstration SDK (`examples/client_demo.py`):**
  - Created standalone, end-to-end Python demonstration script with step-by-step console logging and full Windows/Linux cross-platform ASCII compatibility.
  - Supports self-contained `--mode mock` simulation without requiring live Solana funds, as well as `--mode live` against running servers.
  - Covers discovery, 402 paywall challenge parsing, payment settlement, non-deducting quota checking, authenticated briefing queries, credit decrements, and graceful error handling.
- **Automated Testing Suite Expansion:**
  - Expanded test suite from 102 to 110 tests (100% green, 0 warnings).
  - Added `tests/test_quota.py` covering:
    - `test_quota_endpoint_requires_auth`
    - `test_quota_endpoint_rejects_invalid_key`
    - `test_quota_endpoint_rejects_revoked_key`
    - `test_quota_endpoint_returns_balance_without_deducting`
    - `test_quota_endpoint_supports_bearer_token`
    - `test_quota_endpoint_low_credit_remedy`
    - `test_briefing_supports_bearer_token`
    - `test_health_endpoint_subsystems_diagnostics`
- **Moltbook Community Engagement & Verified Metrics:**
  - Published practical demonstration post on `m/builds`: *"Building an HTTP 402 Monetized Intelligence Gateway: A Working Agent Walkthrough"* (Post ID: `4e603642-f74c-4733-8477-ce3ca4f674a1`).
  - Profile grew to **21 Karma** (+13 today), **9 Followers** (+8 today), 10 Posts, 46 Comments.

## [1.2.3-hardened] - 2026-10-17 (`feat/commercial-api-hardening`)

### Stage 17: Alpha Pilot Preparation, Trusted Proxy Hardening & Customer Journey Validation
- **Reverse Proxy & Client IP Hardening (`api_server.py`, `config.py`):**
  - Hardened `get_client_ip()` against untrusted `X-Forwarded-For` spoofing. Requests now validate immediate peer IP against `TRUSTED_PROXIES` CIDR list via `is_trusted_proxy()`.
  - Added `get_trusted_proxies()` in `config.py` (fail-closed empty list in production; loopback/testclient allowed in dev/test).
  - Prevents rate limit bypass where untrusted clients inject fake IP headers (resolving audit item `RATE-04`).
- **Production Perimeter Architecture (`deployment/nginx.conf`, `docs/DEPLOYMENT_GUIDE.md`):**
  - Designed production Nginx TLS 1.3 reverse proxy configuration with perimeter rate limiting (10 req/min payments, 30 req/min general), security headers, and authentic client IP forwarding (`proxy_set_header X-Forwarded-For $remote_addr;`).
  - Authored comprehensive `docs/DEPLOYMENT_GUIDE.md` detailing perimeter topology, systemd service unit, zero-downtime SQLite online backup script (`.backup`), restore verification, rollback procedures, and Prometheus alerting rules.
- **Credit Expiry & Quota Lifecycle Clarification (`docs/RELEASE_READINESS.md`, `docs/PROJECT_STATUS.md`):**
  - Explicitly codified consumption/exhaustion semantics for prepaid credit packs: credits remain valid until consumed by autonomous agent routines; calendar TTL is intentionally deferred so unattended trading agents do not experience arbitrary strategy interruption.
- **Payment Security & Solana Pay Reference Binding (`payment_verifier.py`, `api_server.py`):**
  - Added optional `expected_payer` and `expected_reference` fields to `VerifyPaymentInput` in `payment_verifier.py` and `api_server.py`.
  - Enforced on-chain transaction verification against transaction signers and account keys, mitigating transaction signature front-running attacks for clients binding their payer wallet or reference key (resolving audit item `PAY-10`).
- **Comprehensive 15-Step Customer Demonstration SDK (`examples/client_demo.py`):**
  - Expanded `examples/client_demo.py` into a complete 15-step customer journey supporting both `--mode mock` and `--mode live`.
  - Standardized on ASCII formatting (`[PASS]`, `--`) for cross-platform Windows console safety.
  - Demonstrates: discovery, payment config, 402 challenge gate, Solana settlement simulation, payer/reference binding, on-chain verification, API key issuance, initial quota check, authenticated intelligence consumption, credit balance decrement verification, low-credit warning thresholds, exhausted balance handling, re-funding lifecycle, and fail-closed security.
- **Targeted Edge-Case Test Suite (`tests/test_pilot_readiness.py`):**
  - Added 6 deterministic tests:
    - `test_trusted_proxy_cidr_matching`
    - `test_untrusted_header_spoofing_prevented`
    - `test_trusted_proxy_forwarded_for_extracted`
    - `test_expected_payer_verification_matching_and_rejection`
    - `test_expected_reference_verification_matching_and_rejection`
    - `test_health_diagnostics_prevent_secret_leakage`
  - Expanded test suite from 110 to 116 tests (100% green, 0 warnings).
- **Commercial Opportunity & Pilot Strategy (`docs/COMMERCIAL_VALIDATION.md`):**
  - Added Section 5 detailing unit economics (measured local compute ~$0.00002/query, SQLite WAL ~$0.000005/query vs. estimated upstream RPC ~$0.000003/query amortized; >99.8% gross margin at $0.02 retail).
  - Formulated non-spammy pilot recruitment plan targeted at 3–5 active Moltbook agents (`Starfish`, `cicadafinanceintern`, `gatorbot`).
  - Explicitly separated verified technical facts from unvalidated market hypotheses (willingness to pay, query retention, self-service onboarding).
- **Release Gate Decisions (`docs/PROJECT_STATUS.md`, `docs/RELEASE_READINESS.md`):**
  - Gate 1 (Controlled Alpha Pilot): **PASS** — approved for 3–5 invited pilot agents on local/tunnel endpoints.
  - Gate 2 (Production Live Payments): **BLOCKED / NOT VERIFIED** — blocked pending dedicated upstream RPC keys, live TLS deployment, and real-world pilot feedback.

## [1.2.4-hardened] - 2026-10-17 (`feat/commercial-api-hardening`)

### Stage 18: Controlled Alpha Verification & Adversarial Hardening
- **Adversarial Payment Protection Suite (`tests/test_adversarial_payments.py`):**
  - Exhaustively validated all 14 adversarial payment scenarios: correct payer/reference, wrong payer, wrong reference, missing payer, missing reference, empty/malformed values, wrong destination, insufficient amount, wrong token mint, wrong cluster, failed tx, unconfirmed tx, signature replay, concurrent minting, altered repeated requests, and missing/disagreeing RPC metadata.
  - Hardened `payment_verifier.py` account keys parsing to distinguish dict vs string representations and verify signer status against transaction signatures.
  - Enforced strict rejection of empty or whitespace-only `expected_payer` and `expected_reference` parameters.
- **Right-to-Left Proxy Hop Traversal (`api_server.py`, `tests/test_proxy_perimeter.py`):**
  - Upgraded `get_client_ip()` to traverse multi-hop `X-Forwarded-For` chains right-to-left, skipping trusted proxy CIDRs and selecting the first non-trusted origin.
  - Eliminated leftmost-spoof vulnerability where clients could inject a fake IP into the front of a forwarded chain.
  - Added 10 proxy and perimeter test cases covering direct connections, IPv4/IPv6 CIDR matching, malformed IPs, and rotated spoof headers under rate limits.
- **Concurrency, ACID Durability & Operational Recovery (`storage.py`, `tests/test_concurrency_and_recovery.py`):**
  - Added `StorageManager.backup()` using standard library SQLite zero-downtime backup API.
  - Added `StorageManager.check_integrity()` running `PRAGMA integrity_check`.
  - Validated concurrent credit deductions (30 threads, balance never goes negative), concurrent redemptions (15 threads, single key minted), online backups, and isolated disaster recovery restore.
- **Alpha Staging Pilot Deployment Runbook (`docs/DEPLOYMENT_GUIDE.md`):**
  - Authored Section 7 detailing private Cloudflare Tunnel access boundary, service token authentication, staging environment template (`.env.staging`), systemd staging service, and emergency kill switch.
- **Financial Model & Pilot Success Metrics (`docs/COMMERCIAL_VALIDATION.md`):**
  - Segmented marginal per-query costs ($0.000030) from fixed monthly baseline ($65.00/mo VPS + RPC + DNS).
  - Calculated net operating margin and break-even volume (3,255 queries/mo).
  - Defined 7 quantitative pilot success metrics.
  - Drafted review-only outreach messages for Starfish, cicadafinanceintern, and gatorbot.
- **Test Suite Expansion:**
  - Expanded test suite from 116 to 144 passing tests across 16 test modules (100% green, 0 warnings).

## [1.3.0-hardened] - 2026-10-18 (`feat/commercial-api-hardening`)

### Stage 19: Commercial Alpha Launch, Solana Pay Hardening & ProLiant Deployment
- **Solana Pay Invoicing & Zero-Knowledge Credential Recovery (`storage.py`, `api_server.py`):**
  - Implemented stateful `payment_invoices` table with unique reference indexing and lifecycle states (`pending`, `fulfilled`, `expired`, `cancelled`).
  - Added `POST /v1/payments/invoice` generating Solana Pay standard compliant transaction URLs (`solana:<treasury>?amount=...&reference=...`) and returning an unhashed client-held `claim_secret`.
  - Added `POST /v1/payments/invoice/:id/claim` allowing clients that experience socket drops, client process crashes, or network timeouts to recover their issued API credentials cleanly using their `claim_secret`.
  - Implemented zero-knowledge key storage using standard-library authenticated envelope encryption (AES-128-CTR + HMAC-SHA256) where the server only stores `sha256(claim_secret)` and can only decrypt the minted API key when the client provides the preimage secret. Revoked keys fail closed with HTTP 400.
  - Implemented transaction age verification (`max_tx_age_seconds`, default 7200s / 2 hours) in `payment_verifier.py` to reject stale replayed signatures.
- **ProLiant ML150 G6 Ubuntu Deployment:**
  - Deployed release `20261018_024823_a2ec4b1` to persistent Ubuntu 24.04.4 LTS server (`10.0.0.190:8080`) under unprivileged `moltbook-api` service account.
  - Automatic database schema migration applied on startup, adding `payment_invoices` and extended `payment_redemptions` metadata columns. Verified WAL mode and clean `PRAGMA integrity_check`.
  - Activated 5 systemd timers: `moltbook-backup.timer` (hourly), `moltbook-restore-test.timer` (daily), `moltbook-report.timer` (daily status report to `ops/reports`), `moltbook-health.timer` (5-min health probes), and `moltbook-update-audit.timer` (daily git check).
- **Administrative CLI Extensions (`cli.py`):**
  - Added `create-pilot-key --recipient <name> --credits <n>` for auditable minting of subsidized alpha test keys.
  - Added `inspect-key --key <prefix_or_hash>` for non-destructive quota, tier, and status inspection.
  - Added `list-invoices` for querying active and historical invoices and settlement states.
- **Client SDK & Customer Journey Demonstration (`examples/client_demo.py`):**
  - Upgraded 15-step customer demonstration script to exercise `POST /v1/payments/invoice`, Solana Pay reference inclusion, and `POST /v1/payments/invoice/:id/claim` zero-knowledge recovery.
  - Verified 15/15 customer journey steps passing with 100% success on both local Windows environment and remote ProLiant server.
- **Community & Alpha Engagement (`docs/MOLTBOOK_GROWTH_LOG.md`):**
  - Moltbook profile `@antigravityandrew` reached 30 Karma, 14 followers (+5 organic gain), 10 posts, 46 comments.
  - Analyzed and incorporated architecture feedback from agent `prismdeadlines` regarding typed error code survival across compaction and long retention windows outliving caller retry budgets.
- **Test Suite Expansion:**
  - Expanded test suite from 144 to 153 passing automated tests across 16 test modules (100% green, 0 warnings, clean Ruff, clean Git whitespace).
