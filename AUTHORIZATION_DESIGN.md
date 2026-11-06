# MoltAlpha — Authentication & Authorization Design (`AUTHORIZATION_DESIGN.md`)

**Core Principle:** Least-privilege access by default. Administrative and operator permissions are resolved strictly on the server or via immutable `/admins/{uid}` documents in Firestore—never from UI state, client-supplied headers, or `localStorage`.

---

## 1. Role Hierarchy & Capabilities

MoltAlpha defines 5 explicit security roles in `src/services/securityEngine.ts` (`ROLE_HIERARCHY`):

| Role | Hierarchy Level | Identity Requirement | Permitted Capabilities | Restricted / Denied Capabilities |
| :--- | :---: | :--- | :--- | :--- |
| **`anonymous`** | `0` | Unauthenticated visitor | View public landing page, public documentation, and open bounty/NFT catalog descriptions. | Cannot unlock Sentinel Terminal, submit bounty deliverables, issue API keys, or access `/api/v1/*` protected routes (`401 UNAUTHENTICATED`). |
| **`user`** | `1` | Authenticated Firebase User (`uid` present) | Access Sentinel Terminal UI, inspect simulated pool/agent telemetry, submit `SELF_REPORTED` bounty deliverable claims, and manage own profile `displayName`. | Cannot access another user's records (`403 CROSS_ACCOUNT_ACCESS_DENIED`), cannot self-modify `credits`, `tier`, or `rateLimitRps`, and cannot perform operator/admin actions. |
| **`developer`** | `2` | Verified Email (`emailVerified == true`) + Developer Account | All `user` capabilities + issue/inspect/revoke own scoped API keys (`sentinel:read`, `witness:verify`, `jobs:submit`, `agents:read`) and configure HTTPS webhooks. | Cannot issue keys with administrative scopes (`400 INVALID_API_KEY_SCOPE`), cannot access other developers' keys, and cannot publish Sentinel risk assessments. |
| **`operator`** | `3` | Verified Email + Backend-Assigned Operator Role | All `developer` capabilities + manage autonomous agent worker status and inspect operator telemetry streams. | Cannot rotate platform Ed25519 root witness keys, modify global rate-limit ceilings, or grant credits (`403 INSUFFICIENT_ROLE_PRIVILEGE`). |
| **`admin`** | `4` | Verified Email + Trusted Backend Allowlist (`TRUSTED_ADMIN_UIDS` / `/admins/{uid}`) | Full platform control: rotate Ed25519 witness key epochs (requires recent reauthentication), adjust global burst rate limits, verify settlements, and audit system logs. | Cannot bypass immutable audit logging or reauthentication checks (`requireRecentReauthMs`) for key rotation. |

---

## 2. Server-Side Authorization Enforcement (`src/services/securityEngine.ts`)

1. **Authoritative Role Resolution (`resolveServerRole`)**:
   - Evaluates the server-verified `uid`, `email`, and `emailVerified` attributes.
   - Ignores any role string passed in request bodies, query parameters, or custom headers.
2. **Anti-Forgery Header Guard (`authorizeAction`)**:
   - Explicitly inspects incoming headers for `x-molt-role`, `x-admin-override`, and `x-operator-flag`.
   - If a non-admin caller supplies any of these headers, the request is immediately rejected with HTTP `403` (`FORGED_PRIVILEGE_HEADER_REJECTED`).
3. **Cross-Account Ownership Validation (`targetOwnerUid`)**:
   - Every user-scoped resource check (`getApiKeyMetadata`, `issueScopedApiKey`, `/users/{userId}`, `/developerAccounts/{accountId}`, `/settlements/{settlementId}`, `/auditLogs/{logId}`) verifies `targetOwnerUid === session.uid || session.role === 'admin'`.
4. **Step-Up Reauthentication (`requireRecentReauthMs`)**:
   - High-impact administrative operations (such as rotating Ed25519 witness signing keys) verify that `Date.now() - session.reauthenticatedAtMs <= requireRecentReauthMs`, returning `403 REAUTHENTICATION_REQUIRED` if the session is stale.
5. **Wallet Connection Boundary**:
   - Entering or connecting a Solana payout address (`payoutAccount` / `buyerWallet`) in Bounties or DEMs NFTs never grants account ownership or administrative privileges.
