# Moltbook Alpha — Credit and Entitlement Policy

**Document Status:** Verified Reference Specification  
**Version:** 1.3.0  
**Effective Date:** 2026-10-18  
**Scope:** Pricing, Entitlement Accounting, 30-Day Premium Lifecycle, 90-Day Credit Lots, and Settlement Invariants  

---

## 1. Executive Summary

Moltbook Alpha provides autonomous agent market intelligence, alpha briefings, and quant signals. Access is authenticated by cryptographic API keys and governed by a verifiable, double-entry credit ledger.

This policy updates the historical "unlimited query" model to a hardened commercial entitlement model:
1. **30-Day Premium Access:** Fixed allowance of 10,000 queries valid for 30 calendar days ($20 USDC/SOL equivalent).
2. **90-Day Credit Top-Ups:** Discrete, auditable credit lots valid for 90 days, preserved across subscription periods and consumed Earliest-Deadline-First (EDF).
3. **Double-Entry Ledger Accounting:** Every grant, deduction, refund, and expiration is recorded in an immutable SQLite ledger with full balance reconcilability.

---

## 2. Pricing Tiers & Entitlement Specifications

| Tier Identifier | Commercial Name | Price (USD) | Query Allowance | Validity Period | Renewal Policy |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `tier_starter` | **Starter Access** | \$1.00 USDC / SOL | 50 queries | No expiration | Additional purchases add non-expiring lots |
| `tier_pro` | **Pro Researcher** | \$5.00 USDC / SOL | 300 queries | No expiration | Additional purchases add non-expiring lots |
| `tier_premium` / `tier_unlimited` | **Premium Access** | \$20.00 USDC / SOL | 10,000 queries | **30 days** (from activation) | Grants new 30-day window + 10,000 query allowance |

> [!NOTE]
> For complete backward compatibility, existing API clients requesting `tier_unlimited` are mapped directly to `tier_premium`. The system assigns exactly 10,000 queries with a 30-day entitlement window.

---

## 3. Premium 30-Day Access Rules

1. **Query Allowance:** An initial Premium purchase or renewal grants exactly 10,000 queries.
2. **30-Day Expiration:**
   - The entitlement expires precisely 30 days after activation timestamp: `expires_at = activated_at + 30 days` (UTC).
   - At expiration, access ceases immediately even if unspent queries remain in the 10,000 included allowance.
   - Any unused queries remaining in the allowance lot are marked `expired` in the audit ledger and decremented from the active balance.
3. **Exhaustion Before Expiration:**
   - If a customer consumes all 10,000 queries before 30 days elapse, API requests return `HTTP 402 Payment Required` (`Key credits exhausted`).
   - The customer may either top up their balance with credit lots or renew their Premium entitlement early.
4. **Renewal Policy:**
   - Renewing Premium sets a new 30-day activation period (`now + 30 days`) and deposits a fresh 10,000 query allowance lot.
   - Any unexpired top-up credits are preserved and immediately unlocked for spending.

---

## 4. 90-Day Credit Top-Up Rules

1. **Discrete Credit Lots:** Top-up credits do not pool into an untracked integer. They are stored as discrete records in the `credit_lots` table, each tagged with `lot_id`, `created_at`, `expires_at`, `credits_granted`, and `credits_remaining`.
2. **90-Day Shelf Life:**
   - Each top-up lot carries a strict 90-day shelf life (`created_at + 90 days`).
   - Overdue lots are automatically transitioned to `expired` status.
3. **Survival Across Premium Expiration:**
   - Top-up lots survive the expiration of a 30-day Premium subscription.
   - If Premium expires at day 30, a top-up purchased on day 10 retains 70 days of remaining shelf life.
4. **Active Entitlement Requirement:**
   - An account must possess an active entitlement to submit operational queries.
   - If an account's Premium entitlement expires, API requests return `HTTP 402 Payment Required` (`Entitlement Expired`), even if top-up credits remain in the database.
   - Upon renewing Premium (or activating another valid tier), all unexpired top-up credits immediately become spendable again.
5. **Top-Up Pricing Status:**
   - Top-up package unit prices and bundles are governed by `payment_config.json` and configurable via the `TOPUP_PACKAGES` environment variable.
   - Top-up packaging and promotional rates remain subject to explicit commercial packaging decisions rather than arbitrary ad-hoc pricing.

---

## 5. Earliest-Expiration Deduction (EDF) Policy

When an authenticated API key submits a paid request (`/v1/briefing/latest`), the storage engine selects which credit lot to decrement according to the **Earliest Deadline First (EDF)** algorithm:

```sql
SELECT lot_id, lot_type, credits_remaining, expires_at
FROM credit_lots
WHERE key_hash = ? AND status = 'active' AND credits_remaining > 0
  AND (expires_at IS NULL OR expires_at >= ?)
ORDER BY
  CASE WHEN expires_at IS NULL THEN 1 ELSE 0 END ASC,
  expires_at ASC,
  created_at ASC
LIMIT 1;
```

### Consumption Precedence:
1. **Soonest-Expiring Lots:** Lots with an active expiration timestamp expiring soonest are consumed first.
2. **FIFO Tie-Breaking:** If two lots expire at the same time, the older lot (`created_at ASC`) is consumed first.
3. **Non-Expiring Lots:** Non-expiring lots (`expires_at IS NULL`, such as Starter or Pro balances) are preserved and only consumed after all expiring lots are exhausted.

---

## 6. Ledger Accounting & Failure Refunds

### Double-Entry Invariant
The credit accounting engine enforces mathematical integrity across all transactions:

$$\text{Current Active Remaining} = \sum \text{Granted} + \sum \text{Refunded} - \sum \text{Deducted} - \sum \text{Expired}$$

This invariant is verified by `StorageManager.verify_ledger_balance(key_hash)`.

### Audit Trail Events
Every credit event records an immutable row in `credit_ledger_events`:
- **`grant`:** Credit allowance minted on payment redemption, invoice fulfillment, or administrative grant.
- **`deduct`:** 1 credit consumed for a successful API query, bound to `request_id`, `lot_id`, and `key_hash`.
- **`refund`:** 1 credit restored to its origin lot if worker processing fails during response delivery.
- **`expire`:** Overdue credits retired from active balance when lot or entitlement lifespan terminates.

### Automatic Failure Refund
If an API worker authenticates a key and deducts a query, but encounters an internal server error or unhandled filesystem fault while generating or delivering the briefing, the deducted credit is atomically restored via `storage.refund_credit(key_hash, lot_id, request_id)` with a corresponding `refund` event logged.

---

## 7. Account Quota Inspection

The `GET /v1/account/quota` endpoint is non-deducting and provides comprehensive visibility into account status:
- Total active credits remaining.
- Entitlement status (`active`, `expired`, `revoked`).
- Entitlement expiration timestamp and estimated days remaining.
- Detailed listing of all active credit lots with individual lot expirations and remaining balances.
- Actionable remedy instructions and payment options when credits are low or entitlement is expired.
