# Moltbook Alpha — Commercial Readiness, Payment Assurance & Customer Acquisition Audit (Stage 0)

**Date:** 2026-10-27  
**Operating Mode:** Stage 0 — Audit Only (Zero Code/Infrastructure Modifications)  
**Repository:** https://github.com/theheiszt/moltbook-alpha  
**Local Branch:** `feat/machine-readable-error-contract` (Commit: `d9f4b7f`)  
**Remote Branch:** `origin/main` (Commit: `a3aad61`)  

---

## 1. Executive Summary

Moltbook Alpha possesses a technically sophisticated, production-grade quantitative engine (Solana DEX Concentrated Liquidity parsing, 50-bps orderbook imbalance modeling, flash-loan anomaly detection, multi-rail Solana/Nano settlement, Ed25519 state witnesses, and sub-100ms WebSocket streaming). The internal codebase is backed by **315 passing automated tests (100% green)**.

However, the platform currently suffers from **three critical commercial blockers (P0/P1)** that prevent it from converting prospective developers into paying customers:
1. **Public API Ingress is Dead (P0):** The public landing page (`theheiszt.github.io/moltbook-alpha`) embeds an expired Cloudflare quick tunnel (`https://movement-enlarge-sites-dock.trycloudflare.com`), causing all client quickstart cURL requests to fail immediately with DNS resolution errors.
2. **Severe Pricing Discrepancy (P0):** `README.md` and onboarding docs advertise the \$20 tier as **"Permanent Unlimited access (999,999 credits that never expire)"**, whereas the live code and policy enforce **10,000 queries valid for 30 calendar days**, creating legal and commercial dispute risks.
3. **No Free Evaluation / Sample Endpoint (P1):** Unauthenticated agents cannot inspect a real sample briefing schema without paying, creating high friction for autonomous evaluation.

---

## 2. Verified Repository & Deployment State

### 2.1 Repository Architecture & Branches
| Dimension | Verified Fact | Evidence / Command |
| :--- | :--- | :--- |
| **Local Workspace** | `I:\Scripts and Programs\moltbook-intel` | Filesystem inspection |
| **Active Local Branch** | `feat/machine-readable-error-contract` | `git branch --show-current` |
| **Active Local Commit** | `d9f4b7f` (*feat: implement Pillars 1-3...*) | `git rev-parse HEAD` |
| **Local Working Tree** | Clean (0 uncommitted changes) | `git status` |
| **Local Private Backup** | `main-private` at `d9f4b7f` | `git branch -v` |
| **Public Remote Repo** | `https://github.com/theheiszt/moltbook-alpha.git` | `git remote -v` |
| **Public Remote Branch** | `origin/main` at `a3aad61` | `git rev-parse origin/main` |
| **Public Content Isolation** | **Clean Client Portal Only** (`index.html`, `sdk/`, `sdk-ts/`, `mcp/`, `examples/`). Zero proprietary backend files on GitHub. | `git ls-tree --name-only origin/main` |

### 2.2 Live Deployment Verification
| Service Component | URL / Endpoint | Verified Status | Evidence |
| :--- | :--- | :--- | :--- |
| **Public Landing Page** | `https://theheiszt.github.io/moltbook-alpha` | **HEALTHY (HTTP 200)** | Returns 36.4 KB static HTML5 application via GitHub Pages. |
| **Public Ingress Tunnel** | `https://movement-enlarge-sites-dock.trycloudflare.com` | **FAILED (DNS Errno 11001)** | `getaddrinfo failed`. Ephemeral tunnel is dead. |
| **Host Application Node** | HP ProLiant ML150 G6 (`10.0.0.190:8080`) | **UNVERIFIED (Internal LAN)** | Host is intentionally isolated on private subnet; no public port forwarding. |

---

## 3. CI Failure Analysis

### 3.1 Inspection of Workflow Runs
- Workflow: `.github/workflows/tests.yml`
- Test Matrix: `ubuntu-latest, windows-latest` on Python `3.11, 3.12`.
- Historical Runs on GitHub: Run `39165863333` and earlier failed with `conclusion: failure` within **2 seconds** with 0 steps executed.
- **Root Cause:** GitHub Actions runner quota or spending limits disabled execution on the personal repository tier, causing jobs to fail at runner provisioning before running dependencies or pytest.
- **Local Reality:** Running `python -m pytest tests/` locally executes **all 315 tests to 100% completion in 82.45s with 0 failures**.

---

## 4. Pricing & Entitlement Discrepancy Matrix

| Tier / Feature | `README.md` & Onboarding Docs | Code & Config (`storage.py`, `config.py`) | Landing Page (`index.html`) | Canonical Policy (`CREDIT_AND_ENTITLEMENT_POLICY.md`) | Discrepancy Classification |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Micro Query** | Not mentioned | \$0.25 (15 credits, non-expiring) | Mentioned in config response | \$0.25 on Nano rail | **P1 Missing Documentation** |
| **Starter** | \$1.00 (50 queries, non-expiring) | \$1.00 (50 credits, non-expiring) | \$1.00 (50 queries) | \$1.00 (50 queries) | **Consistent** |
| **Pro** | \$5.00 (300 queries, non-expiring) | \$5.00 (300 credits, non-expiring) | \$5.00 (300 queries) | \$5.00 (300 queries) | **Consistent** |
| **Premium ($20)** | **"Unlimited queries, permanent access (999,999 credits)"** | **10,000 queries / 30 days (`validity_days: 30`)** | **"Premium \$20.00 / 30 days, 10,000 included queries"** | **10,000 queries / 30 calendar days** | **P0 Critical Legal / Commercial Conflict** |
| **Top-Up Packages** | Not in main README | 500 / 1,500 / 5,000 queries (90-day expiry) | Not in main pricing table | 90-day expiry; spendable only while account active | **P1 Transparency Gap** |

---

## 5. Payment & Security Risk Register

| Risk ID | Vulnerability / Threat Scenario | Current Defense Mechanism | Residual Risk Level | Recommendation |
| :--- | :--- | :--- | :--- | :--- |
| **SEC-01** | **Transaction Front-Running:** Attacker observes transaction on Solana RPC and submits signature before payer. | Invoices strictly bind a single-use Ed25519 `reference` key. `verify-solana` asserts reference matches invoice. | **LOW (Mitigated)** | Maintain current invariant. |
| **SEC-02** | **Signature Replay:** Attacker resubmits verified transaction signature to double-mint credits. | SQLite WAL `payment_redemptions` table enforces `UNIQUE(tx_signature)`. Repeated submissions return existing record without minting credits. | **NONE (Mitigated)** | Covered by 19 adversarial unit tests. |
| **SEC-03** | **Underpayment / Overpayment:** Honest buyer sends incorrect SOL lamports due to slippage or wrong tier. | Stored in `unmatched_payments` table under `HELD` status. `SolanaRefundDispatcher` enables automated refunds minus network fees. | **LOW (Mitigated)** | Expose customer self-service refund claim. |
| **SEC-04** | **Integer Overflow on Nano Rail:** Raw Nano units ($10^{30}$) exceed SQLite 64-bit signed integer limit. | Stored in `amount_raw_text TEXT` column alongside capped integer representation. | **NONE (Mitigated)** | Fully tested in `test_multi_rail_payments.py`. |
| **SEC-05** | **Lost Response / Network Drop:** Buyer pays and key is minted, but network drops before response returns. | Buyer recovers key out-of-band using `claim_secret` via `POST /v1/payments/invoice/:id/claim`. | **NONE (Mitigated)** | Tested in `test_adversarial_payments.py`. |
| **SEC-06** | **Development Webhook Secret in Production:** Attacker forges webhooks using default secret. | When `APP_ENV=production`, server refuses to start if `WEBHOOK_SECRET` is unset or default. | **LOW (Mitigated)** | Verify host `.env` configuration. |

---

## 6. Developer Onboarding & Marketing Review

### 6.1 Positioning Statement
- **Current Headline:** *"Intelligence your AI agents can actually use."*
- **Supporting Message:** A developer API for structured, timestamped intelligence and DEX microstructure from Solana and the Moltbook ecosystem.
- **Assessment:** Clean and credible. Avoids hype or unsubstantiated trading performance guarantees.

### 6.2 Customer Onboarding Friction Points
1. **Broken Quickstart:** Developers running the landing page cURL command get a connection error due to the dead quick tunnel.
2. **Missing Sample Endpoint:** An agent cannot inspect a real sample JSON briefing payload without initiating an on-chain transaction or having demo keys enabled.
3. **Missing Pricing Alignment:** README promises unlimited lifetime access while the API enforces 30 days.

---

## 7. Existing Analytics & Customer-Funnel Gaps

| Funnel Stage | Current Metric Capability | Visibility Gap |
| :--- | :--- | :--- |
| **1. Landing / Demo Entry** | GitHub Pages web traffic (aggregate views only) | No tracking of developer tool/SDK downloads or quickstart views. |
| **2. Sample Briefing Request** | None (endpoint does not exist) | Cannot measure how many agents evaluate data before buying. |
| **3. First Invoice Created** | Tracked in SQLite `payment_invoices` table | Aggregate count only; no source or referral attribution. |
| **4. Payment Verified** | Tracked in SQLite `payment_redemptions` | Tracked, but lacks customer cohort analysis. |
| **5. Key Delivered / First Query** | Tracked in `credit_ledger_events` and audit log | Latency between payment and first query is not measured. |
| **6. 7-Day Active Retention** | Available via manual SQL query on `audit_events` | No automated weekly retention metric report. |
| **7. Repeat Purchase** | Visible via SQL join on `key_hash` in `payment_redemptions` | No automated metric pipeline. |

---

## 8. Prioritized Remediation Plan

### **Priority 0 (P0) — Immediate Blockers (Must fix before outreach)**
1. **P0.1: Establish Persistent Ingress Tunnel:** Configure a stable, named Cloudflare Tunnel (`cloudflared`) or reverse proxy with a fixed domain, replacing the dead `trycloudflare.com` URL.
2. **P0.2: Reconcile \$20 Pricing Documentation:** Update `README.md` and `docs/CUSTOMER_ONBOARDING.md` to state **"Premium: \$20.00 / 10,000 queries (30 calendar days)"**, aligning with code, configuration, landing page, and legal policy.

### **Priority 1 (P1) — Commercial Readiness Blockers**
3. **P1.1: Free Evaluation Endpoint (`GET /v1/intel/sample`):** Add an unmetered, static, source-linked sample briefing endpoint so agents can validate schema parsing with zero payment friction.
4. **P1.2: Update Public Portal Examples:** Update `index.html` and `examples/` to use the verified persistent gateway URL.
5. **P1.3: Repair GitHub Actions CI:** Configure workflow to run on push to public repo without failing on runner provisioning.

### **Priority 2 (P2) — Developer Onboarding & Conversion Enhancements**
6. **P2.1: Instrument Privacy-Conscious Funnel Metrics:** Add an aggregate `funnel_metrics` tracking table in `storage.py` (logging non-sensitive event counters: demo_view, invoice_created, payment_verified, first_query, repeat_7d).
7. **P2.2: Launch 30-Day Customer Acquisition Outreach:** Contact 30 qualified AI-agent builders on Moltbook, Farcaster, and GitHub with personalized invitations to evaluate the live sample.

### **Priority 3 (P3) — Future Optimizations**
8. **P3.1: Self-Service Customer Refund Portal:** Web UI component for claiming unmatched payments.
9. **P3.2: Automated Weekly Funnel Digest:** Scheduled task generating weekly conversion summaries.

---

## 9. Evidence and Confidence for Each Finding

| Finding | Evidence File / Command | Confidence Level |
| :--- | :--- | :--- |
| Dead public ingress tunnel | `urllib.request` to `trycloudflare.com` -> `[Errno 11001]` | **100% (Confirmed)** |
| Landing page HTTP 200 | `urllib.request` to `theheiszt.github.io/moltbook-alpha` -> 200 OK | **100% (Confirmed)** |
| 30-day Premium in code | `storage.py:1157` (`now + timedelta(days=30)`), `credits=10000` | **100% (Confirmed)** |
| "Unlimited" claim in docs | `README.md:44`, `CUSTOMER_ONBOARDING.md:40` | **100% (Confirmed)** |
| 315 tests passing locally | `python -m pytest tests/` -> 315 passed in 82.45s | **100% (Confirmed)** |
| Zero backend code on GitHub | `git ls-tree --name-only origin/main` -> 8 client files only | **100% (Confirmed)** |

---

## 10. Explicit Decisions Required from User

Before proceeding to **Stage 1 (Pricing Reconciliation)** or **Stage 6 (Implementation)**, please approve or clarify:

1. **Pricing Decision:** Confirm that the \$20 tier is officially **"Premium: \$20.00 / 10,000 queries per 30 days"**, authorizing us to remove all legacy references to "Unlimited / Permanent access" across all documentation.
2. **Public Gateway Domain / Ingress:** Do you have a custom domain for the API gateway (e.g., `api.moltbook.xyz`), or should we configure a persistent named Cloudflare Tunnel (`cloudflared`) on the HP ProLiant host?
3. **Approval to Proceed:** Do you approve proceeding to **Stage 1 (Pricing & Entitlement Reconciliation)** and **Stage 2 (Payment Assurance)** based on this remediation plan?
