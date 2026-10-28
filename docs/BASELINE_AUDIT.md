# Moltbook Alpha — Phase 1 Baseline Security & Architecture Audit

**Date:** 2026-10-17  
**Git Branch Baseline:** `feat/commercial-api-hardening` (branched from `main` @ `629e0c3`)  
**Target Environments:** Development (Windows 11, Python 3.14) / Production (Linux x86_64, Python 3.11+)  
**Repository:** `https://github.com/theheiszt/moltbook-alpha`

---

## 1. Executive Summary

A comprehensive architectural and security audit was performed across the Moltbook Alpha repository. The core application provides autonomous market intelligence scraped from Moltbook submolts (`trading`, `crypto`, `agentfinance`, `builds`, `infrastructure`), exposes a FastAPI intelligence briefing service with HTTP 402 paywall settlement, generates newsletters, and manages token deployment states on Robinhood Chain.

While functional as an early prototype, the application exhibits **critical vulnerabilities in payment verification, authentication, state management, and deployment portability** that prevent it from functioning as a secure commercial API.

---

## 2. Detailed Findings Matrix

| ID | Category | Severity | File Reference | Summary |
|---|---|---|---|---|
| **SEC-01** | Payment Verification | **CRITICAL** | `api_server.py:141-191` | Flawed Solana payment verification; no recipient, amount, token mint, or confirmation check. |
| **SEC-02** | Authentication / Backdoor | **CRITICAL** | `api_server.py:52-65` | Insecure startup bootstrap mints well-known privileged `master_admin_token` (999,999 credits). |
| **SEC-03** | Rate Limiting / Abuse | **HIGH** | `api_server.py:193-204` | Unauthenticated, unthrottled `/v1/keys/generate-demo` mints unlimited usable credits. |
| **SEC-04** | State / Concurrency | **HIGH** | `api_server.py:52-70, 71-106` | Unsafe JSON file reads/writes; race conditions lead to lost updates and double spends. |
| **SEC-05** | Cryptography / Secrets | **HIGH** | `api_keys.json`, `api_server.py:88-95` | Raw API keys stored in plaintext; comparison vulnerable to timing side channels. |
| **SEC-06** | Portability / Config | **HIGH** | Multiple files (`api_server.py:24`, etc.) | Hardcoded Windows absolute filesystem paths (`i:\...`) breaking Linux deployment. |
| **SEC-07** | Configuration / Resilience | **MEDIUM** | `api_server.py:41-50` | Silent fallback to placeholder treasury address upon configuration parsing failure. |
| **SEC-08** | Network & Information Disclosure | **MEDIUM** | `api_server.py:164-165` | Raw internal RPC network exceptions leaked directly to client in HTTP 502 responses. |
| **SEC-09** | Ephemeral URLs & UI Claims | **MEDIUM** | `index.html:79-81`, `newsletter_generator.py:55-58` | Expired/inconsistent Cloudflare tunnel URLs and unverified marketing metrics. |
| **SEC-10** | Input Validation | **LOW** | `api_server.py:119-122` | Transaction signatures accept arbitrary unvalidated string lengths and characters. |

---

## 3. In-Depth Vulnerability Analysis & Reproduction

### SEC-01: Critical Solana Payment Verification Flaws (Proof-of-Payment Bypass)
- **File:** `api_server.py:141-191`
- **Severity:** **CRITICAL**
- **Description:**
  `POST /v1/payments/verify-solana` takes a client-supplied `transaction_signature` and `target_tier`.
  The verification routine only queries `getTransaction` from Solana RPC and checks:
  ```python
  meta = tx_data.get("meta", {})
  if meta.get("err") is not None:
      raise HTTPException(status_code=400, detail="Transaction failed on-chain.")
  ```
  It **fails** to verify:
  1. **Recipient Wallet:** The transaction could be a transfer to ANY address (the attacker's own wallet, an exchange, or a third party).
  2. **Transfer Amount:** The client specifies `target_tier: "tier_unlimited"` ($20), but sends $0.000001 (or 0 lamports) and the server will grant the unlimited tier.
  3. **Asset / Token Mint:** No check whether the transfer was native SOL or SPL USDC (mint `EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v`). An attacker can send an arbitrary worthless meme token.
  4. **Confirmation Status / Commitment:** Does not enforce finalization (`finalized`), allowing transactions from reorged or unconfirmed blocks.
  5. **Decimal Conversions:** No validation of token decimals (SPL token accounts vs lamports).
- **Reproduction:**
  1. Submit any valid, successful mainnet Solana signature (e.g., from Solscan transferring 0.0001 SOL between two unrelated addresses) to `/v1/payments/verify-solana` with `target_tier="tier_unlimited"`.
  2. The endpoint successfully responds with `allocated_credits: 999999` and returns a newly minted API key with unlimited tier without receiving any funds.
- **Remediation:**
  Implement server-authoritative parsing:
  - Query RPC with `{"commitment": "finalized", "encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}`.
  - Verify `meta.err is None` and that the transaction is finalized.
  - Parse `preBalances`/`postBalances` (for native SOL) or `preTokenBalances`/`postTokenBalances` / parsed token instructions (for SPL USDC).
  - Assert the recipient address exactly equals the server-configured `solana_treasury_wallet`.
  - Validate token mint for USDC (`EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v`).
  - Calculate exact net received amount using integer arithmetic (lamports or USDC micro-units).
  - Map verified received amount to allowed pricing tiers strictly on the server side.

---

### SEC-02: Hardcoded Privileged Credential Generation on Missing File
- **File:** `api_server.py:52-65`
- **Severity:** **CRITICAL**
- **Description:**
  When `api_keys.json` is missing (such as on initial deployment or after accidental deletion), `load_valid_keys()` populates it with:
  ```python
  initial = {
      "demo_free_token": {"credits": 5, "tier": "free"},
      "master_admin_token": {"credits": 999999, "tier": "unlimited"}
  }
  ```
  This creates a universal, well-known backdoor token `master_admin_token` providing unlimited access.
- **Reproduction:**
  1. Remove or rename `api_keys.json`.
  2. Send `GET /v1/briefing/latest` with header `X-API-KEY: master_admin_token`.
  3. The request succeeds and grants unlimited access.
- **Remediation:**
  - Remove all code that generates default admin tokens.
  - Fail closed on missing credentials.
  - Require explicit command-line or administrative script provisioning for admin tokens (`python -m moltbook.cli create-admin-key`).

---

### SEC-03: Unrestricted Public Endpoint Minting Free Credits
- **File:** `api_server.py:193-204`
- **Severity:** **HIGH**
- **Description:**
  `POST /v1/keys/generate-demo` generates a new trial token with 5 credits on every invocation without IP rate limiting, authorization, captcha, or gating. An attacker can script requests to mint millions of free credits and store them indefinitely.
- **Remediation:**
  - Add configuration setting `ENABLE_DEMO_KEYS` (default `false` in production).
  - Implement IP/rate-limit controls and short expiry for demo tokens.

---

### SEC-04: Non-Atomic State Storage and Concurrency Race Conditions
- **File:** `api_server.py:52-70, 71-106, 175-184`
- **Severity:** **HIGH**
- **Description:**
  API keys, credits, and redeemed transaction signatures are stored in a single JSON file (`api_keys.json`).
  The server loads the whole dictionary into memory, modifies it, and rewrites the file:
  - If two requests hit `/v1/briefing/latest` concurrently, both read balance `N`, both decrement to `N - 1`, and both write `N - 1`. The user consumes 2 queries while only 1 credit is deducted.
  - Under concurrent payment redemption requests for the same transaction signature, both requests pass the `for k, v in keys.items()` check before either writes to disk, causing double redemption.
  - A crash during `save_keys()` truncates `api_keys.json` to 0 bytes or corrupts the JSON, triggering the SEC-02 fallback recreating `master_admin_token`.
- **Remediation:**
  Migrate key management, credit balances, and redeemed payment signatures to an ACID transactional SQLite database (`data/moltbook.db`) with unique constraints (`UNIQUE(tx_signature)`), row locking, and atomic credit decrement statements (`UPDATE keys SET credits = credits - 1 WHERE id = ? AND credits > 0`).

---

### SEC-05: Plaintext Secret Storage and Timing Vulnerability
- **File:** `api_server.py:88-95`
- **Severity:** **HIGH**
- **Description:**
  API keys are stored as plaintext dictionary keys in `api_keys.json`. If this file is leaked or read via unauthorized directory traversal, all customer and admin keys are compromised. Additionally, `if api_key not in keys:` performs standard non-constant-time string comparisons.
- **Remediation:**
  - Store keys as SHA-256 hashes (`key_hash`).
  - Compare incoming API keys using `hmac.compare_digest` on their hashed representations.
  - Return the raw API key only once upon payment verification or admin creation.

---

### SEC-06: Windows-Specific Path Hardcoding Breaking Linux Deployment
- **Files:**
  - `api_server.py:24`: `BASE_DIR = Path(r"i:\Scripts and Programs\moltbook-intel")`
  - `intel_collector.py:132`: `out_dir = Path(r"i:\Scripts and Programs\moltbook-intel\reports")`
  - `bounty_hunter.py:12`: `BOUNTY_DIR = Path(r"i:\Scripts and Programs\moltbook-intel\bounties")`
  - `newsletter_generator.py:12`: `BASE_DIR = Path(r"i:\Scripts and Programs\moltbook-intel")`
  - `token_manager.py:16`: `TOKEN_STATE_FILE = Path(r"i:\Scripts and Programs\moltbook-intel\token_state.json")`
- **Severity:** **HIGH**
- **Description:**
  Hardcoding Windows drive letters (`i:\...`) causes immediate `FileNotFoundError` or invalid path exceptions on Linux, macOS, or any Windows machine with a different directory layout.
- **Remediation:**
  Replace hardcoded paths with project-relative paths using `Path(__file__).resolve().parent` and support path overrides via the `MOLTBOOK_DATA_DIR` environment variable.

---

### SEC-07: Silent Configuration Fallback on Malformed JSON
- **File:** `api_server.py:41-50`
- **Severity:** **MEDIUM**
- **Description:**
  In `load_payment_config()`, any exception reading `payment_config.json` catches `Exception` and returns `DEFAULT_CONFIG`. `DEFAULT_CONFIG` contains a placeholder treasury wallet (`2sW9nZ1Q65qY8mD7xXvF4uL3kR9pE1wB7vC5nA2mG8hK`), diverting payment instructions away from the real treasury wallet without any warning.
- **Remediation:**
  Raise a fatal configuration error during startup if configuration files are missing, unreadable, or malformed. Never silently substitute placeholder treasury addresses.

---

### SEC-08: Network Failure Handling & Information Disclosure
- **File:** `api_server.py:164-165`
- **Severity:** **MEDIUM**
- **Description:**
  ```python
  except Exception as e:
      raise HTTPException(status_code=502, detail=f"Solana RPC error: {str(e)}")
  ```
  Leaking raw socket/HTTP connection exceptions exposes internal infrastructure details to the caller. Furthermore, timeouts are not handled with clear retry-safe semantics.
- **Remediation:**
  Catch network/RPC timeouts explicitly and return a standardized, sanitized error message (`"Payment verification service temporarily unavailable. Please retry later."`). Ensure payment status fails closed (zero credits issued).

---

### SEC-09: Stale Tunnel URLs & Unverified UI Claims
- **Files:** `index.html:79-81`, `newsletter_generator.py:55-58`
- **Severity:** **MEDIUM**
- **Description:**
  - `index.html` hardcodes `https://verification-passenger-additions-probability.trycloudflare.com`
  - `newsletter_generator.py` hardcodes `https://fair-edinburgh-starts-specialists.trycloudflare.com`
  Both tunnel URLs expire or fail, breaking public cURL commands.
  - UI claims "Status: Live & Synced (3x Daily)" and "140,000+ Autonomous Agents" without backend telemetry or verification.
- **Remediation:**
  - Update `index.html` to reference relative paths (`/v1/...`) or dynamically read the current host.
  - Document actual verified pipeline capabilities.

---

### SEC-10: Unvalidated Transaction Signature Input Format
- **File:** `api_server.py:119-122`
- **Severity:** **LOW**
- **Description:**
  `transaction_signature` in `VerifyPaymentRequest` is accepted as an arbitrary string. Solana base58 transaction signatures are exactly 87-88 characters containing base58 characters. Accepting arbitrary strings allows invalid RPC calls and potential payload injection.
- **Remediation:**
  Enforce regex validation on base58 signatures (length 80-90, valid base58 charset `[1-9A-HJ-NP-Za-km-z]`).

---

## 4. Remediation Roadmap

1. **Stage 1 — Development Infrastructure:** Merge `moltbook_alpha_phase1` scaffolding, set up `requirements.txt`, `requirements-dev.txt`, `.env.example`, GitHub CI workflow, and baseline health test.
2. **Stage 2 — Secure Payment Verification:** Re-architect `verify-solana` with server-authoritative recipient, mint, amount, decimals, and finalization validation. Fail closed on all RPC errors.
3. **Stage 3 — API Key & Credit Security:** Eliminate `master_admin_token`, gate demo keys, hash API keys, and use constant-time comparisons.
4. **Stage 4 — SQLite Transactional Storage:** Replace `api_keys.json` with SQLite schema enforcing atomic balance updates and unique transaction redemptions.
5. **Stage 5 — Cross-Platform Portability:** Eliminate Windows paths and unify environment configuration via `pathlib` and `.env`.
6. **Stage 6 — Frontend & Documentation:** Clean up `index.html` endpoints and align all documentation with real application behavior.
7. **Stage 7 — Verification & Release:** Run comprehensive automated tests (100% green without external network calls) and document in `docs/CHANGELOG.md` and `docs/PHASE_1_REPORT.md`.
