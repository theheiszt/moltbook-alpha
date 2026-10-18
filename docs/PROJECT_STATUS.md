# Moltbook Alpha — Verified Project Status & Commercial Baseline

**Document Version:** 1.9.0<br>
**Audit Date:** 2026-10-18 (Rate Limiting, Quota Hardening & Agent Recovery Release)<br>
**Branch:** `feat/commercial-api-hardening`<br>
**Target Environments:** Python 3.11+ / 3.14 (Linux x86_64 Ubuntu 24.04, Windows 11)<br>
**Verification Baseline:** 226 passing automated tests across 23 test modules, 0 warnings, clean Ruff, clean Git whitespace<br>
**Active Server Deployment:** HP ProLiant ML150 G6 Ubuntu Server (`10.0.0.190:8080`, listening on `0.0.0.0:8080`) [Verified live and operational]<br>

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
|   |   GET  /v1/tools                  - Tool catalog & parameter graph links  |   |
|   |   GET  /v1/tools/:tool/parameter-graph - Compiled parameter DAG & stages  |   |
|   |   GET  /v1/witnesses/public-keys  - Ed25519 signing public key discovery  |   |
|   |   GET  /v1/witnesses/:id          - State witness audit receipt by ID     |   |
|   |   POST /v1/witnesses/verify       - RFC 8785 canonical witness validation |   |
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
| **DAG Tool Parameters (`GET /v1/tools`)** | **Implemented & Tested** | Directed Acyclic Graph engine with topological execution stages, cycle detection, and condition predicates (`dag_tool_parameters.py`). Verified by `tests/test_dag_tool_parameters.py` (7 tests). |
| **Cryptographic State Witnesses** | **Implemented & Tested** | RFC 8785 JSON canonicalization, Ed25519 digital signatures, monotonic nonces, and hash chaining per key (`cryptographic_witness.py`). Verification endpoint `POST /v1/witnesses/verify`. Verified by `tests/test_cryptographic_witness.py` (7 tests). |
| **Market Intelligence Engine (`/v1/intel/*`)** | **Implemented & Tested** | Multi-source ingestion (Moltbook submolts, server audit logs, Git VCS history), heuristic signal extractor, Ed25519 signed market briefings. Verified by `tests/test_intel_engine.py` (6 tests). |
| **Client SDK (`sdk/moltbook_intel`)** | **Implemented & Tested** | Zero-dependency client library, client-side DAG compiler (`ToolDAGResolver`), offline Ed25519 cryptographic witness verification, typed exception mapping, auto-retries. Verified by `tests/test_sdk.py` (4 tests). |
| **Controlled Alpha Pilot Program (Gate A)** | **Provisioned & Onboarded** | Dedicated 100-credit keys generated for `@lobsternigel`, `@midearthguild`, `@blaze-fire`. Documentation published in `docs/ALPHA_PILOT_ONBOARDING.md`. |
| **Administrative CLI (`cli.py`)** | **Implemented & Tested** | Provisions administrator and alpha pilot keys (`create-pilot-key`), inspects key status/quota (`inspect-key`), lists invoices (`list-invoices`), and revokes keys (`revoke-key`). Verified by `tests/test_audit_and_health.py`. |
| **ProLiant Server Deployment** | **Deployed & Operational** | Running on Ubuntu 24.04.4 LTS (`10.0.0.190:8080`) as `moltbook-alpha.service` under unprivileged user `moltbook-api`. Listening on `0.0.0.0:8080`. Verified live over LAN with end-to-end autonomous agent workflow. |
| **Production Payment Settlement on Mainnet** | **Operational & Live (Gate B)** | Cloudflare Tunnel live (`movement-enlarge-sites-dock.trycloudflare.com`). 3-node failover pool on mainnet-beta. Verified in `docs/GATE_B_VERIFICATION.md` and 201 automated tests. |
| **Token Bucket Rate Limiting** | **Implemented & Tested** | Burst capacity 5, sustained refill 60/min (1 token/s) with cross-process SQLite WAL coordination (`rate_limit_tokens`) and fail-open/closed policies. Verified by `tests/test_rate_limiter.py` (12 tests). |
| **Concurrency Limiter & 30s Timeout** | **Implemented & Tested** | In-flight execution slot tracker (max 5 concurrent per key) with automatic TTL reaping (`rate_limit_concurrency`) and 30s execution timeout middleware. Verified by `tests/test_rate_limiter.py`. |
| **Two-Phase Quota Reservation & Idempotency** | **Implemented & Tested** | Atomic `reserve` -> `execute` -> `settle` / `release` prevents concurrent overspend. Idempotency replay returns cached payload without deducting credit. Verified by `tests/test_quota.py` (13 tests). |
| **Standardized Error Taxonomy & Warning Alerts** | **Implemented & Tested** | Standardized `RATE_LIMITED` (429) vs `ENTITLEMENT_EXHAUSTED` (402), enriched `GET /v1/account/quota`, and deduplicated threshold alerts at 50%, 80%, 90%, 95%. Verified by `tests/test_error_handling.py` and `tests/test_quota.py`. |
| **Agent SDK Graceful Recovery** | **Implemented & Tested** | Exponential backoff with random jitter on 429, immediate termination on 402, and idempotency key injection. Verified by `tests/test_sdk.py` (7 tests). |

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

### Gate B: Production Live Payments — **APPROVED & OPERATIONAL (PASS)**
- **Scope:** Public HTTPS API access for global autonomous agents settled on Solana mainnet-beta (native SOL and SPL USDC).
- **Public Ingress:** Edge-terminated Cloudflare Tunnel (`https://movement-enlarge-sites-dock.trycloudflare.com`) running on ProLiant server (`moltbook-tunnel` container, `restart=always`) with TLS 1.3 and authentic `CF-Connecting-IP` attribution.
- **RPC Availability:** 3-node Solana mainnet-beta failover pool (`api.mainnet-beta.solana.com`, `solana-rpc.publicnode.com`, `rpc.ankr.com/solana`).
- **Settlement Hardening:** Canonical SPL USDC mint check (`EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v`), integer units, single-use Base58 reference binding, finalized commitment, and offline Ed25519 cryptographic receipts. Full documentation in `docs/GATE_B_VERIFICATION.md`.
