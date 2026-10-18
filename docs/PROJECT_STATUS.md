# Moltbook Alpha — Verified Project Status & Commercial Baseline

**Document Version:** 1.5.0<br>
**Audit Date:** 2026-10-18 (Agent-Native Error Taxonomy & Reliability Initiative)<br>
**Branch:** `feat/commercial-api-hardening`<br>
**Target Environments:** Python 3.11+ / 3.14 (Linux x86_64 Ubuntu 24.04, Windows 11)<br>
**Verification Baseline:** 177 passing automated tests across 18 test modules, 0 warnings, clean Ruff, clean Git whitespace<br>
**Active Server Deployment:** HP ProLiant ML150 G6 Ubuntu Server (`10.0.0.190:8080`, commit `b8a7623`) [Untouched during this mission; pending deployment approval]<br>

---

## 1. System Overview & Core Architecture

Moltbook Alpha is a commercial market intelligence and quant API engineered for autonomous trading agents, decentralized finance protocols, and autonomous agent developers. The service ingests real-time ecosystem intelligence from Moltbook agent submolts, synthesizes market briefings and trading alpha, and monetizes query access via an HTTP 402 paywall settled on Solana mainnet (native SOL and SPL USDC).

```
                      +---------------------------------------+
                      |       Autonomous Client / Agent       |
                      +---------------------------------------+
                                          |
                      1. HTTP 402 Challenge or Direct Query
                                          v
+-----------------------------------------------------------------------------------+
|                        Moltbook Alpha Hardened Perimeter                          |
|                                                                                   |
|   +-----------------------+   +----------------------+   +--------------------+   |
|   | Sliding-Window Rate   |   | In-Flight Payment    |   | Constant-Time Auth |   |
|   | Limiter & Proxy Guard |   | Deduplicator         |   | & SHA-256 Hashing  |   |
|   +-----------------------+   +----------------------+   +--------------------+   |
|                                         |                                         |
|                                         v                                         |
|   +---------------------------------------------------------------------------+   |
|   |                  FastAPI Application Core (`api_server.py`)                |   |
|   |                                                                           |   |
|   |   GET  /v1/health                 - Subsystem diagnostics & DB status     |   |
|   |   GET  /metrics                   - Prometheus 0.0.4 metrics exposition   |   |
|   |   GET  /v1/errors                 - Machine-readable error code registry  |   |
|   |   GET  /v1/errors/:code           - Error code specification & retry rules|   |
|   |   GET  /v1/account/quota          - Non-deducting credit & tier inspection|   |
|   |   GET  /v1/payments/config        - Treasury wallet, assets, tiers        |   |
|   |   POST /v1/payments/invoice       - Solana Pay invoice creation & secret  |   |
|   |   POST /v1/payments/invoice/:id/claim - Zero-knowledge key recovery       |   |
|   |   POST /v1/payments/verify-solana - Server-authoritative settlement       |   |
|   |   POST /v1/payments/webhook       - Push-based webhook confirmation       |   |
|   |   GET  /v1/payments/status/:sig   - Public redemption status check        |   |
|   |   GET  /v1/briefing/latest        - Paid market intelligence briefing     |   |
|   |   POST /v1/keys/generate-demo     - Gated demo token issuance             |   |
|   +---------------------------------------------------------------------------+   |
|                     |                                     |                       |
|                     v                                     v                       |
|   +------------------------------------+   +----------------------------------+   |
|   |    Transactional SQLite (WAL)      |   |   Solana Payment Verifier        |   |
|   |    `storage.py` (ACID)             |   |   `payment_verifier.py`          |   |
|   |    - `api_keys` (SHA-256 hashed)   |   |   - Multi-provider failover pool |   |
|   |    - `payment_redemptions` (Unique)|   |   - Evidence-based finality      |   |
|   |    - `payment_invoices` (Stateful) |   |   - Canonical SPL USDC mint check|   |
|   |    - `audit_logs` (Forensics)      |   |   - Expected payer/reference auth|   |
|   |    - Encrypted key envelope (ZK)   |   |   - Max transaction age check    |   |
|   +------------------------------------+   +----------------------------------+   |
|                                                               |                   |
+---------------------------------------------------------------|-------------------+
                                                                |
                                              2. JSON-RPC (Commitment: Finalized)
                                                                v
                                             +-------------------------------------+
                                             |       Solana Mainnet-Beta RPC       |
                                             |  (Helius / QuickNode / Public Node) |
                                             +-------------------------------------+
```

---

## 2. Component Implementation & Readiness Classification

System capabilities are classified across the Stage 19 operational dimensions:

| Component / Subsystem | Status Classification | Verified Evidence / Operational Notes |
|---|:---:|---|
| **Health Diagnostics (`GET /v1/health`)** | **Implemented & Tested** | Returns subsystem health (DB engine/WAL, payments assets, RPC pool). Zero secrets exposed. Verified by `tests/test_health.py` and `tests/test_pilot_readiness.py`. |
| **Account Quota (`GET /v1/account/quota`)** | **Implemented & Tested** | Non-deducting balance & tier query. Supports Bearer and X-API-KEY. Verified by `tests/test_quota.py` (8 tests). |
| **Prometheus Telemetry (`GET /metrics`)** | **Implemented & Tested** | Prometheus 0.0.4 text format with bounded cardinality and Bearer auth option. Sub-millisecond benchmarks. Verified by `tests/test_metrics.py`. |
| **Solana Pay Invoicing (`POST /v1/payments/invoice`)** | **Implemented & Tested** | Generates stateful invoice with single-use cryptographic Solana Pay reference and client-held `claim_secret`. Verified by `tests/test_payments.py` and `tests/test_adversarial_payments.py`. |
| **Zero-Knowledge Recovery (`POST /v1/payments/invoice/:id/claim`)** | **Implemented & Tested** | Recovers minted API key without resending payment using authenticated ciphertext envelope (AES-128-CTR + HMAC-SHA256). Verified by `tests/test_adversarial_payments.py`. |
| **Solana Settlement (`POST /v1/payments/verify-solana`)** | **Implemented & Tested** | Server-authoritative, `finalized` commitment, canonical USDC SPL mint (`EPj...`), integer arithmetic, reference binding, max transaction age enforcement. Verified across 19 adversarial scenarios in `tests/test_adversarial_payments.py`. |
| **Webhook Settlement (`POST /v1/payments/webhook`)** | **Implemented & Tested** | Push-based settlement with secret verification and idempotent replay protection. Verified by `tests/test_webhook_and_status.py` (8 tests). |
| **Payment Status Polling (`GET /v1/payments/status/{sig}`)** | **Implemented & Tested** | Read-only public transaction redemption status. Verified by `tests/test_webhook_and_status.py`. |
| **Market Intelligence (`GET /v1/briefing/latest`)** | **Implemented & Tested** | Atomic single-credit decrement. Returns HTTP 402 with actionable top-up instructions on exhaustion. Verified by `tests/test_auth.py` and `tests/test_quota.py`. |
| **Trusted Proxy IP Guard (`get_client_ip`)** | **Implemented & Tested** | Evaluates peer against `TRUSTED_PROXIES` CIDR list via right-to-left multi-hop traversal. Ignores forged `X-Forwarded-For` from untrusted clients, preventing IP rate limit bypass. Verified by `tests/test_proxy_perimeter.py` (10 tests). |
| **RPC Failover & Consensus Pool** | **Implemented & Tested** | Auto-fails over on network timeouts and HTTP 429; cross-checks secondary nodes when consensus enabled. Verified by `tests/test_rpc_failover.py` and `tests/test_concurrency_and_recovery.py`. |
| **SQLite ACID Concurrency (WAL Mode)** | **Implemented & Tested** | Single atomic update statement prevents negative balances under concurrent threads. Online zero-downtime backup verified via `PRAGMA integrity_check`. Verified by `tests/test_concurrency_and_recovery.py`. |
| **15-Step Customer Demo (`examples/client_demo.py`)** | **Independently Verified** | Automated SDK walkthrough reproducing full customer journey cleanly in mock simulation mode (`--mode mock`) and live against local ProLiant deployment. |
| **30-Day Premium Entitlements** | **Implemented & Tested** | 10,000 query allowance with strict 30-day cutoff, replacing legacy infinite models. Full backwards compatibility for `tier_unlimited`. Verified by `tests/test_entitlements_and_topups.py`. |
| **90-Day Credit Top-Ups** | **Implemented & Tested** | Discrete, auditable lots in `credit_lots` with 90-day validity surviving Premium expiration, spendable only when an active entitlement exists. Verified by `tests/test_entitlements_and_topups.py`. |
| **Earliest-Deadline-First (EDF) & Ledger Audit** | **Implemented & Tested** | Earliest-expiring credits consumed first; double-entry ledger invariant `granted + refunded - deducted - expired == remaining` enforced. Request failure refund path active. Verified by `tests/test_entitlements_and_topups.py`. |
| **Administrative CLI (`cli.py`)** | **Implemented & Tested** | Provisions administrator and alpha pilot keys (`create-pilot-key`), inspects key status/quota (`inspect-key`), lists invoices (`list-invoices`), and revokes keys (`revoke-key`). Verified by `tests/test_audit_and_health.py`. |
| **ProLiant Server Deployment** | **Deployed & Operational** | Running on Ubuntu 24.04.4 LTS (`10.0.0.190:8080`) as `moltbook-alpha.service` under unprivileged user `moltbook-api`. (Maintains commit `b8a7623`; new credit hardening remains local pending deployment approval). |
| **Production Payment Settlement on Mainnet** | **Not Verified / Blocked** | Requires public TLS deployment, production RPC API keys (Helius/QuickNode), and explicit operator authorization before accepting real customer funds. |

---

## 3. Dependency & Portability Profile

- **Runtime Dependencies:** `fastapi`, `uvicorn[standard]`, `pydantic`, `python-dotenv`, `ipaddress`, `sqlite3`, `hashlib`, `urllib` (Standard Library core). Zero third-party blockchain libraries required.
- **Filesystem Portability:** 100% path-agnostic. All paths resolve dynamically relative to `Path(__file__).resolve().parent`. Machine-specific absolute drive letters have been completely eliminated.
- **Operating System Compatibility:** Verified across Windows 11 and Ubuntu Linux runners in CI (`.github/workflows/tests.yml`). Clean ASCII console formatting in `examples/client_demo.py` eliminates Windows `cp1252` encoding errors.

---

## 4. Release Gate Decisions

### Gate A: Controlled Alpha Pilot — **APPROVED (PASS)**
- **Scope:** Invitation-only testing for 3–5 autonomous agent developers using local/mock mode or private tunneled staging.
- **Justification:** Core API deployed and operational on HP ProLiant Ubuntu server; 153 passing tests; 0 warnings; zero plaintext secret exposure; rate limiting hardened against IP spoofing via right-to-left traversal; online SQLite backups verified; 15-step customer demo succeeds 100% locally and on remote host; administrative CLI supports auditable pilot key generation (`create-pilot-key`).

### Gate B: Production Live Payments — **BLOCKED (NOT VERIFIED)**
- **Blockers:**
  1. Public TLS reverse proxy is configured (`deployment/nginx.conf`) but not deployed on a public domain.
  2. Production RPC subscription (Helius/QuickNode) with dedicated rate limits not yet provisioned.
  3. Commercial willingness-to-pay remains unvalidated with real funds.
- **Next Milestone:** Conduct invitation-only pilot with selected alpha agent builders (`Starfish`, `cicadafinanceintern`, `gatorbot`, `prismdeadlines`), gather quantitative latency and schema feedback, and measure retention.
