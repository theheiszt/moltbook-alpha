# Moltbook Alpha — Phase 1 Hardening & Verification Report

**Date:** 2026-10-17  
**Branch:** `feat/commercial-api-hardening`  
**Base Commit:** `629e0c3` (origin/main)  
**Target Environments:** Windows 11 (Development) / Linux x86_64 (Production Deployment)  
**Verification Status:** **100% PASSED (31 tests green, 0 lint errors, 0 network dependency)**

---

## 1. Exact Git State & Recommended Actions

- **Current Branch:** `feat/commercial-api-hardening`
- **Base Branch:** `main` at commit `629e0c3`
- **Recommended Tag:** `v1.2.0-hardened`
- **Working Tree State:** Clean; untracked local logs, bounties, and newsletters preserved safely in `.gitignore`.

---

## 2. Summary of Audit Findings & Actions Taken

An initial security and architecture audit confirmed 10 release-blocking vulnerabilities (`docs/BASELINE_AUDIT.md`):

1. **SEC-01 (Solana Payment Bypass):** Client-supplied transactions were accepted without checking the recipient, amount, token mint, or confirmation level.
   - *Action Taken:* Implemented `SolanaPaymentVerifier` requiring `finalized` commitment, matching treasury recipient, canonical USDC mint (`EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v`), integer micro-units/lamports, and server-authoritative tier calculation.
2. **SEC-02 (Privileged Backdoor Token):** Missing key files generated `master_admin_token` (999,999 credits).
   - *Action Taken:* Removed all automatic admin token generation. Added `cli.py create-admin-key` for out-of-band provisioning.
3. **SEC-03 (Unthrottled Credit Minting):** `/v1/keys/generate-demo` allowed unauthenticated users to mint infinite credits.
   - *Action Taken:* Gated behind `ENABLE_DEMO_KEYS` (disabled by default in production, returning 403 Forbidden).
4. **SEC-04 (Non-Atomic Storage / Race Conditions):** `api_keys.json` suffered from lost updates, negative balances, and double redemptions under concurrency.
   - *Action Taken:* Migrated to SQLite with WAL mode, transactions, and unique transaction signature constraints.
5. **SEC-05 (Plaintext Secrets & Timing Vulnerabilities):** API keys stored in plaintext and checked non-atomically.
   - *Action Taken:* All API keys are now SHA-256 hashed. Keys are never stored or logged in plaintext.
6. **SEC-06 (Hardcoded Windows Paths):** `i:\Scripts and Programs\...` paths caused immediate failure on Linux.
   - *Action Taken:* Normalized all paths with `pathlib.Path(__file__).resolve().parent` and environment overrides.
7. **SEC-07 (Silent Config Fallback):** Malformed config silently fell back to placeholder wallet.
   - *Action Taken:* Implemented strict fail-closed configuration validation with `ConfigError`.
8. **SEC-08 (Network Error Disclosure):** Raw RPC network stack traces leaked in 502 responses.
   - *Action Taken:* Standardized sanitized error responses; network failures fail closed (0 credits issued).
9. **SEC-09 (Ephemeral Tunnel URLs & Claims):** Broken Cloudflare tunnel URLs in docs and UI.
   - *Action Taken:* Replaced with relative and configurable API endpoints.
10. **SEC-10 (Unvalidated Signature Format):** Allowed arbitrary length string inputs for signatures.
    - *Action Taken:* Enforced base58 regex validation (80-90 chars) in Pydantic schema.

---

## 3. Files Inventory

### Created Files
- `config.py`: Centralized cross-platform path resolution, rates, and configuration validation.
- `storage.py`: ACID transactional SQLite persistence engine, key hashing, and concurrency safety.
- `payment_verifier.py`: Server-authoritative Solana & USDC verification engine.
- `cli.py`: Administrative utility for explicit key provisioning and database inspections.
- `requirements.txt`: Clean runtime dependency manifest.
- `requirements-dev.txt`: Test and development dependencies (`pytest`, `httpx`, `ruff`).
- `.env.example`: Environment configuration template with placeholders.
- `.github/workflows/tests.yml`: Multi-OS CI pipeline testing Linux & Windows on Python 3.11 & 3.12.
- `pyproject.toml`: Pytest and Ruff configuration.
- `tests/README.md`: Test documentation.
- `tests/test_health.py`: Smoke tests for API service health.
- `tests/test_auth.py`: Authentication, rate limiting, and credit deduction tests.
- `tests/test_payments.py`: Solana & USDC payment verification unit and integration tests.
- `tests/test_storage.py`: SQLite transactions, concurrency races, and replay tests.
- `tests/test_config.py`: Configuration and cross-platform path tests.
- `docs/BASELINE_AUDIT.md`: In-depth vulnerability audit and reproduction steps.
- `docs/CHANGELOG.md`: Detailed stage-by-stage hardening changelog.
- `docs/PHASE_1_REPORT.md`: This comprehensive verification report.

### Modified Files
- `api_server.py`: Integrated `config`, `storage`, and `payment_verifier`. Hardened routes.
- `intel_collector.py`: Replaced hardcoded Windows drive path with portable `Path`.
- `bounty_hunter.py`: Replaced hardcoded Windows drive path with portable `Path`.
- `newsletter_generator.py`: Replaced hardcoded Windows drive path and tunnel URLs with portable configuration.
- `token_manager.py`: Replaced hardcoded Windows drive path with portable `Path`.
- `index.html`: Cleaned up quickstarts, removed dead tunnel URLs, updated cURL commands.
- `README.md`: Documented testing, CLI administration, and hardened architecture.
- `.gitignore`: Added local SQLite databases, caches, and runtime artifacts.

---

## 4. Verification Results

### Automated Test Suite Execution
```bash
python -m pytest -v
```
**Results:** `31 passed in 1.78s` (100% green)
- `tests/test_auth.py`: 7/7 passed
- `tests/test_config.py`: 6/6 passed
- `tests/test_health.py`: 1/1 passed
- `tests/test_payments.py`: 13/13 passed
- `tests/test_storage.py`: 4/4 passed

### Code Formatting & Linting
```bash
python -m ruff check .
```
**Results:** `All checks passed!` (0 lint errors, 0 warnings).

### Concurrency Stress Verification
- **Credit Deductions:** 25 concurrent threads competing for 5 credits resulted in exactly 5 successful deductions and 20 exhausted responses; database balance ended at exactly 0.
- **Payment Replay:** 15 concurrent threads submitting the identical transaction signature resulted in exactly 1 newly minted key and 14 idempotent replay responses; exactly 1 redemption record exists in the database.

---

## 5. Security Posture Summary

| Component | Previous Baseline | Hardened Commercial API |
|---|---|---|
| **Payment Proof** | Checked tx existence only | Recipient, canonical USDC mint, 6 decimals, integer units, and finalization strictly verified. |
| **Tier Authority** | Client chose arbitrary tier | Server calculates earned tier strictly from verified transferred amount. |
| **Replay Protection** | In-memory JSON loop | Atomic database unique constraint on `tx_signature`. Replays return idempotent record without minting. |
| **Admin Rights** | Default `master_admin_token` generated on startup | Zero automatic admin tokens. Explicit provisioning via `python cli.py create-admin-key`. |
| **Demo Keys** | Publicly unthrottled | Disabled by default in production. Returns HTTP 403 unless explicitly enabled in dev. |
| **Secret Storage** | Plaintext in `api_keys.json` | SHA-256 hashed in SQLite. Plaintext keys never stored or logged. |
| **Credit Balances** | Non-atomic JSON rewrite | Atomic SQL `UPDATE ... WHERE credits > 0`. Never drops below zero. |
| **Network Failures** | Stack traces leaked | Fail closed with sanitized HTTP 502/503. Zero credits issued on error. |

---

## 6. Cross-Platform Compatibility

- **Path Handling:** All modules utilize `pathlib.Path(__file__).resolve().parent` and support environment overrides (`MOLTBOOK_DATA_DIR`, `MOLTBOOK_REPORTS_DIR`).
- **Operating Systems Tested:**
  - Windows 11 (Development machine, Python 3.14.7)
  - Ubuntu Linux & Windows Server (Configured via GitHub Actions CI matrix in `.github/workflows/tests.yml`).
- **File System Safety:** Forward-slash/backslash normalization is transparently handled by `pathlib`.

---

## 7. Deployment Prerequisites & Environment Variables

Create `.env` based on `.env.example`:
```ini
APP_ENV=production
MOLTBOOK_DATA_DIR=/var/lib/moltbook/data
MOLTBOOK_REPORTS_DIR=/var/lib/moltbook/reports
SOLANA_RPC_URL=https://api.mainnet-beta.solana.com
SOLANA_TREASURY_WALLET=DQkseq8m92h9mQbcQjDRSESAxphpAroKjqyGeSAoKCiC
ENABLE_DEMO_KEYS=false
```

### System Services / Background Jobs
1. **API Server:** Run using systemd or supervisord:
   ```bash
   uvicorn api_server:app --host 0.0.0.0 --port 8080 --workers 4
   ```
2. **Scheduled Intelligence Collector:** Run every 25-30 minutes:
   ```bash
   python intel_collector.py
   ```

---

## 8. Residual Technical Debt & Limitations

1. **Solana RPC Rate Limiting:** The public Solana RPC (`https://api.mainnet-beta.solana.com`) enforces strict rate limits (429 Too Many Requests). In high-volume production, configure a dedicated RPC provider (e.g. Helius, QuickNode, Triton) via `SOLANA_RPC_URL`.
2. **Single-Node SQLite:** SQLite with WAL mode is rock-solid for single-server multi-worker deployments. If horizontally scaling across multiple cloud servers behind a load balancer, migrate `storage.py` to PostgreSQL.
3. **Clawnch / EVM Wallet Storage:** `token_manager.py` still loads credentials from `~/.config/moltbook/evm_wallet.json`. Phase 2 should migrate this to AWS Secrets Manager / HashiCorp Vault.

---

## 9. Operator Runbook

### Starting the Server
```bash
python api_server.py
```

### Creating an Admin Key
```bash
python cli.py create-admin-key --credits 999999
```

### Auditing Keys and Balances
```bash
python cli.py list-keys
```

### Database Backup
Back up `data/moltbook.db` safely using SQLite online backup:
```bash
sqlite3 data/moltbook.db ".backup data/moltbook_backup_$(date +%Y%m%d).db"
```

---

## 10. Recommended Next Steps for Phase 2

1. **PostgreSQL Adapter:** Implement an optional async SQLAlchemy / asyncpg storage backend for multi-host deployments.
2. **Dedicated RPC & Webhook Integration:** Integrate Helius / Shyft webhooks for push-based payment confirmations alongside polling verification.
3. **Clawnch EVM Hardening:** Add unit tests with synthetic EVM RPC fixtures for `token_manager.py` and automated Robinhood Chain launch ticket execution.
4. **[COMPLETED in v1.2.1-hardened] Rate Limiting & Audit Middleware:** Per-IP sliding-window rate limiting on `/v1/payments/verify-solana`, in-flight RPC deduplication, security audit logging, and administrative key revocation shipped and verified with 49 tests passing.

