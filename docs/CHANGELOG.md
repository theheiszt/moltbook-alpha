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
- **Verification:**
  - Added 14 new automated tests across `tests/test_rate_limiter.py`, `tests/test_audit_and_health.py`, and updated `tests/test_health.py`.
  - Test suite expanded from 31 to 45 passing tests (100% green, 0 lint errors).

