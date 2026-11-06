# MoltAlpha — Firebase Security Audit (`FIREBASE_SECURITY_AUDIT.md`)

**Audited Environment:** Isolated AI Studio Firebase Development Project (`promptforge-512701` / Database `ai-studio-82f0e603-e7bf-4334-81c9-4c1c596bf601`)  
**Production Deployment Status:** **NOT DEPLOYED TO PRODUCTION** (Held in development workspace per Section 2 Mandatory Operating Restrictions & Firebase Isolation Directive).

---

## 1. Executive Summary of Pre-Implementation Inspection Findings

Before modifying the application, a complete inspection of `/src/firebase.ts`, `/firestore.rules`, `/firebase-blueprint.json`, `/src/App.tsx`, and the frontend components was performed and recorded:

| Finding ID | Severity | Component / Collection | Description of Vulnerability Found During Audit | Remediation Implemented | Status Classification |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **F-01** | **CRITICAL** | `/firestore.rules` (`/users/{userId}`) & `/src/App.tsx` | Previous rule allowed any authenticated user creating or updating `/users/{userId}` to specify arbitrary `credits` (up to `1,000,000,000`), `tier: 'Enterprise'`, and `rateLimitRps: 100000`. | Hardened `/users/{userId}` in `firestore.rules` so non-admin users can only `create` with `tier == 'Micro' && credits == 0 && rateLimitRps == 15 && status == 'Active'`, and on `update` can only modify `['displayName', 'updatedAt']`. Updated `src/App.tsx` accordingly. | `VERIFIED FIXED` |
| **F-02** | **CRITICAL** | `/firestore.rules` (`/settlements/{settlementId}`) & `/src/App.tsx` | Previous rule allowed any verified user to directly `create` a document in `/settlements/{settlementId}` with `status == 'Completed'` and arbitrary `creditsGranted` from browser JavaScript. | Restricted `/settlements/{settlementId}` `create` and `update` to `isAdmin()` (trusted backend/admin boundary) and added server-side replay/idempotency verification in `/api/v1/settlements/verify`. Removed direct client settlement writes from `src/App.tsx`. | `VERIFIED FIXED` |
| **F-03** | **HIGH** | `/firestore.rules` (`/auditLogs/{logId}`) & `/src/App.tsx` | Previous rule allowed any authenticated user to write audit logs claiming `actor: 'admin'` or `actor: 'witness'`. | Enforced `(incoming().actor == 'user' || isAdmin())` on `/auditLogs/{logId}` `create` and updated client audit log writes in `src/App.tsx` to use `actor: 'user'`. | `VERIFIED FIXED` |
| **F-04** | **HIGH** | `/firestore.rules` (Missing Collection Coverage) | Only 5 collections (`users`, `users/private`, `auditLogs`, `settlements`, `witnessKeys`) had explicit rules; `developerAccounts`, `apiKeys`, `agentIdentities`, `agentReputations`, `agentProofs`, `sentinelAssessments`, `witnessMetadata`, `platformAnalytics`, and `adminConfig` lacked explicit schemas. | Added explicit, schema-validated, least-privilege rules and validator functions for all 12 required collections in `/firestore.rules` and `/firebase-blueprint.json`. | `VERIFIED FIXED` |
| **F-05** | **MEDIUM** | UI Provenance & Simulated Intelligence Labeling | Simulated Sentinel risk scores and daily briefings displayed a green `LIVE` badge in `LandingPage.tsx` and `AdminPanelPage.tsx`. | Replaced `LIVE` badges on simulated intelligence with explicit `SIMULATED DEMO` / `SIMULATED DEMO TELEMETRY` badges and added provenance badges (`CRYPTOGRAPHICALLY_VERIFIED` vs `SELF_REPORTED`) to Agent Lookup deliverables. | `VERIFIED FIXED` |
| **F-06** | **MEDIUM** | Client-Side Passkey Demo Session (`operatorSessionActive`) | The instant sandbox passkey demo toggle in `src/App.tsx` unlocks UI previews locally without a server-signed Firebase ID token. | Explicitly isolated the sandbox demo session from Firestore writes (all Firestore rules require `request.auth != null && request.auth.token.email_verified == true`) and labeled the Admin Console as `Environment: Isolated Dev Sandbox (SIMULATED DEMO)`. | `VERIFIED SECURE FOR TESTED SCOPE` |

---

## 2. Eight Pillars Firestore Rule Audit

1. **Pillar 1 — Global Default-Deny Safety Net**: Present at lines 5–7 of `/firestore.rules` (`match /{document=**} { allow read, write: if false; }`).
2. **Pillar 2 — Verified Identity & Ownership Guards**: `isVerifiedUser()` enforces `request.auth != null && request.auth.token.email_verified == true`.
3. **Pillar 3 — Document ID & Path Sanitization**: `isValidId(id)` enforces `id is string && id.size() >= 1 && id.size() <= 128 && id.matches('^[a-zA-Z0-9_\\-]+$')` on every path variable.
4. **Pillar 4 — Strict Key Whitelisting**: Every validator enforces both `data.keys().hasAll([...])` and `data.keys().hasOnly([...])` to block shadow field injection.
5. **Pillar 5 — Strict Type, Bounds & Enum Validation**: Every string, number, boolean, list, and timestamp field is bounded and checked against explicit allowlists.
6. **Pillar 6 — Server Timestamp Enforcement**: All `createdAt` and `updatedAt` fields require `== request.time`.
7. **Pillar 7 — Immutable & Terminal State Protection**: `uid`, `ownerId`, `createdAt`, `keyId`, `publicKey`, and `keyHashSha256` are locked against mutation on `update`; `Completed` settlements and `Revoked` witness keys cannot be reopened.
8. **Pillar 8 — Subcollection Parent Existence & PII Isolation**: `/users/{userId}/private/{docId}` verifies `exists(/databases/$(database)/documents/users/$(userId))` and blocks `list` queries (`allow list: if false;`).
