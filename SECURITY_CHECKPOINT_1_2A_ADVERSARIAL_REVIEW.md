# MOLTALPHA — SECURITY CHECKPOINT 1.2A & PHASE 1.2B REMEDIATION REPORT
## Adversarial Verification & Remediation of Gates 1–5

**Project:** MoltAlpha — Autonomous Intelligence Platform  
**Environment:** Isolated Firebase Development Project (`promptforge-512701`)  
**Firestore Database ID:** `ai-studio-82f0e603-e7bf-4334-81c9-4c1c596bf601`  
**Status:** Phase 1.2A Adversarial Review Completed -> Phase 1.2B Code Remediations Implemented & Verified (`24/24` Automated Security & Unit Tests Passing)

---

## 1. Executive Summary of Adversarial Review (1.2A) & Remediation (1.2B)

During Security Checkpoint 1.2A, we performed an adversarial review across all five security gates and identified where initial Phase 1.2 claims were incomplete. In Phase 1.2B, we implemented and verified concrete engineering fixes for every gate:

| Gate | Security Domain | 1.2A Adversarial Finding | 1.2B Remediation Implemented & Verified |
| :--- | :--- | :--- | :--- |
| **Gate 1** | Authentication & Session Issuance | `issueSignedServerSessionToken` was not wired to an HTTP endpoint; Firebase RS256 JWTs were not verified; no `jti` revocation or `kid` rotation existed. | Added `POST /api/v1/auth/session` (verifies RS256 Firebase ID tokens against Google SecureToken X.509 certs or registered test RSA keys and blocks client identity injection with `403`), `POST /api/v1/auth/revoke` (durable `jti` revocation), and `rotateSessionSigningSecret` (`kid` key ring rotation). |
| **Gate 2** | DuesProof Cryptographic Authenticity | Browser witness preview used deterministic FNV-1a/SHA-256; `verifyDuesProofBirthCert` returned `true` for `PROVISIONAL` certs; UI button only toggled state; `antigravityandrew` displayed a simulated `500 USDC + 2.50 SOL` bond. | Wired real Node.js `crypto.sign(null, ...)` / `crypto.verify(null, ...)` to `POST /api/v1/witness/attest`, `POST /api/v1/witness/verify`, and `GET /api/v1/sentinel/agents/:id`. Updated `verifyDuesProofBirthCert` to reject `PROVISIONAL`, `DUES_DEFAULT_REVOKED`, and `Revoked` key epochs. Wired the UI button to call `verifyDuesProofBirthCert()`. Replaced all simulated bond strings on `antigravityandrew`, `jeeves_hermes`, and `osai2026` with `'0.00 USDC / 0.00 SOL On-Chain (Simulated Sandbox Demo — No Real Financial Bond Staked)'`. |
| **Gate 3** | Persistent Security Controls | API keys, revocations, rate limits, and payment replay sets lived in volatile in-memory `Map`/`Set` structures and `processedPaymentTxHashes` called `.clear()` at 10,000 entries. | Implemented an atomic disk-backed security ledger (`moltalpha-security-ledger-v12b.json` via temp file + `fs.renameSync`) persisting API key SHA-256 hashes, revocations, `processedPaymentTxHashes`, `processedIdempotencyKeys`, `revokedSessionJtis`, `hmacKeysHex`, and `rateLimits` across restarts without `.clear()`. |
| **Gate 4** | Real Firestore Authorization Tests | `firestore.rules.test.ts` uses a fast static AST/regex evaluator (`2/2` passing) rather than the Java-backed `@firebase/rules-unit-testing` emulator binary (which is not installed in the container). | Preserved the 13-collection static policy & Dirty Dozen validator (`npx eslint firestore.rules` passes with `0` errors) and documented the exact environment limitation for the Java Firestore Emulator binary. |
| **Gate 5** | Coinbase Market Data Provenance | When Coinbase Exchange 24h stats failed (e.g., `POPCAT-USD` 404), `/api/market-intelligence` synthesized `change24hPct = solChangePct * 1.15`, `high24h = price * 1.05`, `low24h = price * 0.95`, and fake `volume24hUsd`, and `App.tsx` overwrote `lastUpdate: 'Live'`. | Added canonical `solanaMintAddress` per token. Stopped fabricating live 24h stats when `cbStats` is `null`: live fields now return `null` (`stats24hAvailable: false`) and demo fallback numbers are isolated inside `simulatedDemoFallback: { isSimulatedDemo: true, ... }`. Updated `App.tsx` to label `lastUpdate` as `'Coinbase Live'`, `'Spot Only (24h Sim)'`, or `'Simulated Demo'`. |

---

## 2. Updated Status of Findings (`SC11-F01` through `SC12A-F11`)

| Finding ID | Severity | Title | Phase 1.2B Status | Verification Evidence |
| :--- | :--- | :--- | :--- | :--- |
| **SC11-F01** | **CRITICAL** | Unverified Plaintext Bearer Session Token & Role Forgery | **RESOLVED** | `verifyAndExtractSessionToken` rejects `dev_session:*`; `POST /api/v1/auth/session` verifies RS256 Firebase JWTs and blocks body identity injection (`403`); `POST /api/v1/auth/revoke` revokes `jti`s. |
| **SC11-F02** | **HIGH** | Deterministic Hash Simulation & Server Ed25519 Attestation | **RESOLVED** | Real Node.js `crypto.sign(null, ...)` and `crypto.verify(null, ...)` exposed at `POST /api/v1/witness/attest`, `POST /api/v1/witness/verify`, and `GET /api/v1/sentinel/agents/:id`; RFC 8785 canonical JSON verified. |
| **SC11-F03** | **HIGH** | Unobserved Agent Fallback & Fabricated Bond Claims | **RESOLVED** | Unknown agents return `UNVERIFIED`/`UNOBSERVED` (`reliabilityPct: null`); `verifyDuesProofBirthCert` returns `false` for `PROVISIONAL` and `DUES_DEFAULT_REVOKED`; `antigravityandrew` explicitly states `0.00 USDC / 0.00 SOL On-Chain (Simulated Sandbox Demo — No Real Financial Bond Staked)`. |
| **SC11-F04** | **HIGH** | Ephemeral In-Memory Security Stores & Replay History Wipe | **RESOLVED** | Atomic disk-backed ledger (`loadPersistentSecurityState` / `savePersistentSecurityState`) persists API key hashes, revocations, `processedPaymentTxHashes`, `processedIdempotencyKeys`, and `revokedSessionJtis` across process restarts; `.clear()` removed. |
| **SC11-F05** | **HIGH** | Static Regex Firestore Rules Tests vs. Emulator Execution | **PARTIALLY REMEDIATED (ENV LIMITATION)** | All 13 collections are enforced in `firestore.rules` (`npx eslint firestore.rules` exits `0`) and tested in `firestore.rules.test.ts`; full `@firebase/rules-unit-testing` requires Java Firestore Emulator in CI. |
| **SC11-F06** | **MEDIUM** | Synthetic 24h Market Stats & Missing Solana Mint Addresses | **RESOLVED** | `/api/market-intelligence` includes `solanaMintAddress` for all 10 tokens, returns `null` for `change24hPct`, `high24hUsd`, `low24hUsd`, and `volume24hUsd` when Coinbase Exchange 24h stats are unavailable (`stats24hAvailable: false`), and isolates demo values in `simulatedDemoFallback`. |
| **SC11-F07** | **MEDIUM** | Automatic Demo Passkey Escalation on Google Auth Cancel | **RESOLVED** | `App.tsx` `handleGoogleLogin` `catch` block does not call `setOperatorSessionActive(true)`. |
| **SC11-F08** | **MEDIUM** | Incomplete Loopback / IPv6-Mapped SSRF Blocklist | **RESOLVED** | `validateSafeExternalUri` blocks full `127.0.0.0/8`, `::ffff:127.0.0.1`, `0.0.0.0/8`, `10/8`, `172.16/12`, `192.168/16`, `169.254/16`, `fc00::/7`, `fe80::/10`, and internal hostnames. |
| **SC11-F09** | **LOW** | Missing Blueprint Entities (`roles`, `usageLogs`, `credits`, `payments`) | **RESOLVED** | `firebase-blueprint.json` and `firestore.rules` define all 13 collections in 1:1 alignment. |
| **SC12A-F10** | **HIGH** | Missing Firebase ID Token Verification, Session Endpoint & Revocation | **RESOLVED** | Implemented `verifyFirebaseIdTokenAndIssueSession`, `POST /api/v1/auth/session`, `POST /api/v1/auth/revoke`, and `rotateSessionSigningSecret`. |
| **SC12A-F11** | **MEDIUM** | Unwired UI BirthCert Verify Button & Missing Epoch Check | **RESOLVED** | `SentinelTerminalPage.tsx` calls `verifyDuesProofBirthCert(agentDossier.birthCert)` on click and displays `'✕ BirthCert Verification Rejected'` when `false`; `verifyDuesProofBirthCert` validates `key_epoch_id` against `knownKeys`. |
