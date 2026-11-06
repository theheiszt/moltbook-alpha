# MoltAlpha — Firestore Collection Access Matrix (`FIRESTORE_COLLECTION_ACCESS_MATRIX.md`)

**Policy Model:** Deny-by-Default (`allow read, write: if false;`) with explicit per-operation rules (`get`, `list`, `create`, `update`, `delete`) across all 12 platform collections plus `/admins/{adminId}` and `/users/{userId}/private/{docId}`.

---

## 1. Collection Access Matrix

| # | Collection Path | `get` | `list` | `create` | `update` | `delete` | Protected / Immutable Fields & Anti-Tampering Invariants |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | `/users/{userId}` | Owner or Admin | Owner (`uid == auth.uid`) or Admin | Verified Owner (`tier == 'Micro'`, `credits == 0`, `rateLimitRps == 15`, `status == 'Active'`) or Admin | Verified Owner (**only** `['displayName', 'updatedAt']`) or Admin | Admin only | Non-admins can **never** modify `credits`, `tier`, `rateLimitRps`, `status`, `uid`, or `createdAt`. |
| **1b** | `/users/{userId}/private/{docId}` | Owner or Admin (`docId == 'info'` & parent exists) | `false` (Never listable) | Verified Owner or Admin (`docId == 'info'` & parent exists) | `false` | `false` | Isolates `email` PII from public user profile queries. |
| **2** | `/developerAccounts/{accountId}` | Owner (`ownerId == auth.uid`) or Admin | Owner or Admin | Verified Owner (`tier == 'Micro'`, `quotaRps == 15`, `status == 'Active'`) | Admin only | Admin only | Prevents developers from self-upgrading `tier` or `quotaRps`. |
| **3** | `/apiKeys/{keyId}` | Owner (`ownerId == auth.uid`) or Admin | Owner or Admin | Admin / Trusted Backend only | Verified Owner or Admin (**only** `status -> 'Revoked'`) | `false` | Stores only `keyPrefix` (6–16 chars) and `keyHashSha256` (64 hex chars). Raw secret is **never** stored. |
| **4** | `/agentIdentities/{agentId}` | Signed-in users | Signed-in users | Verified Owner (`ownerId == auth.uid`, `verificationStatus == 'UNVERIFIED'`) | Admin only | `false` | Agents/owners cannot self-assign `verificationStatus: 'ACTIVE'`. |
| **5** | `/agentReputations/{agentId}` | Signed-in users | Signed-in users | Admin / Trusted Backend only | Admin / Trusted Backend only | `false` | Users and agents can **never** modify `reliabilityPct`, `reputationTier`, `knownDeliveries`, `unfulfilledClaims`, `deadSponsorFlags`, or `duesProofStatus`. |
| **6** | `/agentProofs/{proofId}` | Signed-in users | Signed-in users | Verified Owner (`ownerId == auth.uid`, `provenance == 'SELF_REPORTED'`, `verifiedByBackend == false`, `https://` or `ipfs://`) | Admin / Trusted Backend only | `false` | Client submissions are locked to `SELF_REPORTED` and `verifiedByBackend == false` until verified by backend. |
| **7** | `/sentinelAssessments/{assessmentId}` | Signed-in users | Signed-in users | Admin / Trusted Backend only | Admin / Trusted Backend only | `false` | Clients can **never** create or modify pool risk scores, `SAFE` statuses, or witness signatures. |
| **8a** | `/witnessMetadata/{witnessId}` | Signed-in users | Signed-in users | Admin / Trusted Backend only | `false` (Immutable) | `false` | Append-only cryptographic witness attestation metadata. |
| **8b** | `/witnessKeys/{keyId}` | Owner or Admin | Owner or Admin | Admin only | Admin only (`status != 'Revoked'`, **only** `['status']`) | `false` | Protects Ed25519 public key epochs against unauthorized rotation or key replacement. |
| **9** | `/platformAnalytics/{metricId}` | Signed-in users | Signed-in users | Admin / Trusted Backend only | Admin / Trusted Backend only | `false` | Requires explicit `provenance in ['SIMULATED_DEMO', 'VERIFIED_TELEMETRY']`. |
| **10** | `/settlements/{settlementId}` | Owner (`ownerId == auth.uid`) or Admin | Owner or Admin | Admin / Trusted Backend only | Admin only (`existing().status != 'Completed'`) | `false` | Clients can **never** write `Completed` payment settlements from browser JS; `Completed` records are terminal. |
| **11** | `/adminConfig/{configId}` | Admin only | Admin only | Admin only | Admin only | `false` | Restricts global burst limits, mTLS flags, and key rotation cadence to verified Admins. |
| **12** | `/auditLogs/{logId}` | Owner (`ownerId == auth.uid`) or Admin | Owner or Admin | Verified Owner (`actor == 'user'`) or Admin | `false` (Immutable) | `false` | Append-only audit log; non-admins cannot forge `actor: 'admin'` or `'witness'`. |
| **13** | `/admins/{adminId}` | Self (`auth.uid == adminId`) or Admin | `false` | `false` (Console/Admin SDK only) | `false` | `false` | Prevents any client from granting admin status via Firestore client SDK. |
