# Moltbook Alpha — Payment Settlement Hardening Plan

**Document Version:** 1.0.0  
**Date:** 2026-10-18  
**Repository:** `I:\Scripts and Programs\moltbook-intel`  
**Branch:** `feat/commercial-api-hardening`  
**Starting Commit:** `af89082`  
**Baseline Test Result:** 144 passed in 16.91s  

---

## 1. Baseline Summary & Architectural Context

Following the security audit recorded in `docs/PAYMENT_SETTLEMENT_AUDIT.md`, Moltbook Alpha’s payment verification pipeline demonstrates strong baseline properties (SQLite transactional atomicity, durable replay prevention via `PRIMARY KEY (tx_signature)`, raw integer token mathematics, and `finalized` Solana commitment enforcement).

However, four specific architectural deficiencies must be hardened:
1. **Unbound Public Payments (Front-Running Risk):** Transaction signatures without reference or invoice binding allow third parties to monitor the treasury wallet on-chain and redeem newly minted API keys before legitimate buyers.
2. **Irrecoverable Key Delivery on Network Disconnect:** Plaintext keys are returned once upon initial redemption and never stored in plaintext. A network drop during HTTP delivery leaves the customer with an unrecoverable key.
3. **Missing Transaction Age Boundary:** The API server currently initializes `SolanaPaymentVerifier` without passing `max_age_seconds`, permitting arbitrary historical transactions to be settled.
4. **Unverified RPC Network Identity:** Cluster identity relies on URL string heuristics rather than cryptographic verification of the Solana cluster genesis hash.

---

## 2. Implementation Sequence by Stage

```
+---------------------------------------------------------------------------------------------------+
| Stage 0: Baseline Verification (144 tests green) & Architecture Planning                         |
|                                     │                                                             |
| Stage 1: Invoice Lifecycle & Cryptographic Solana Pay Reference Binding                          |
|          - POST /v1/payments/invoice (generates invoice_id, reference pubkey, claim_secret)       |
|          - State transitions: pending -> paid -> fulfilled / expired                             |
|          - Mandatory reference matching in POST /v1/payments/verify-solana                       |
|                                     │                                                             |
| Stage 2: Safe Credential Recovery Mechanism                                                      |
|          - POST /v1/payments/invoice/{invoice_id}/claim with claim_secret                         |
|          - Ephemeral encrypted key envelope (AES-CTR/HMAC-SHA256 derived from claim_secret)       |
|          - Zero-knowledge storage: server cannot decrypt without client-presented secret          |
|          - Strict 15-minute recovery window; secure zeroing of recovery material                  |
|                                     │                                                             |
| Stage 3: Transaction Age & Invoice Expiry Enforcement                                            |
|          - Server-side max_age_seconds (default 1800s / 30m, matching invoice lifetime)          |
|          - Strict expiration rejection; rejection of missing/future timing metadata              |
|                                     │                                                             |
| Stage 4: Network Identity Verification via Genesis Hash                                          |
|          - Query getGenesisHash during verifier initialization                                    |
|          - Assert mainnet-beta genesis (5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d)            |
|          - Fail closed if hash mismatches or node is unreachable                                  |
|                                     │                                                             |
| Stage 5: Settlement Evidence Audit Trail in SQLite                                               |
|          - Non-destructive migration: invoice_id, payer_wallet, reference, slot, block_time       |
|          - Comprehensive audit records without persisting secrets or personal data                |
|                                     │                                                             |
| Stage 6: Concurrency & Storage Invariant Verification                                             |
|          - Atomic state transitions: invoice status, redemption status, credential minting        |
|          - Development database backup prior to migration tests                                   |
|                                     │                                                             |
| Stage 7: Comprehensive Adversarial & Regression Validation                                       |
|          - Front-running attack simulations, recovery simulations, clock skew, cluster spoofing  |
|          - Full 144+ test suite execution, Ruff linting, git diff --check                         |
|                                     │                                                             |
| Stage 8: Documentation, Migration Runbook, & Approval Package                                     |
+---------------------------------------------------------------------------------------------------+
```

---

## 3. Detailed Component Designs

### 3.1 Invoice State Machine & Solana Pay Binding (Stage 1)
- **Table:** `payment_invoices`
  - `invoice_id TEXT PRIMARY KEY`: `inv_` + 24 hex characters.
  - `reference TEXT UNIQUE NOT NULL`: 32-44 character valid base58 public key. Used as a non-signing read-only account in the Solana transfer according to the Solana Pay specification.
  - `tier TEXT NOT NULL`: Target tier (`tier_starter`, `tier_pro`, `tier_unlimited`).
  - `credits INTEGER NOT NULL`: Entitlement to grant upon settlement.
  - `asset TEXT NOT NULL`: "USDC" or "SOL".
  - `amount_raw INTEGER NOT NULL`: Exact integer base units (micro-USDC or lamports).
  - `recipient TEXT NOT NULL`: Expected treasury wallet address.
  - `cluster TEXT NOT NULL`: Expected cluster (`mainnet-beta`).
  - `status TEXT NOT NULL`: `pending` -> `fulfilled` (or `expired`, `failed`).
  - `claim_secret_hash TEXT NOT NULL`: SHA-256 hash of the recovery secret.
  - `encrypted_key_envelope TEXT`: Ephemeral encrypted API key (purged after claim window).
  - `tx_signature TEXT UNIQUE`: Settled on-chain transaction signature.
  - `created_at TEXT NOT NULL`: ISO 8601 UTC timestamp.
  - `expires_at TEXT NOT NULL`: ISO 8601 UTC timestamp (created_at + 1800s / 30 mins).
  - `fulfilled_at TEXT`: ISO 8601 UTC timestamp.

- **Binding Rule:**
  Verification requires `invoice_id`. The server retrieves the pending invoice and ensures that the on-chain transaction contains `invoice.reference` in its `accountKeys`. A third party submitting the signature without the invoice or with a different invoice is rejected immediately.

### 3.2 Safe Credential Recovery Architecture (Stage 2)
- **The Challenge:** The server must never store plaintext API keys on disk (`api_keys` stores only SHA-256 hashes). However, if an HTTP delivery fails, the client must be able to recover their key without paying twice.
- **The Solution: Zero-Knowledge Key Envelope**:
  1. During invoice generation (`POST /v1/payments/invoice`), the server generates `claim_secret = sec_ + secrets.token_hex(20)`.
  2. The server stores only `claim_secret_hash = sha256(claim_secret.encode()).hexdigest()`. The plaintext `claim_secret` is returned to the client once in the invoice creation response.
  3. When the payment is verified, the server mints `raw_token` (`molt_sol_...`).
  4. The server encrypts `raw_token` using an authenticated symmetric cipher (HMAC-SHA256 CTR stream + HMAC tag) keyed by `HKDF(claim_secret)`.
  5. The resulting ciphertext envelope is saved in `payment_invoices.encrypted_key_envelope`.
  6. If the client receives the initial response, they possess `raw_token` directly.
  7. If the client experiences a connection drop, they call `POST /v1/payments/invoice/{invoice_id}/claim` providing `claim_secret`.
  8. The server checks `sha256(claim_secret) == invoice.claim_secret_hash`, decrypts `encrypted_key_envelope`, returns `raw_token`, and securely purges `encrypted_key_envelope`.
  9. Even in a catastrophic database compromise, attackers cannot decrypt API keys because `claim_secret` exists only on the client.

### 3.3 Transaction Age & Expiration Policy (Stage 3)
- `max_age_seconds` set to 1800s (30 minutes), matching the invoice TTL.
- Enforced at both:
  1. **Solana Verifier Level:** `tx.blockTime` must be within `max_age_seconds` of current UTC server time.
  2. **Invoice Level:** `datetime.now(timezone.utc) <= invoice.expires_at`.
- Rejects missing or non-positive timestamps; rejects transactions from the future beyond acceptable clock drift (60s).

### 3.4 Cryptographic Cluster Verification (Stage 4)
- During verifier initialization or on first RPC request, executes `getGenesisHash`.
- Verifies exact match against mainnet-beta genesis hash: `5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d`.
- Fails closed if the node is unreachable or returns devnet/testnet genesis hashes.

---

## 4. Database Migration & Rollback Strategy

### 4.1 Schema Migration (Zero-Downtime, Additive Only)
The migration adds:
1. `payment_invoices` table.
2. Additional nullable columns to `payment_redemptions` (`invoice_id`, `payer_wallet`, `reference`, `slot`, `block_time`).

```sql
-- Migration 002: Invoices and Extended Settlement Evidence
CREATE TABLE IF NOT EXISTS payment_invoices (
    invoice_id TEXT PRIMARY KEY,
    reference TEXT UNIQUE NOT NULL,
    tier TEXT NOT NULL,
    credits INTEGER NOT NULL,
    asset TEXT NOT NULL,
    amount_raw INTEGER NOT NULL,
    recipient TEXT NOT NULL,
    cluster TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    claim_secret_hash TEXT NOT NULL,
    encrypted_key_envelope TEXT,
    tx_signature TEXT UNIQUE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    fulfilled_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_invoices_ref ON payment_invoices(reference);
CREATE INDEX IF NOT EXISTS idx_invoices_status ON payment_invoices(status);

ALTER TABLE payment_redemptions ADD COLUMN invoice_id TEXT;
ALTER TABLE payment_redemptions ADD COLUMN payer_wallet TEXT;
ALTER TABLE payment_redemptions ADD COLUMN reference TEXT;
ALTER TABLE payment_redemptions ADD COLUMN slot INTEGER;
ALTER TABLE payment_redemptions ADD COLUMN block_time INTEGER;
```

### 4.2 Rollback Strategy
1. The migration is purely additive: existing `api_keys` and legacy `payment_redemptions` queries continue functioning unchanged.
2. If rolled back to commit `af89082`, the older code ignores the extra table and columns.
3. Development database backup is created at `data/moltbook_pre_hardening_backup.db` prior to running migration tests.

---

## 5. Deprecation & Client Compatibility Strategy

1. **Deprecated Signature-Only Flow:**
   Calling `POST /v1/payments/verify-solana` without an `invoice_id` is deprecated and rejected with HTTP 400 Bad Request detailing that payments must be initiated via `POST /v1/payments/invoice` to prevent front-running.
2. **Existing Issued Keys:**
   All previously minted keys in `api_keys` remain 100% valid; authentication and credit deductions (`authenticate_and_deduct`) are unaffected.
3. **Previously Redeemed Signatures:**
   All historical signatures in `payment_redemptions` continue returning `"status": "already_redeemed"`.

---

## 6. Implementation Verification & Adversarial Results

### 6.1 Test Suite Metrics
- **Total Tests Collected:** 151
- **Total Tests Passed:** 151 (0 failed, 0 errors, 0 skipped)
- **Suite Execution Time:** 18.99s
- **Code Linter:** `ruff check .` -> All checks passed!
- **Whitespace / Formatting:** `git diff --check` -> Zero errors.

### 6.2 Adversarial Scenarios Validated (`tests/test_adversarial_payments.py`)
1. `test_scenario_01_correct_payer_and_correct_reference`: Exact parameter validation passes.
2. `test_scenario_02_wrong_payer_fails_closed`: Payer mismatch fails closed with VerificationError.
3. `test_scenario_03_wrong_reference_fails_closed`: Reference mismatch fails closed with VerificationError.
4. `test_scenario_04_05_missing_optional_payer_and_reference_succeeds_when_tx_valid`: Legacy verifier unit check.
5. `test_scenario_06_empty_or_malformed_values_rejected`: Rejects malformed base58 and invalid lengths.
6. `test_scenario_07_correct_signer_but_wrong_destination_or_insufficient_amount`: Rejects wrong recipient or low transfer.
7. `test_scenario_08_correct_destination_but_wrong_token_mint`: Rejects spoofed token mints (e.g. USDT).
8. `test_scenario_09_wrong_cluster_fails_closed`: Rejects mismatched cluster strings.
9. `test_scenario_10_failed_or_insufficiently_finalized`: Rejects on-chain execution error and unconfirmed blocks.
10. `test_scenario_11_13_replay_and_altered_parameters`: Replay returns existing key prefix without re-minting; parameter tampering does not escalate tier.
11. `test_scenario_12_concurrent_redemptions_guarantee_single_mint`: 10 concurrent threads guarantee exactly 1 mint and 9 safe rejections.
12. `test_scenario_14_missing_or_disagreeing_rpc_metadata`: Malformed transaction payloads fail closed.
13. `test_scenario_15_adversarial_frontrun_blocked_by_invoice_binding`: Mempool observer cannot steal API key without matching invoice reference; legitimate invoice holder receives key.
14. `test_scenario_16_zero_knowledge_credential_recovery_after_network_drop`: Decrypts and recovers identical API key using `claim_secret`; attacker with incorrect secret is rejected.
15. `test_scenario_17_expired_invoice_rejection`: Invoices past `expires_at` are rejected with HTTP 400.
16. `test_scenario_18_mismatched_asset_or_amount_against_invoice`: Mismatched asset (SOL instead of USDC) or underpaid amount rejected.
17. `test_scenario_19_future_timestamp_rejected`: Transactions with `block_time > now + 60s` rejected to defend against clock skew.
18. `test_scenario_20_cluster_genesis_hash_validation`: Verifies Solana mainnet genesis hash; devnet/testnet hashes fail closed.
19. `test_scenario_21_revoked_key_claim_blocked`: Revoked API keys cannot be recovered via claim secret.

---

## 7. Production Deployment Runbook (Ubuntu ProLiant ML150 G6)

*Note: In accordance with the non-negotiable safety rules of this mission, no remote commands or migrations have been executed on the production server. The steps below document the approved production deployment procedure for when explicit authorization is granted.*

### Step 1: Pre-Deployment Backup
```bash
ssh user@10.0.0.190
sudo systemctl stop moltbook-alpha.service
cp /home/user/moltbook-alpha/data/moltbook.db /home/user/moltbook-alpha/data/moltbook_pre_hardening_$(date +%Y%m%d_%H%M%S).db
```

### Step 2: Fetch and Switch Branch
```bash
cd /home/user/moltbook-alpha
git fetch origin feat/commercial-api-hardening
git checkout feat/commercial-api-hardening
```

### Step 3: Run Additive Migration & Integrity Check
```bash
python3 -c "
from storage import StorageManager
s = StorageManager('/home/user/moltbook-alpha/data/moltbook.db')
assert s.check_integrity()
print('Database integrity and migration verified.')
"
```

### Step 4: Restart Service and Verify Health
```bash
sudo systemctl start moltbook-alpha.service
systemctl status moltbook-alpha.service
curl -s http://127.0.0.1:8080/v1/health | jq .
curl -s http://127.0.0.1:8080/v1/payments/config | jq .
```

