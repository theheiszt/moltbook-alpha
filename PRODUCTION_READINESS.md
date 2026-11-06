# MoltAlpha — Production Readiness & Migration Checklist (`PRODUCTION_READINESS.md`)

**Current Environment Status:** Isolated AI Studio Development & Security-Verification Sandbox (`promptforge-512701`).  
**Production Deployment Status:** **NO UNSUPERVISED PRODUCTION CHANGES PERFORMED** (Complies strictly with Section 2 Mandatory Operating Restrictions & Firebase Isolation Directive).

---

## 1. Readiness Assessment by Subsystem

| Subsystem | Current Development State | Verification Status | Required Action Before Authoritative Production Cutover |
| :--- | :--- | :--- | :--- |
| **Visual Design & UX Parity** | Opposing chamfered frames (`.cyber-cut`, `.cyber-cut-sm`), Neon Data Core background, frameless hero sections, rounded-square Risk Heatmap, real crypto/DEX icons, expandable pool rows, Bounties (`/v1/jobs`), DEMs NFTs (`/v1/nfts`), and Section 4 Agent Credit Bureau & `DuesProof™` BirthCert Lookup. | `VERIFIED SECURE FOR TESTED SCOPE` | Ready for frontend production bundle build (`npm run build`). |
| **Simulated vs. Authoritative Data Separation** | `SimulatedDemoDataProvider` (`src/services/dataProvider.ts`) marks all preview Sentinel scores, pool risk assessments, witness proofs, and agent dossiers with `mode: 'SIMULATED_DEMO'` and `isAuthoritative: false`. UI displays `SIMULATED DEMO` badges and never displays a `LIVE` badge for simulated intelligence. | `VERIFIED FIXED` | Implement an `AuthenticatedProductionApiDataProvider` conforming to `IMoltAlphaDataProvider` when connecting to the authorized MoltAlpha production backend. |
| **Firestore Security Rules (`firestore.rules`)** | Hardened locally across all 12 required collections (`users`, `developerAccounts`, `apiKeys`, `agentIdentities`, `agentReputations`, `agentProofs`, `sentinelAssessments`, `witnessMetadata`, `witnessKeys`, `platformAnalytics`, `settlements`, `adminConfig`, `auditLogs`). Passed ESLint and 22 automated security tests. | `VERIFIED FIXED` | **Requires Owner Approval (`REQUIRES MANUAL REVIEW`)**: Review diff of `/firestore.rules` in staging using the Firebase Emulator Suite before deploying to the production Firebase project. |
| **Server-Side RBAC & API Boundary (`server.ts`)** | Enforces server-resolved roles, rejects forged privilege headers, validates external URIs against XSS/SSRF, hashes issued API keys with SHA-256, and applies sliding-window rate limits + CSP headers. | `VERIFIED FIXED` | **Requires Manual Review (`REQUIRES MANUAL REVIEW`)**: Wire `resolveServerRole` to `firebase-admin` `auth().verifyIdToken(idToken, true)` using a Secret Manager service account in Cloud Run. |
| **Multi-Rail Payment & Settlement Verifier** | Rejects client-supplied `creditsGranted` overrides, blocks direct browser writes to `/settlements`, and prevents `txHash` / `X-Idempotency-Key` replay attacks in `securityEngine.ts`. | `VERIFIED FIXED` | **Requires Manual Review (`REQUIRES MANUAL REVIEW`)**: Connect settlement verifier to authoritative Solana Mainnet-Beta RPC and Nano RPC nodes with persistent Redis/Firestore replay ledgers before enabling real credit fulfillment. |
| **Cryptographic Ed25519 Witness Signing** | Canonical JSON (RFC 8785) serialization, SHA-256 digest computation, and Ed25519 key epoch attribution implemented. | `VERIFIED SECURE FOR TESTED SCOPE` | **Requires Manual Review (`REQUIRES MANUAL REVIEW`)**: Provision the production Ed25519 private signing key inside Google Cloud KMS / Secret Manager so private signing material never leaves the backend HSM boundary. |

---

## 2. Rollback & Safe Deployment Procedure (For Owner Execution Only)

1. **Snapshot Existing Production Rules & Indexes**:
   ```bash
   firebase firestore:rules:get --project <PRODUCTION_PROJECT_ID> >firestore.rules.prod.backup
   ```
2. **Run Local Verification Gate**:
   ```bash
   npx --yes tsx --test src/utils/cryptoEngine.test.ts firestore.rules.test.ts src/services/securityVerification.test.ts
   npx eslint firestore.rules
   npm run build
   ```
3. **Stage & Verify in Separate Staging Project First**:
   Deploy `firestore.rules` and the Cloud Run container to staging, verify Firebase App Check and Cloud Armor rate-limit policies, and only promote to production after manual sign-off.
