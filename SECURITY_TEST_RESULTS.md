# MoltAlpha — Automated Security Verification Results (`SECURITY_TEST_RESULTS.md`)

**Test Runner Command:**
```bash
npx --yes tsx --test src/utils/cryptoEngine.test.ts firestore.rules.test.ts src/services/securityVerification.test.ts && npx eslint firestore.rules
```
**Execution Summary:** `22 passed, 0 failed` (`duration_ms: 542.5ms`), `eslint firestore.rules`: `0 errors, 0 warnings`.

---

## 1. Mandatory 15-Scenario Security Verification Matrix (Section 11)

| Scenario # | Mandatory Security Test Scenario | Test File & Test Name | Verification Method & Evidence | Status Classification |
| :---: | :--- | :--- | :--- | :--- |
| **1** | **Anonymous access restrictions** | `src/services/securityVerification.test.ts` (`Scenario 1`) & `firestore.rules.test.ts` | Verified `resolveServerRole(null, null, false)` resolves to `'anonymous'` and `authorizeAction(null, 'user' \| 'admin')` returns `401 UNAUTHENTICATED`. Unauthenticated Firestore operations return `PERMISSION_DENIED`. | `VERIFIED SECURE FOR TESTED SCOPE` |
| **2** | **Unauthorized access to another user’s records** | `src/services/securityVerification.test.ts` (`Scenario 2`) & `firestore.rules.test.ts` (`PII Blanket Read`, `Unauthorized List Scraping`) | Verified `user_alice_01` attempting to access `targetOwnerUid: 'user_bob_02'` receives `403 CROSS_ACCOUNT_ACCESS_DENIED`. Cross-user reads on `/users/{uid}/private/info` and `/auditLogs` return `PERMISSION_DENIED`. | `VERIFIED FIXED` |
| **3** | **Privilege escalation** | `src/services/securityVerification.test.ts` (`Scenario 3`) & `firestore.rules.test.ts` (`Client Self-Assigning Enterprise Tier`) | Verified ordinary user (`role: 'user'`) is denied `operator` and `admin` actions (`403 INSUFFICIENT_ROLE_PRIVILEGE`) and cannot self-assign `tier: 'Enterprise'` or `credits: 1000000` in `/users/{userId}`. | `VERIFIED FIXED` |
| **4** | **Forged admin roles** | `src/services/securityVerification.test.ts` (`Scenario 4`) & `firestore.rules.test.ts` (`Shadow Field Injection`, `Forged Admin Actor`) | Verified `x-molt-role: admin` and `x-admin-override: true` headers are rejected with `403 FORGED_PRIVILEGE_HEADER_REJECTED`, and `isAdmin: true` shadow fields or `actor: 'admin'` client audit logs return `PERMISSION_DENIED`. | `VERIFIED FIXED` |
| **5** | **Agent reputation manipulation** | `src/services/securityVerification.test.ts` (`Scenario 5`) & `firestore.rules` (`/agentReputations`, `/agentProofs`) | Verified client payloads containing `reliabilityPct: 100` are rejected with `403 AGENT_REPUTATION_TAMPERING_BLOCKED`, and valid submissions are forced to `provenance: 'SELF_REPORTED'`. | `VERIFIED FIXED` |
| **6** | **Sentinel score forgery** | `src/services/securityVerification.test.ts` (`Scenario 6`) & `firestore.rules` (`/sentinelAssessments`) | Verified non-admin callers attempting to supply `riskScore: 0.1`, `status: 'SAFE'`, or `signatureEd25519` are blocked with `403 SENTINEL_SCORE_FORGERY_BLOCKED`. | `VERIFIED FIXED` |
| **7** | **Cross-account API-key access** | `src/services/securityVerification.test.ts` (`Scenario 7`) & `firestore.rules` (`/apiKeys/{keyId}`) | Verified API key issuance returns `rawKeyOnce` only once, persists only 64-char `keyHashSha256`, and rejects cross-account inspection by `bob_uid` with `403 CROSS_ACCOUNT_ACCESS_DENIED`. | `VERIFIED FIXED` |
| **8** | **Credit balance tampering** | `src/services/securityVerification.test.ts` (`Scenario 8`) & `firestore.rules.test.ts` (`Client Self-Escalating Credits on Update`) | Verified `processVerifiedSettlementRequest` rejects client `creditsGranted: 25000` with `403 CREDIT_BALANCE_TAMPERING_BLOCKED`, and `/users/{userId}` update rule blocks credit mutations. | `VERIFIED FIXED` |
| **9** | **Payment replay attacks** | `src/services/securityVerification.test.ts` (`Scenario 9`) | Verified re-submitting an already processed `txHash` (`9xQeWvG816...`) or duplicate `X-Idempotency-Key` is blocked with `409 PAYMENT_REPLAY_DETECTED`. | `VERIFIED FIXED` |
| **10** | **Invalid and malicious API inputs** | `src/services/securityVerification.test.ts` (`Scenario 10`) & `firestore.rules.test.ts` (`ID Poisoning`, `Update-Gap Value Poisoning`, `Invalid Enum Injection`) | Verified disallowed API key scopes (`admin:root_shell`), invalid rails (`DOGE`), 2KB document IDs, and 5,000-char strings are rejected (`400` / `PERMISSION_DENIED`). | `VERIFIED SECURE FOR TESTED SCOPE` |
| **11** | **Excessive request rates** | `src/services/securityVerification.test.ts` (`Scenario 11`) | Verified `enforceRateLimit` allows 5 requests within window and blocks the 6th burst request with `429 RATE_LIMIT_EXCEEDED`. | `VERIFIED SECURE FOR TESTED SCOPE` |
| **12** | **Public data leakage** | `src/services/securityVerification.test.ts` (`Scenario 12`) | Verified `defaultDataProvider` envelopes all sandbox telemetry with `mode: 'SIMULATED_DEMO'` and `isAuthoritative: false`, and `/users/{userId}/private/{docId}` blocks unauthorized reads/lists. | `VERIFIED SECURE FOR TESTED SCOPE` |
| **13** | **Missing or overly permissive Firestore rules** | `src/services/securityVerification.test.ts` (`Scenario 13`) & `npx eslint firestore.rules` | Verified zero occurrences of `allow read, write: if true`, verified global `allow read, write: if false;` fallback, and passed `@google/eslint-plugin-firestore-rules` with 0 errors. | `VERIFIED FIXED` |
| **14** | **Secret exposure & market provider hygiene** | `src/services/securityVerification.test.ts` (`Scenario 14`) | Scanned frontend source files (`src/App.tsx`, `src/firebase.ts`, `src/utils/cryptoEngine.ts`, and page components) to confirm zero references to deprecated provider keys or private keys. | `VERIFIED SECURE FOR TESTED SCOPE` |
| **15** | **Unsafe agent-provided HTML or links (XSS & SSRF)** | `src/services/securityVerification.test.ts` (`Scenario 15`) | Verified `validateSafeExternalUri` blocks `javascript:alert(1)`, `data:text/html,...`, `https://127.0.0.1/admin`, `https://127.0.0.2/internal`, `https://[::ffff:127.0.0.1]/secret`, `https://169.254.169.254/...`, and `https://localhost:3000`, and `sanitizePlainText` strips `<script>` and `<img onerror=...>` tags. | `VERIFIED FIXED` |

---

## 2. Cryptographic & Domain Logic Unit Tests (`src/utils/cryptoEngine.test.ts`)

| Test # | Unit Test Name | Result |
| :---: | :--- | :--- |
| **16** | `classifyRiskScore categorizes microstructure risk scores accurately` | `PASS` |
| **17** | `formatCompactUsd formats millions and billions cleanly` | `PASS` |
| **18** | `canonicalizeJsonRfc8785 recursively sorts object keys in UTF-16 code-unit order without whitespace` | `PASS` |
| **19** | `buildWitnessAttestation & verifyWitnessAttestation enforce RFC 8785 digest, signature binding, and reject tampering (SC11-F02)` | `PASS` |
| **20** | `lookupAgentDossier returns UNVERIFIED/UNOBSERVED for unknown agents and verifies DuesProof BirthCerts (SC11-F03)` | `PASS` |
| **21** | `calculateMultiRailQuote computes accurate SOL, USDC, and Zero-Fee Nano settlements` | `PASS` |
| **22** | `rotateWitnessKeys promotes new Ed25519 key epoch to Active and rotates prior Active key` | `PASS` |
