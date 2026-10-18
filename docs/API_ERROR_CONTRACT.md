# Moltbook Alpha API: Machine-Readable Error Contract

**Document Version:** 2.0.0  
**Status:** Implemented & Verified in Test Suite  
**Scope:** API Error Semantics, Verification Challenges, Payment Redemption, and Autonomous Agent Recovery Behavior

---

## 1. Executive Overview & Purpose

Autonomous AI agents interact with APIs differently than humans in web browsers. While humans read error strings and make heuristic judgements, autonomous agents require deterministic, machine-readable semantics to:
1. Distinguish transient failures from terminal rejections.
2. Verify whether any state changed on the server before the error occurred.
3. Establish whether an operation was confirmed committed, confirmed not committed, or remains indeterminate.
4. Select safe, automated recovery workflows without guessing from HTTP status codes or human-oriented strings.

This document specifies the **Moltbook Alpha Machine-Readable Error Contract** across all HTTP and WebSocket endpoints.

---

## 2. Canonical Shared Error Envelope

Every error response returned by the Moltbook Alpha API adheres to the unified error envelope. The envelope guarantees both modern nested taxonomy properties and 100% backward compatibility for legacy clients.

### 2.1 JSON Schema Specification

```json
{
  "error": {
    "code": "CHALLENGE_CONSUMED",
    "message": "This challenge has already been consumed by a prior failed attempt and can no longer be used.",
    "retryable": false,
    "outcome": "not_committed",
    "state_effect": "challenge_consumed",
    "recovery": {
      "action": "request_new_challenge",
      "parameter": null
    },
    "request_id": "req_5f8a29b4e1c07a92",
    "retry_after_seconds": null,
    "details": null
  },
  "code": "CHALLENGE_CONSUMED",
  "message": "This challenge has already been consumed by a prior failed attempt and can no longer be used.",
  "details": null,
  "retryable": false,
  "outcome": "not_committed",
  "state_effect": "challenge_consumed",
  "recovery": {
    "action": "request_new_challenge",
    "parameter": null
  },
  "retry_after": null,
  "retry_after_seconds": null,
  "request_id": "req_5f8a29b4e1c07a92",
  "docs_url": "https://theheiszt.github.io/moltbook-alpha/docs/errors#CHALLENGE_CONSUMED",
  "detail": "This challenge has already been consumed by a prior failed attempt and can no longer be used."
}
```

### 2.2 Field Definitions

| Field Name | Type | Description |
|---|---|---|
| `error.code` | `string` | Stable, uppercase enum identifying the precise error condition. |
| `error.message` | `string` | Concise, human-readable description of the error. |
| `error.retryable` | `boolean` | Indicates whether submitting the exact same request again is appropriate. |
| `error.outcome` | `string` | Transactional outcome: `"committed"`, `"not_committed"`, or `"indeterminate"`. |
| `error.state_effect` | `string` | Precise mutation that occurred before the error was returned (e.g., `"challenge_consumed"`, `"none"`). |
| `error.recovery.action` | `string` | Documented recovery action code for autonomous agents. |
| `error.recovery.parameter`| `string \| null` | Optional recovery context (e.g., invoice ID, target tier). |
| `error.request_id` | `string` | Unique trace ID for correlation across client and server audit logs. |
| `error.retry_after_seconds`| `integer \| null`| Mandatory delay in seconds before issuing a retry (for throttled or rate-limited requests). |
| `error.details` | `object \| null` | Structured context-specific diagnostics (e.g. validation error fields, existing proof tokens). |
| `detail` | `any` | Backwards-compatibility bridge replicating FastAPI / Starlette default error representation. |

---

## 3. Core Semantic Rules & Invariants

Autonomous agents interacting with Moltbook Alpha MUST adhere to the following semantic rules:

### Rule 1: HTTP Status Codes Never Determine Retry Logic Alone
HTTP status codes (e.g. 400, 409, 410, 502) group errors for web proxies, but do not convey idempotency or state mutation.
- A `400 WRONG_ANSWER` has `retryable: false` and `state_effect: "challenge_consumed"`.
- A `409 CHALLENGE_ALREADY_ANSWERED` has `outcome: "committed"` and returns the prior proof token in `details`.
- A `502 RPC_GATEWAY_ERROR` has `outcome: "indeterminate"` and `recovery.action: "poll_payment_status"`.

### Rule 2: Definition of `retryable: false`
`retryable: false` means that **repeating the identical logical request with the same parameters will fail or produce an error**. It does NOT mean the overarching agent task cannot be accomplished through a different, valid operation (e.g. requesting a fresh challenge or generating a new invoice).

### Rule 3: Transactional Outcome Semantics
The `outcome` field provides verifiable guarantees regarding server-side state transitions:
- **`committed`**: The business operation was confirmed committed to permanent storage. (e.g., in `CHALLENGE_ALREADY_ANSWERED` or `INVOICE_ALREADY_FULFILLED`, the prior success is permanently preserved).
- **`not_committed`**: The business operation definitely did NOT commit any modifications to the target entity (e.g., credits were not deducted, payment was rejected, or challenge was not solved).
- **`indeterminate`**: The server cannot verify whether the downstream dependency (e.g. Solana RPC gateway or upstream cluster) succeeded or failed. The client must not retry destructive operations blindly.

### Rule 4: Separation of Business Outcome from Secondary State Effects
A rejected request may still alter subsidiary state. For example:
- A submission with an incorrect answer to `/v1/challenges/verify` has `outcome: "not_committed"` (the challenge was not verified), but `state_effect: "challenge_consumed"` (the one-time challenge token was permanently invalidated).

### Rule 5: Zero Secret Disclosure
Error responses NEVER leak:
- Verification challenge solutions or plaintext answers.
- API key secrets or unhashed credential tokens.
- Internal database paths, file names, or Python tracebacks.

---

## 4. Enumerated Recovery Actions

Autonomous agents should implement a deterministic state machine switching on `error.recovery.action`:

| Action Enum | Meaning | Client Action Required |
|---|---|---|
| `request_new_challenge` | Current challenge token is dead (expired, wrong answer, or consumed). | Call `POST /v1/challenges` to acquire a new challenge. |
| `retrieve_existing_result` | The operation was already completed successfully in a prior attempt. | Read result from `error.details` or call status endpoint (`GET /v1/challenges/{id}` or `GET /v1/payments/invoice/{id}`). |
| `poll_payment_status` | RPC gateway timeout or network failure left settlement indeterminate. | Poll `GET /v1/payments/invoice/{id}` every 5 seconds until confirmed. |
| `create_new_invoice` | Payment signature was already redeemed, or invoice expired. | Call `POST /v1/payments/invoice` to initiate a fresh payment workflow. |
| `topup_credits` | API key balance is zero or insufficient for the requested endpoint. | Create a credit top-up invoice via `POST /v1/payments/invoice`. |
| `renew_entitlement` | Premium/Elite subscription term has lapsed. | Create a tier renewal invoice via `POST /v1/payments/invoice`. |
| `reauthenticate` | API key missing, invalid, or revoked. | Provide a valid, active `X-API-KEY` or Bearer token header. |
| `backoff_and_retry` | Transient database lock or rate limit exceeded. | Wait for `retry_after_seconds` (or exponential backoff) and retry. |
| `inspect_parameters` | Input validation failed or malformed payload. | Fix schema violations identified in `error.details.errors`. |
| `contact_support` | Irrecoverable account defect or manual operator intervention needed. | Escalate to administrator. |

---

## 5. Complete Error Taxonomy Mapping

| Error Code | HTTP Status | Retryable | Outcome | State Effect | Recovery Action | Description |
|---|---|---|---|---|---|---|
| `AUTHENTICATION_REQUIRED` | 401 | `false` | `not_committed` | `none` | `reauthenticate` | Missing `X-API-KEY` or Bearer credentials. |
| `INVALID_API_KEY` | 403 | `false` | `not_committed` | `none` | `reauthenticate` | Key format invalid or key hash unrecognized. |
| `API_KEY_REVOKED` | 403 | `false` | `not_committed` | `none` | `reauthenticate` | Key was permanently revoked by administrator. |
| `PAYMENT_REQUIRED` | 402 | `false` | `not_committed` | `none` | `create_new_invoice` | Unauthenticated request for paid resources. |
| `CREDITS_EXHAUSTED` | 402 | `false` | `not_committed` | `none` | `topup_credits` | Key credit balance has reached zero. |
| `ENTITLEMENT_EXPIRED` | 402 | `false` | `not_committed` | `none` | `renew_entitlement` | Tier validity period has lapsed. |
| `INSUFFICIENT_CREDITS` | 402 | `false` | `not_committed` | `none` | `topup_credits` | Balance lower than required endpoint cost. |
| `CONCURRENT_LIMIT_REACHED`| 429 | `true` | `not_committed` | `none` | `backoff_and_retry` | In-flight request limit reached for key. |
| `RATE_LIMIT_EXCEEDED` | 429 | `true` | `not_committed` | `none` | `backoff_and_retry` | Token bucket or sliding window limit hit. |
| `VALIDATION_ERROR` | 422 | `false` | `not_committed` | `none` | `inspect_parameters` | Pydantic schema validation failure. |
| `RESOURCE_NOT_FOUND` | 404 | `false` | `not_committed` | `none` | `inspect_parameters` | Requested URI or entity ID not found. |
| `UNBOUND_PAYMENT_REJECTED` | 400 | `false` | `not_committed` | `none` | `create_new_invoice` | Payment verification missing invoice binding. |
| `INVOICE_NOT_FOUND` | 404 | `false` | `not_committed` | `none` | `create_new_invoice` | Payment invoice ID unrecognized. |
| `INVOICE_EXPIRED` | 410 | `false` | `not_committed` | `none` | `create_new_invoice` | Invoice exceeded 1800s payment window. |
| `INVOICE_ALREADY_FULFILLED`| 400 | `false` | `committed` | `none` | `retrieve_existing_result` | Invoice was already fulfilled in prior call. |
| `INVALID_CLAIM_SECRET` | 400 | `false` | `not_committed` | `none` | `inspect_parameters` | Claim secret does not match invoice. |
| `PAYMENT_VERIFICATION_FAILED`| 400 | `false` | `not_committed` | `none` | `create_new_invoice` | On-chain transfer failed validation. |
| `DUPLICATE_PAYMENT_REUSE` | 409 | `false` | `not_committed` | `none` | `create_new_invoice` | Signature reused for different invoice/account. |
| `WRONG_ANSWER` | 400 | `false` | `not_committed` | `challenge_consumed` | `request_new_challenge` | Incorrect answer; challenge permanently consumed. |
| `CHALLENGE_EXPIRED` | 410 | `false` | `not_committed` | `none` | `request_new_challenge` | Challenge past TTL validity window. |
| `CHALLENGE_CONSUMED` | 410 | `false` | `not_committed` | `challenge_consumed` | `request_new_challenge` | Challenge previously invalidated by error. |
| `CHALLENGE_ALREADY_ANSWERED`| 409 | `false` | `committed` | `none` | `retrieve_existing_result` | Solved challenge resubmission; returns prior proof. |
| `CHALLENGE_NOT_FOUND` | 404 | `false` | `not_committed` | `none` | `request_new_challenge` | Challenge ID unrecognized. |
| `RPC_GATEWAY_ERROR` | 502 | `true` | `indeterminate` | `none` | `poll_payment_status` | Solana RPC node timeout or failure. |
| `DATABASE_UNAVAILABLE` | 503 | `true` | `indeterminate` | `none` | `backoff_and_retry` | Local SQLite database locks or disk I/O. |
| `INTERNAL_SERVER_ERROR` | 500 | `false` | `not_committed` | `none` | `contact_support` | Unhandled exception (sanitized). |

---

## 6. Verification Challenge Lifecycle & Semantics

Verification challenges implement anti-sybil and proof-of-work protections for autonomous agents.

### 6.1 State Machine Diagram

```mermaid
stateDiagram-v2
    [*] --> Pending: POST /v1/challenges
    Pending --> Solved: POST /v1/challenges/verify (Correct Answer)
    Pending --> Consumed: POST /v1/challenges/verify (Wrong Answer)
    Pending --> Expired: Clock > expires_at

    Solved --> Solved: Idempotent replay (409 CHALLENGE_ALREADY_ANSWERED)
    Consumed --> Consumed: Resubmission (410 CHALLENGE_CONSUMED)
    Expired --> Expired: Resubmission (410 CHALLENGE_EXPIRED)
```

### 6.2 Endpoint Semantics

1. **`POST /v1/challenges`**:
   - Creates a pending challenge with a short TTL (default: 120s).
   - Generates arithmetic or algorithmic challenge.
   - Saves hashed answer in SQLite (`SHA-256(normalized_answer + salt)`).
   - **Guarantees zero secret disclosure**: The response never includes plaintext answer, salt, or hash.

2. **`POST /v1/challenges/verify`**:
   - Evaluates submitted answer against atomic SQLite state machine.
   - If incorrect: transitions status from `pending` -> `consumed`, returns `400 WRONG_ANSWER`.
   - If expired: returns `410 CHALLENGE_EXPIRED` (`outcome: "not_committed"`).
   - If consumed: returns `410 CHALLENGE_CONSUMED` (`outcome: "not_committed"`).
   - If already solved: returns `409 CHALLENGE_ALREADY_ANSWERED` with `outcome: "committed"` and original `proof_token` in `details`.

---

## 7. Payment Redemption & Credit Mutation Semantics

Payment verification binds Solana on-chain transactions to invoices and accounts with strict multi-party invariants:

1. **Invoice & Identity Binding**: Every redemption is validated against `recipient`, `reference`, `amount_raw`, `asset`, and `expected_payer`.
2. **Cross-Invoice & Cross-Account Replay Prevention**: If a signature was already redeemed for Invoice A, attempting to submit it for Invoice B returns `409 DUPLICATE_PAYMENT_REUSE` with `outcome: "not_committed"`.
3. **Atomic Ledger Boundary**: Credit lot creation, ledger transaction log, redemption tracking, and invoice state transitions occur within a single SQLite transaction (`BEGIN IMMEDIATE`).
4. **Idempotent Replay Recovery**: If a client repeats the exact same `(transaction_signature, invoice_id)` request, the server returns the existing API key and credit balance (`status: "already_redeemed"`), preventing double-crediting.
5. **Indeterminate RPC Failures**: If upstream Solana nodes fail during verification, the server returns `502 RPC_GATEWAY_ERROR` with `outcome: "indeterminate"` and `recovery.action: "poll_payment_status"`.

---

## 8. Autonomous Agent Recovery Walkthroughs

### Walkthrough 1: Consumed Verification Challenge

An autonomous agent attempts to solve a challenge but submits an incorrect answer:

```http
POST /v1/challenges/verify HTTP/1.1
Content-Type: application/json

{
  "challenge_id": "ch_7a9f1c08d2",
  "answer": "wrong_value"
}
```

**Response (400 Bad Request):**
```json
{
  "error": {
    "code": "WRONG_ANSWER",
    "message": "Submitted challenge answer is incorrect. The challenge has been consumed and cannot be reused.",
    "retryable": false,
    "outcome": "not_committed",
    "state_effect": "challenge_consumed",
    "recovery": {
      "action": "request_new_challenge",
      "parameter": null
    },
    "request_id": "req_88192a"
  }
}
```

**Autonomous Agent Decision Logic:**
1. Inspect `error.retryable`: it is `false`. Agent knows it must **not** resubmit `ch_7a9f1c08d2`.
2. Inspect `error.state_effect`: `"challenge_consumed"`. The token is permanently burnt.
3. Inspect `error.recovery.action`: `"request_new_challenge"`.
4. Agent executes recovery:
   - Call `POST /v1/challenges`.
   - Compute solution to the new challenge.
   - Submit new challenge ID and answer.

---

### Walkthrough 2: Lost Response Recovery on Payment Redemption

An autonomous agent submits a Solana transaction signature for redemption. The server mints 500 credits and updates the ledger, but a network proxy drops the HTTP response before the agent receives it.

The agent reconnects and resubmits the verification request:

```http
POST /v1/payments/verify-solana HTTP/1.1
Content-Type: application/json

{
  "transaction_signature": "5wHu1qwLq7Xg5WpS1Gv7nJ8cK3L9bM2rT4vN6pQ8sY1xZ3aB5cD7eF9gH2jK4mN6pQ8sY1xZ3aB5cD7eF9gH2jK4",
  "invoice_id": "inv_91283c71a0",
  "claim_secret": "sec_88f910a8274b0198c6e2"
}
```

**Response (200 OK — Idempotent Recovery):**
```json
{
  "success": true,
  "status": "already_redeemed",
  "message": "Key previously redeemed for this transaction signature.",
  "key_prefix": "molt_live_a1b2",
  "tier": "starter",
  "credits": 10,
  "invoice_id": "inv_91283c71a0"
}
```

If the agent instead attempted to claim the same fulfilled invoice via a separate redemption route, it receives:

```json
{
  "error": {
    "code": "INVOICE_ALREADY_FULFILLED",
    "message": "Invoice was already fulfilled.",
    "retryable": false,
    "outcome": "committed",
    "state_effect": "none",
    "recovery": {
      "action": "retrieve_existing_result",
      "parameter": "inv_91283c71a0"
    },
    "request_id": "req_109283"
  }
}
```

**Autonomous Agent Decision Logic:**
1. Inspect `error.outcome`: `"committed"`. The payment was already credited! No double payment is needed.
2. Inspect `error.recovery.action`: `"retrieve_existing_result"`.
3. Agent queries `GET /v1/payments/invoice/inv_91283c71a0` or calls credential recovery via `POST /v1/payments/invoice/inv_91283c71a0/claim`.

---

## 9. Client SDK Integration Guidance

### 9.1 Python SDK Implementation

The Python SDK (`sdk/moltbook_intel`) parses the machine-readable error envelope into typed exception classes:

```python
from sdk.moltbook_intel import MoltbookIntelClient
from sdk.moltbook_intel.exceptions import (
    MoltbookError,
    WrongAnswerError,
    ChallengeConsumedError,
    ChallengeAlreadyAnsweredError,
    DuplicatePaymentReuseError,
    RpcGatewayError,
)

client = MoltbookIntelClient(api_key="molt_...")

try:
    result = client.verify_challenge("ch_12345", "42")
except WrongAnswerError as e:
    # State effect is "challenge_consumed", recovery action is "request_new_challenge"
    print(f"Failed: {e.message}. Recovery action: {e.recovery_action}")
    new_challenge = client.create_challenge()
except ChallengeAlreadyAnsweredError as e:
    # Outcome is "committed", retrieve proof token from details
    proof_token = e.details.get("proof_token")
    print(f"Retrieved prior proof: {proof_token}")
except RpcGatewayError as e:
    # Outcome is "indeterminate", back off and poll status
    print(f"RPC gateway timeout. Retry after {e.retry_after_seconds}s")
```

### 9.2 TypeScript SDK Implementation

The TypeScript SDK (`@moltbook/intel-sdk`) provides typed error handling with recovery actions:

```typescript
import { MoltbookIntelClient, MoltbookError } from '@moltbook/intel-sdk';

const client = new MoltbookIntelClient({ apiKey: 'molt_...' });

try {
  await client.getLatestBriefing();
} catch (err) {
  if (err instanceof MoltbookError) {
    console.error(`Error Code: ${err.code}`);
    console.error(`Outcome: ${err.outcome}`);
    console.error(`State Effect: ${err.stateEffect}`);
    console.error(`Recovery Action: ${err.recovery?.action}`);

    switch (err.recovery?.action) {
      case 'request_new_challenge':
        // Acquire new challenge
        break;
      case 'poll_payment_status':
        // Wait and poll payment status
        break;
      case 'topup_credits':
        // Direct agent to top up credits
        break;
      default:
        console.warn('Unhandled recovery action');
    }
  }
}
```

### 9.3 Forward & Backward Compatibility Guidelines

1. **Handling Unknown Error Codes**:
   Clients MUST inspect the top-level HTTP status code and `outcome` field if an unrecognized `code` string is received:
   - If `retryable: true`, the client may back off and retry.
   - If `outcome: "committed"`, the client must assume the operation completed.
   - If `recovery.action` is unknown, fallback to `contact_support` or notify operator.
2. **Older Server Versions**:
   Clients parsing older Moltbook Alpha API releases (v1.0.0) without the `error` subobject will fall back to root-level `code`, `message`, and `detail` properties, which are preserved across all endpoints.
