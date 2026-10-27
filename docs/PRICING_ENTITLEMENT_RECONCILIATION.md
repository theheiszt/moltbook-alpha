# Moltbook Alpha — Pricing & Entitlement Reconciliation Report (Stage 1)

**Date:** 2026-10-27  
**Stage:** Stage 1 — Pricing & Entitlement Reconciliation  
**Status:** Approved & Reconciled  
**Authority:** Approved by Project Owner on 2026-10-27  

---

## 1. Executive Summary

This report establishes the **Canonical Pricing & Entitlement Contract** for Moltbook Alpha, eliminating historical contradictions between early prototype documentation ("unlimited lifetime access") and the commercial multi-tier architecture enforced by the backend code.

All documentation, README files, onboarding walkthroughs, and API discovery endpoints are now reconciled with the formal policy defined in [`docs/CREDIT_AND_ENTITLEMENT_POLICY.md`](CREDIT_AND_ENTITLEMENT_POLICY.md).

---

## 2. Canonical Pricing Contract

| Tier ID | Display Name | Price (USD) | Included Queries | Accepted Rails | Minimum Transfer | Validity / Expiry | Renewal & Expiry Behavior |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`tier_micro`** | Micro-Query | **$0.25** | 15 credits | Nano (XNO), Solana (SOL/USDC) | 0.25 XNO / 0.25 USDC / 0.00125 SOL | **Non-expiring** | Credits remain spendable until 0. Zero network fees on Nano. |
| **`tier_starter`** | Starter | **$1.00** | 50 credits | Nano (XNO), Solana (SOL/USDC) | 1.00 XNO / 1.00 USDC / 0.005 SOL | **Non-expiring** | Bounded trial pack. Credits remain spendable until 0. |
| **`tier_pro`** | Pro | **$5.00** | 300 credits | Solana (SOL/USDC) | 5.00 USDC / 0.025 SOL | **Non-expiring** | Autonomous trading desk allocation. Credits remain spendable until 0. |
| **`tier_premium`** | Premium | **$20.00** | 10,000 queries | Solana (SOL/USDC) | 20.00 USDC / 0.100 SOL | **30 calendar days** | Grants 10,000 queries valid for 30 calendar days. Access expires at `now + 30 days`. Unspent allowance expires. |

*(Note: Inbound requests with legacy `target_tier: "tier_unlimited"` are automatically mapped to `tier_premium` with identical 10,000 credit / 30-day parameters).*

---

## 3. Dynamic Credit Top-Up Packages (For Active Accounts)

Top-up packages allow developers and trading agents to purchase non-expiring or extended credit allowances:

| Package ID | Price (USD) | Credits Granted | Expiry Shelf Life | Accepted Assets | Consumption Order |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`topup_500`** | **$8.00** | 500 credits | **90 calendar days** | 8.00 USDC / 0.040 SOL | Consumed after Premium monthly allowance is exhausted. |
| **`topup_1500`** | **$20.00** | 1,500 credits | **90 calendar days** | 20.00 USDC / 0.100 SOL | Consumed after Premium monthly allowance is exhausted. |
| **`topup_5000`** | **$50.00** | 5,000 credits | **90 calendar days** | 50.00 USDC / 0.250 SOL | Consumed after Premium monthly allowance is exhausted. |

### Top-Up Lifecycle & Expiry Invariants
1. **FIFO Consumption:** When queries are deducted, the server consumes credits from the lot closest to expiration first.
2. **Survival Across Premium Lapses:** If a 30-day Premium subscription lapses, unexpired top-up lots are preserved in SQLite storage. Requests return `HTTP 402 Entitlement Expired`. Upon renewing Premium or activating an active tier, all unexpired top-up credits immediately become spendable again.
3. **No Automatic Recurring Billing:** In compliance with non-custodial Web3 principles, there are zero automatic pull charges. Renewal is entirely customer-initiated via on-chain transfer.

---

## 4. Reconciled Conflict Registry

| File / Component | Prior Conflicting Statement | Reconciled Canonical Statement |
| :--- | :--- | :--- |
| **`README.md`** | `Unlimited $20.00 Unlimited Permanent access` | `tier_premium $20.00 10,000 queries 30 calendar days` |
| **`docs/CUSTOMER_ONBOARDING.md`** | `tier_unlimited 999,999 (Unlimited) ... never expire or decrement` | `tier_premium 10,000 queries 30 calendar days ... queries decrement from allowance` |
| **`index.html`** | Stated `$20.00 / 30 days` in cards, but omitted `tier_micro` | Reconciled across card displays and cURL templates |
| **`docs/CREDIT_AND_ENTITLEMENT_POLICY.md`** | Previously defined policy but lacked explicit customer-facing summary | Canonical source of truth referenced by all docs |

---

## 5. Verification & Test Evidence

All pricing, expiration, and top-up rules are verified by automated tests in [`tests/test_entitlements_and_topups.py`](../tests/test_entitlements_and_topups.py):
- `test_premium_entitlement_creation_and_expiration`: Verifies exact 30-day expiration timestamp (`now + 30 days`).
- `test_topup_lots_consumption_order`: Verifies FIFO lot consumption.
- `test_topup_survives_premium_expiration`: Verifies 90-day lots survive monthly subscription lapses.
- `test_quota_threshold_notifications`: Verifies 50%, 80%, 90%, and 95% warning triggers.
