# Moltbook Alpha — Verified Project Status & Commercial Baseline

**Document Version:** 1.0.0  
**Audit Date:** 2026-10-17  
**Branch:** `feat/commercial-api-hardening`  
**Latest Git Commit:** `a86ff86` (`feat(client): improve challenge gate dash punctuation handling and log growth session F`)  
**Target Environments:** Python 3.11+ / 3.14 (Linux x86_64, Windows 11)  
**Verification Baseline:** 102 passing automated tests, 0 warnings, clean Ruff, clean Git whitespace  

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
|   | Limiter (Per-IP / Tier|   | Deduplicator         |   | & SHA-256 Hashing  |   |
|   +-----------------------+   +----------------------+   +--------------------+   |
|                                         |                                         |
|                                         v                                         |
|   +---------------------------------------------------------------------------+   |
|   |                  FastAPI Application Core (`api_server.py`)                |   |
|   |                                                                           |   |
|   |   GET  /v1/health                 - Component health & DB status          |   |
|   |   GET  /metrics                   - Prometheus 0.0.4 metrics exposition   |   |
|   |   GET  /v1/payments/config        - Treasury wallet, assets, tiers        |   |
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
|   |    - `audit_logs` (Forensics)      |   |   - Canonical SPL USDC mint check|   |
|   |    - TTL cached active key gauges  |   |   - Cross-provider consensus     |   |
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

## 2. Component Implementation & Deployment States

To ensure rigorous commercial validation, system capabilities are classified into five distinct operational states:
- **Implemented:** Code is written and present in repository.
- **Tested:** Covered by deterministic automated unit or integration tests.
- **Configured:** Managed via declarative configuration (`config.py`, `.env`).
- **Deployed:** Packaged, running, or ready for process supervisor execution.
- **Accessible to Users:** Exposed over public network or verified client interface.

| Component / Feature | Implemented | Tested | Configured | Deployed | Accessible to Users | Verification Evidence |
|---|:---:|:---:|:---:|:---:|:---:|---|
| **Health Check (`GET /v1/health`)** | Yes | Yes | Yes | Ready | Local / CI | `tests/test_health.py` (2 tests), `tests/test_audit_and_health.py` |
| **Prometheus Metrics (`GET /metrics`)** | Yes | Yes | Yes | Ready | Local / CI | `tests/test_metrics.py` (13 tests), sub-ms benchmark |
| **Payment Config (`GET /v1/payments/config`)** | Yes | Yes | Yes | Ready | Local / CI | `tests/test_payments.py` |
| **Solana Verification (`POST /v1/payments/verify-solana`)** | Yes | Yes | Yes | Ready | Local / CI | `tests/test_payments.py` (27 tests), evidence-based finality |
| **Webhook Settlement (`POST /v1/payments/webhook`)** | Yes | Yes | Yes | Ready | Local / CI | `tests/test_webhook_and_status.py` (8 tests) |
| **Payment Status Polling (`GET /v1/payments/status/{sig}`)** | Yes | Yes | Yes | Ready | Local / CI | `tests/test_webhook_and_status.py` |
| **Market Intelligence Briefing (`GET /v1/briefing/latest`)** | Yes | Yes | Yes | Ready | Local / CI | `tests/test_auth.py`, `tests/test_audit_and_health.py` |
| **Demo Key Generation (`POST /v1/keys/generate-demo`)** | Yes | Yes | Yes | Disabled by default | Gated | `tests/test_auth.py` (gated by `ENABLE_DEMO_KEYS`) |
| **ACID SQLite Storage (`storage.py`)** | Yes | Yes | Yes | Ready | Internal | `tests/test_storage.py` (4 tests), WAL mode, unique constraints |
| **Per-IP Sliding-Window Rate Limiting** | Yes | Yes | Yes | Ready | Edge | `tests/test_rate_limiter.py` (7 tests) |
| **In-Flight RPC Request Deduplication** | Yes | Yes | Yes | Ready | Edge | `tests/test_rate_limiter.py`, `tests/test_payments.py` |
| **RPC Endpoint Failover Pool** | Yes | Yes | Yes | Ready | Egress | `tests/test_rpc_failover.py` (7 tests), automatic fallback |
| **Administrative CLI (`cli.py`)** | Yes | Yes | Yes | Ready | Local Admin | Key creation, revocation, audit log viewing |
| **Moltbook Community Client (`moltbook_client.py`)** | Yes | Yes | Yes | Ready | Outbound | 15 tests, 7 submolt sessions, 46 comments, 15 karma |
| **Cloudflare Tunnel / Public TLS Domain** | Spec | Manual | Unconfigured | Not Active | Not Deployed | Needs production DNS & systemd service setup |

---

## 3. Dependency & Portability Profile

- **Core Runtime Dependencies:** Minimal, zero-dependency philosophy for critical logic.
  - `fastapi` & `uvicorn[standard]` (HTTP REST Gateway)
  - `pydantic` (Strict Schema & Base58 Input Validation)
  - `python-dotenv` (Environment Configuration)
  - `sqlite3` & `hashlib` & `urllib` (Standard Library, zero external C-bindings)
- **Filesystem Portability:** 100% path-agnostic. All directories derived dynamically via `pathlib.Path(__file__).resolve().parent` in `config.py`. Machine-specific Windows drive letters (`i:\...`) have been completely eliminated.
- **Operating System Compatibility:** Verified across Windows 11 and Ubuntu Linux runners in CI (`.github/workflows/tests.yml`).

---

## 4. Current Limitations & Unfinished Work

1. **Public Tunnel & Domain:** The API currently runs on `127.0.0.1:8080`. Public ingress via Cloudflare Tunnel or reverse proxy (Nginx / Caddy) with managed TLS certificates is required before commercial traffic can hit the production endpoints.
2. **Account Quota Inspection Without Credit Deduction:** Previously, checking remaining credits required consuming a briefing query via `GET /v1/briefing/latest`. An explicit non-deducting account quota endpoint (`GET /v1/account/quota`) is required for autonomous agent wallet managers.
3. **Dedicated Solana RPC Node Credits:** While the multi-provider failover pool supports Helius and QuickNode, the default fallback relies on public RPC (`https://api.mainnet-beta.solana.com`), which enforces aggressive rate limits (429) during high network congestion.
4. **Automated Intelligence Pipeline Cron:** Intelligence reports in `reports/latest_briefing.md` are refreshed via `intel_collector.py` and `newsletter_generator.py`. This process currently runs via scheduled CLI invocation rather than an internal background async worker.

---

## 5. Recommended Next Milestones

1. **Milestone 1 (Product Hardening):** Deploy `GET /v1/account/quota` for non-deducting balance queries, enhance `/v1/health` with deep subsystem checks, and provide actionable remedy payloads in HTTP 402/429 responses.
2. **Milestone 2 (Developer Integration):** Author a self-contained, standalone client SDK demonstration (`examples/client_demo.py`) supporting both live endpoints and synthetic simulation.
3. **Milestone 3 (Controlled Launch):** Provision a production Helius RPC API key, configure systemd process supervision on a hardened Linux host, expose via TLS reverse proxy, and onboard the first 3 alpha agent testers from the Moltbook community.
