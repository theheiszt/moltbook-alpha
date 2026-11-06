# MOLTALPHA — SECURITY ARCHITECTURE SPECIFICATION

**Project:** MoltAlpha — Autonomous Solana DEX Market Intelligence & Cryptographic Witness Platform  
**GCP / Firebase Development Project ID:** `promptforge-512701`  
**Firestore Database ID:** `ai-studio-82f0e603-e7bf-4334-81c9-4c1c596bf601`  
**AI Studio Applet ID:** `82f0e603-e7bf-4334-81c9-4c1c596bf601`  
**Market Data Provider:** Coinbase Public REST APIs only (`api.exchange.coinbase.com` & `api.coinbase.com`)  
**Operating Mode:** Security-First Development Isolation — No Unsupervised Production Changes

---

## 1. System Overview & Architectural Topology

MoltAlpha is a full-stack TypeScript application consisting of a React 19 Single-Page Application (`src/`) and an Express.js backend API gateway (`server.ts` listening on port `3000`), integrated with an isolated Firebase Authentication and Cloud Firestore development environment (`promptforge-512701`).

All security controls are designed under a **Zero-Trust Client Assumption**: the browser runtime, client-side React state, query parameters, local storage, and HTTP request headers/bodies are treated as untrusted. Every privileged state transition is enforced independently at the server API boundary (`server.ts` + `src/services/securityEngine.ts`) and at the database boundary (`firestore.rules`).

```
+===================================================================================================+
|                             ZONE 0: UNTRUSTED CLIENT / AGENT ZONE                                 |
|  - Browser SPA (src/App.tsx, SentinelTerminalPage, DevelopersPricingPage, AdminPanelPage, etc.)   |
|  - Autonomous Agent CLI / External HTTP Callers                                                   |
|  - Firebase Web SDK (Auth + Firestore client subject to server-enforced firestore.rules)          |
|  - Client-Side UI Preview Helpers (src/utils/cryptoEngine.ts — non-authoritative preview only)    |
+=================================================+=================================================+
                                                  |
     HTTPS REST (/api/v1/*, /api/*)               |  Firebase Web SDK (WSS / HTTPS)
     Authorization: Bearer <Firebase RS256 JWT>   |  Authorization: Bearer <Firebase RS256 ID Token>
     or Bearer molt_sig_v1.<kid>.<payload>.<mac>  |
                                                  v
+=================================================+=================================================+
|   TRUST BOUNDARY 1: EXPRESS API GATEWAY         |   TRUST BOUNDARY 2: CLOUD FIRESTORE RULES       |
|   (server.ts + src/services/securityEngine.ts)  |   (firestore.rules — 13 Collection Policies)    |
|                                                 |                                                 |
|  1. Header & Body Sanitization:                 |  1. Deny-by-Default Wildcard Fallback:          |
|     - Blocks x-molt-role / x-admin-override     |     match /{document=**} { allow: if false; }   |
|     - Blocks client identity injection (403)    |  2. Anti-Self-Escalation on /users/{uid}:       |
|  2. Cryptographic Session Verification:         |     - Create forces tier='Micro', credits=0,    |
|     - Rejects plaintext dev_session:* (401)     |       rateLimitRps=15, status='Active'          |
|     - Verifies RS256 Firebase ID JWTs against   |     - Update locks tier, credits, rateLimitRps, |
|       Google SecureToken X.509 certificates     |       status, uid, createdAt                    |
|     - Issues/verifies HMAC-SHA256 molt_sig_v1   |  3. Financial & Reputation Integrity:           |
|       tokens with kid rotation & jti revocation |     - Completed settlements & VERIFIED_DELIVERY |
|  3. RBAC & Ownership Enforcement:               |       statuses restricted strictly to isAdmin() |
|     - 5-tier role hierarchy + IDOR guard        |  4. Schema & Payload Bounds:                    |
|     - Step-up reauthentication (< 15 min)       |     - Regex ID validation, string length caps,  |
|  4. Sliding-Window Rate Limiter (429)           |       and field-count bounds on every write     |
+========================+========================+=================================================+
                         |
                         | Internal Server-Only Access
                         v
+========================+========================+=================================================+
|   TRUST BOUNDARY 3: DURABLE SECURITY LEDGER     |   TRUST BOUNDARY 4: UPSTREAM MARKET DATA        |
|   & NODE:CRYPTO SIGNING ENGINE                  |   (Coinbase Public REST APIs Only)              |
|                                                 |                                                 |
|  - Atomic disk ledger (temp write + renameSync) |  - Primary: api.exchange.coinbase.com           |
|  - SHA-256 hashed API keys (raw key never saved)|    /products/{SYMBOL}-USD/stats                 |
|  - Permanent payment txHash & idempotency       |  - Fallback: api.coinbase.com                   |
|    replay registry (never cleared by .clear())  |    /v2/exchange-rates?currency=USD              |
|  - Durable revokedSessionJtis & hmacKeysHex     |  - Provenance: Returns null for unavailable     |
|  - Real Ed25519 private key signing via         |    live 24h stats (stats24hAvailable: false)    |
|    crypto.sign(null, ...) over RFC 8785 JSON    |    and isolates demo fallback metrics           |
+=================================================+=================================================+
```

---

## 2. Trust Boundaries

### 2.1 Trust Boundary 1 — Untrusted Client / Browser Runtime vs. Server API Gateway (`server.ts`)
- **Boundary Location**: Express HTTP entry points in `server.ts` (`/api/v1/*` and `/api/market-intelligence`), backed by `src/services/securityEngine.ts`.
- **Threat Model**: Malicious users or compromised agents may forge HTTP headers (`x-molt-role: admin`, `x-admin-override: true`), craft unsigned or tampered `Authorization: Bearer` tokens, replay settlement transaction hashes (`txHash`), inject XSS/SSRF URIs (`javascript:`, `data:`, `http://127.0.0.1`, `http://[::ffff:127.0.0.1]`, `http://169.254.169.254`), or manipulate URL query parameters (`?autostart=1`).
- **Enforcement Controls**:
  1. **UI Preview Isolation**: Client-side preview state (`operatorSessionActive` in `src/App.tsx`, triggered by `?autostart=1` or the `"Verify Operator Passkey"` demo button) affects local React rendering only. It never issues a server-valid `molt_sig_v1` session token and grants zero access to protected `/api/v1/*` routes or Firestore collections.
  2. **Privilege Header Rejection**: `authorizeAction` inspects `req.headers` and immediately aborts with `HTTP 403 FORGED_PRIVILEGE_HEADER_REJECTED` if any client-supplied role/override header (`x-molt-role`, `x-admin-override`, `x-user-tier`, `x-authenticated-uid`) is present.
  3. **Strict URI & Text Sanitization**: `validateSafeExternalUri` enforces `https://` or `ipfs://` schemes and blocks loopback (`127.0.0.0/8`, `::1`, `::ffff:127.0.0.1`), unspecified (`0.0.0.0/8`), link-local/cloud metadata (`169.254.0.0/16`, `fe80::/10`, `metadata.google.internal`), and RFC 1918 / IPv6 ULA private ranges (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `fc00::/7`). `sanitizePlainText` strips HTML/script tags and control characters.

### 2.2 Trust Boundary 2 — Untrusted Client SDK vs. Cloud Firestore (`firestore.rules`)
- **Boundary Location**: Google Cloud Firestore Security Rules (`firestore.rules`) evaluated on every Firebase Web SDK read, query, create, update, or delete against database `ai-studio-82f0e603-e7bf-4334-81c9-4c1c596bf601`.
- **Threat Model**: An attacker with a valid Firebase Auth account may bypass the React UI and invoke `setDoc`, `updateDoc`, or `getDocs` directly from the browser console to escalate their `tier` to `'Enterprise'`, inflate their `credits` balance, read other users' API keys or audit logs, or forge `'Completed'` payment settlements.
- **Enforcement Controls**:
  1. **Deny-by-Default Catch-All**: `match /{document=**} { allow read, write: if false; }` denies all access to any path not explicitly matched by one of the 13 collection policies.
  2. **Verified Identity Requirement**: `isSignedIn()` requires both `request.auth != null` and `request.auth.token.email_verified == true`.
  3. **Immutable Privileged Fields on User Profiles**: Users creating `/users/{userId}` must initialize `tier == 'Micro'`, `credits == 0`, `rateLimitRps == 15`, and `status == 'Active'`. On update, `request.resource.data.credits == resource.data.credits`, `request.resource.data.tier == resource.data.tier`, `request.resource.data.rateLimitRps == resource.data.rateLimitRps`, and `request.resource.data.status == resource.data.status` are strictly enforced unless `isAdmin()` is true.

### 2.3 Trust Boundary 3 — Server API Gateway vs. Durable Security Ledger & Cryptographic Engine
- **Boundary Location**: `src/services/securityEngine.ts` (server-only Node.js `fs` and `crypto` modules).
- **Threat Model**: Process restarts, multi-worker concurrency, private key leakage into frontend bundles, or memory-cap eviction wiping payment replay history.
- **Enforcement Controls**:
  1. **Crash-Safe Atomic Disk Persistence**: Security state (`hmacKeysHex`, `ed25519PrivateKeyPem`, `revokedSessionJtis`, `revokedWitnessKeyEpochs`, `processedPaymentTxHashes`, `processedIdempotencyKeys`, `apiKeys`, and `rateLimits`) is persisted to `moltalpha-security-ledger-v12b.json` (configurable via `MOLTALPHA_SECURITY_STORE_PATH`) using atomic temp-file writes (`mode: 0o600`) followed by `fs.renameSync`, and reloaded on every security check.
  2. **Permanent Payment Replay Guard**: `processedPaymentTxHashes` and `processedIdempotencyKeys` are append-only in durable storage and never call `.clear()`, preventing transaction hash replay across restarts or high-volume bursts.
  3. **Hashed API Key Storage & Constant-Time Verification**: `issueScopedApiKey` generates high-entropy `mk_dev_<48-hex>` keys, returns `rawKeyOnce` only in the initial creation response, and stores only `keyPrefix` and `keyHashSha256` (`SHA-256`) on disk. `verifyApiKeyCredential` compares key hashes using `crypto.timingSafeEqual`.
  4. **Server-Side Ed25519 Signing Isolation**: Real Ed25519 signing (`signServerEd25519Payload`) uses Node.js `crypto.sign(null, Buffer.from(canonicalPayload, 'utf8'), privKey)` on the backend. Private keys never enter the client bundle.

### 2.4 Trust Boundary 4 — Server Backend vs. External Upstream Coinbase REST APIs
- **Boundary Location**: `getLiveMarketTelemetry()` in `server.ts` making outbound read-only HTTPS requests to `https://api.exchange.coinbase.com` and `https://api.coinbase.com`.
- **Threat Model**: Upstream API downtime, missing 24h product pairs on Coinbase Exchange (e.g., `POPCAT-USD`), cross-chain symbol collision, or silent fabrication of live market metrics.
- **Enforcement Controls**:
  1. **Single Approved Upstream Provider**: Only Coinbase public REST endpoints are queried (3,500 ms `AbortSignal.timeout`, 15-second server cache). CoinMarketCap and all unapproved third-party market providers are permanently excluded.
  2. **Canonical Solana Mint Binding**: Every tracked token in `TRACKED_TOKENS` is bound to its canonical Solana SPL mint address (`solanaMintAddress`).
  3. **Strict Live vs. Simulated Provenance**: When Coinbase Exchange 24h stats (`cbStats`) are unavailable for a token, `/api/market-intelligence` returns `null` for `change24hPct`, `high24hUsd`, `low24hUsd`, and `volume24hUsd` with `stats24hAvailable: false`, isolating demo fallback figures inside `simulatedDemoFallback: { isSimulatedDemo: true, ... }`.

---

## 3. Firebase Isolation Protocols

### 3.1 Environment Pinning & Resource Inventory

| Security Parameter | Isolated Development Value | Configuration Source |
| :--- | :--- | :--- |
| **GCP / Firebase Project ID** | `promptforge-512701` | `firebase-applet-config.json` & `src/services/securityEngine.ts` |
| **Firestore Database ID** | `ai-studio-82f0e603-e7bf-4334-81c9-4c1c596bf601` | `firebase-applet-config.json` & `src/firebase.ts` |
| **Firebase Auth Domain** | `promptforge-512701.firebaseapp.com` | `firebase-applet-config.json` |
| **Expected JWT Issuer (`iss`)** | `https://securetoken.google.com/promptforge-512701` | `src/services/securityEngine.ts` |
| **Expected JWT Audience (`aud`)** | `promptforge-512701` | `src/services/securityEngine.ts` |
| **Production Network Coupling** | **NONE** (Zero production credentials, webhooks, RPCs, or databases connected) | Verified across repository |

### 3.2 Mandatory Isolation Safeguards
1. **Strict Project & Database Binding**: `src/firebase.ts` initializes Firestore with the explicit named database ID `getFirestore(app, firebaseConfig.firestoreDatabaseId)` (`ai-studio-82f0e603-e7bf-4334-81c9-4c1c596bf601`), preventing accidental reads or writes to the `(default)` database or any external project.
2. **JWT Audience & Issuer Pinning**: Both `verifyFirebaseIdTokenRs256Sync` and `verifyAndExtractSessionToken` enforce `payload.aud === 'promptforge-512701'` and `payload.iss === 'https://securetoken.google.com/promptforge-512701'`. Tokens issued for any other Firebase project are rejected with `401`.
3. **No Unsupervised Production Changes**: Deployment of `firestore.rules` or application builds to production infrastructure is strictly gated on explicit human operator authorization.
4. **Static & Automated Rules Verification**: Every change to `firestore.rules` and `firebase-blueprint.json` is validated via `npx eslint firestore.rules` and `firestore.rules.test.ts` before execution.

### 3.3 Complete 13-Collection Firestore Security Rules Matrix (`firestore.rules`)

| Collection Path | Read (`get` / `list`) | Create (`create`) | Update (`update`) | Delete (`delete`) | Key Security Invariants Enforced |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `/users/{userId}` | Owner (`isOwner(userId)`) or `isAdmin()` | Owner (must set `tier=='Micro'`, `credits==0`, `rateLimitRps==15`, `status=='Active'`) or `isAdmin()` | Owner (may only update `displayName`, `walletAddress`, `updatedAt`; `tier`, `credits`, `rateLimitRps`, `status` locked) or `isAdmin()` | `false` (Immutable) | Blocks self-escalation of role tier, credit balance, rate limit, or account status. |
| `/roles/{userId}` | Owner (`isOwner(userId)`) or `isAdmin()` | `isAdmin()` only | `isAdmin()` only | `isAdmin()` only | Prevents users from assigning or modifying their own RBAC role (`user`, `developer`, `operator`, `admin`). |
| `/apiKeys/{keyId}` | Owner (`resource.data.ownerId == request.auth.uid`) or `isAdmin()` | Owner (`ownerId == request.auth.uid`, `revoked == false`, 64-char hex `keyHashSha256`, `<= 12` char `keyPrefix`) or `isAdmin()` | Owner (may only transition `revoked` from `false` to `true`; `keyHashSha256`, `scopes`, `rateLimitRps` locked) or `isAdmin()` | `isAdmin()` only | Raw API keys are prohibited in Firestore; only SHA-256 hashes and short prefixes are permitted. |
| `/usageLogs/{logId}` | Owner (`resource.data.ownerId == request.auth.uid`) or `isAdmin()` | `isAdmin()` only | `false` (Append-only) | `false` (Append-only) | Prevents clients from forging or deleting API consumption telemetry. |
| `/credits/{userId}` | Owner (`isOwner(userId)`) or `isAdmin()` | `isAdmin()` only | `isAdmin()` only | `false` (Immutable) | Prevents client-side credit balance manipulation. |
| `/payments/{paymentId}` | Owner (`resource.data.ownerId == request.auth.uid`) or `isAdmin()` | Owner (only `status == 'PendingVerification'`) or `isAdmin()` | `isAdmin()` only | `false` (Immutable) | Clients cannot mark payments as `Verified` or `Rejected`. |
| `/settlements/{settlementId}` | Owner (`resource.data.ownerId == request.auth.uid`) or `isAdmin()` | Owner (only `status == 'PendingVerification'`) or `isAdmin()` (`status in ['PendingVerification', 'Completed']`) | `isAdmin()` only | `false` (Immutable) | Clients cannot directly write `Completed` settlements or grant credits from browser JS. |
| `/bounties/{jobId}` | Public (`true`) | `isAdmin()` only | `isAdmin()` only | `isAdmin()` only | Only administrators can publish or modify bounty specifications and rewards. |
| `/agentSubmissions/{submissionId}` | Owner (`resource.data.submitterUid == request.auth.uid`) or `isAdmin()` | Authenticated user (`submitterUid == request.auth.uid` and `status == 'SELF_REPORTED'`) or `isAdmin()` | `isAdmin()` only | `isAdmin()` only | Submissions enter strictly as `SELF_REPORTED`; only admins/verifiers can promote to `VERIFIED_DELIVERY`. |
| `/agents/{agentId}` | Public (`true`) | `isAdmin()` only | `isAdmin()` only | `isAdmin()` only | Protects Agent Credit Bureau dossiers and `DuesProof™` BirthCert records from unauthorized mutation. |
| `/sentinelAssessments/{poolId}` | Public (`true`) | `isAdmin()` only | `isAdmin()` only | `isAdmin()` only | Prevents external callers from forging or overwriting pool risk scores (`SAFE` / `CRITICAL`). |
| `/witnessKeys/{keyId}` | Public (`true`) | `isAdmin()` only | `isAdmin()` only | `false` (Immutable) | Only administrators can register or rotate Ed25519 witness public key epochs; keys cannot be deleted. |
| `/auditLogs/{logId}` | Owner (`resource.data.ownerId == request.auth.uid`) or `isAdmin()` | Owner (`actor == 'user'`, `ownerId == request.auth.uid`) or `isAdmin()` (`actor in ['admin', 'witness', 'system', 'user']`) | `false` (Append-only) | `false` (Append-only) | Append-only audit trail; non-admin users cannot spoof `'admin'`, `'witness'`, or `'system'` actor labels. |

---

## 4. Authorization Flow for All Privileged Operations

### 4.1 Five-Tier Role-Based Access Control (RBAC) Hierarchy

Roles are ordered strictly by privilege level in `src/services/securityEngine.ts`:

$$\texttt{anonymous (0)} < \texttt{user (1)} < \texttt{developer (2)} < \texttt{operator (3)} < \texttt{admin (4)}$$

- **Role Resolution (`resolveServerRole`)**:
  1. If `uid` is missing or `emailVerified !== true` or `tokenCryptographicallyVerified !== true`, the caller is assigned `'anonymous'`.
  2. `'admin'` privilege is granted **exclusively** when the verified token's `uid` is in `TRUSTED_ADMIN_UIDS` (`uid_molt_superadmin_01`), its verified email is in `TRUSTED_ADMIN_EMAILS` (`syntheticinquiry@gmail.com`), or a server-signed token carries `assignedRole === 'admin'` issued by server authority.
  3. No client header, query parameter, or request body field can influence role resolution.

### 4.2 Step-by-Step Authentication & Authorization Lifecycle

```
[Client Browser / Agent]                                  [Express Server: server.ts + securityEngine.ts]
          |                                                                      |
          | 1. Sign in via Firebase Auth -> Receive Google RS256 ID Token        |
          |--------------------------------------------------------------------->|
          |    POST /api/v1/auth/session                                         |
          |    Authorization: Bearer <Firebase_RS256_ID_Token>                   |
          |    Body: {} (Any uid/email/role in body -> 403 BLOCKED)              |
          |                                                                      |
          |                                  2. Fetch Google SecureToken X.509   |
          |                                     certs & verify RS256 signature,  |
          |                                     aud='promptforge-512701', iss,   |
          |                                     exp, iat, email_verified         |
          |                                  3. Resolve role from server-side    |
          |                                     allowlist & mint HMAC-SHA256     |
          |                                     molt_sig_v1.<kid>.<payload>.<mac>|
          |<---------------------------------------------------------------------|
          |    200 OK { sessionToken: "molt_sig_v1.hmac_epoch_v1..." }           |
          |                                                                      |
          | 4. Invoke Privileged Operation                                       |
          |--------------------------------------------------------------------->|
          |    POST /api/v1/admin/rotate-key (or /keys/issue, /settlements, etc.)|
          |    Authorization: Bearer molt_sig_v1.<kid>.<payload>.<mac>           |
          |                                                                      |
          |                                  5. enforceRateLimit() -> 429 if >cap|
          |                                  6. verifyAndExtractSessionToken():  |
          |                                     - Reject dev_session:* (401)     |
          |                                     - Lookup HMAC secret by <kid>    |
          |                                     - crypto.timingSafeEqual MAC     |
          |                                     - Check revokedSessionJtis (401) |
          |                                     - Check aud, iss, exp            |
          |                                  7. authorizeAction():               |
          |                                     - Reject x-molt-role headers(403)|
          |                                     - Enforce targetOwnerUid (IDOR)  |
          |                                     - Enforce ROLE_HIERARCHY         |
          |                                     - Enforce requireRecentReauthMs  |
          |                                  8. Execute operation & persist to   |
          |                                     atomic disk security ledger      |
          |<---------------------------------------------------------------------|
          |    200 OK (or 401 / 403 / 409 / 429 on policy violation)             |
```

### 4.3 Authorization Flow by Privileged Operation

#### 1. Session Token Issuance (`POST /api/v1/auth/session`)
- **Required Input**: `Authorization: Bearer <Firebase_RS256_ID_Token>` and empty JSON body `{}`.
- **Security Checks**:
  - Rate limit: 20 requests / 60s per IP (`enforceRateLimit`).
  - Body inspection: Rejects any request containing `uid`, `email`, `role`, or `assignedRole` in `req.body` with `403 CLIENT_IDENTITY_INJECTION_BLOCKED`.
  - Token inspection: Rejects `dev_session:*` or `molt_sig_v1.*` tokens (`401 FIREBASE_ID_TOKEN_REQUIRED`); requires an upstream RS256 Firebase ID token.
  - Cryptographic validation: Verifies the RS256 signature against Google's X.509 certificates (`https://www.googleapis.com/robot/v1/metadata/x509/securetoken@system.gserviceaccount.com`) and validates `aud === 'promptforge-512701'`, `iss === 'https://securetoken.google.com/promptforge-512701'`, `sub`, `iat`, and `exp`.
  - Output: Issues a server-signed `molt_sig_v1.<kid>.<payloadB64>.<mac>` token with a unique `jti` (`sess_<24-hex>`).

#### 2. Session Token Revocation (`POST /api/v1/auth/revoke`)
- **Required Input**: `Authorization: Bearer molt_sig_v1.<kid>.<payloadB64>.<mac>` or `{ jti }`.
- **Security Checks**:
  - Extracts and verifies the session token's `jti` via `revokeServerSessionToken`.
  - Appends `jti` to `state.revokedSessionJtis` in the durable disk ledger (`moltalpha-security-ledger-v12b.json`).
  - Subsequent calls to `verifyAndExtractSessionToken` with that token immediately return `null` (`401`), even if `exp` has not yet elapsed.

#### 3. Scoped API Key Issuance, Inspection & Revocation (`POST /api/v1/keys/issue`, `GET /api/v1/keys/:keyId`, `POST /api/v1/keys/:keyId/revoke`)
- **Required Role**: `user` (`ROLE_HIERARCHY >= 1`) + strict ownership (`session.uid === targetOwnerUid` unless `session.role === 'admin'`).
- **Security Checks**:
  - Cross-account check: If `session.uid !== targetOwnerUid` and `session.role !== 'admin'`, aborts with `403 CROSS_ACCOUNT_ACCESS_DENIED` (prevents IDOR).
  - Scope allowlist: Validates that requested scopes are a non-empty subset of `['sentinel:read', 'witness:verify', 'jobs:submit', 'agents:read']`; unknown scopes (`admin:root_shell`) are rejected with `400 INVALID_API_KEY_SCOPE`.
  - Hashed persistence: Generates `mk_dev_<48-hex>`, computes `keyHashSha256 = sha256Hex(rawKeyOnce)`, and persists only `keyPrefix` and `keyHashSha256` to the durable disk ledger.
  - Revocation: `revokeScopedApiKey` sets `revoked = true` in durable storage; any subsequent `verifyApiKeyCredential` call with the revoked key fails with `403 API_KEY_REVOKED`.

#### 4. Multi-Rail Settlement Verification & Credit Granting (`POST /api/v1/settlements/verify`)
- **Required Role**: `user` (`ROLE_HIERARCHY >= 1`).
- **Security Checks**:
  - Tampering guard: If `req.body` contains `creditsGranted`, `newBalance`, or `overrideAmountUsd`, aborts immediately with `403 CREDIT_BALANCE_TAMPERING_BLOCKED`.
  - Tier & rail validation: Validates `tier in ['Micro', 'Starter', 'Pro', 'Enterprise']`, `rail in ['SOL', 'USDC', 'Nano']`, and `txHash` format (`12–128` alphanumeric characters).
  - Durable replay prevention: Checks `state.processedPaymentTxHashes` and `state.processedIdempotencyKeys` (`pay:${session.uid}:${idempotencyKey}`) in the durable disk ledger. Any duplicate `txHash` or `idempotencyKey` is rejected with `409 PAYMENT_REPLAY_DETECTED`.
  - Sandbox provenance: Records the settlement in the durable ledger with `verificationMode: 'SIMULATED_SANDBOX_RECEIPT'` (client-side Firestore rules independently prohibit clients from writing `Completed` settlements directly).

#### 5. Autonomous Bounty Deliverable Submission (`POST /api/v1/jobs/:id/submit`)
- **Required Role**: `user` (`ROLE_HIERARCHY >= 1`).
- **Security Checks**:
  - Reputation tampering guard: If `req.body` includes `reliabilityPct`, `reputationTier`, `knownDeliveries`, `verificationStatus`, or `birthCertStatus`, aborts with `403 AGENT_REPUTATION_TAMPERING_BLOCKED`.
  - SSRF & XSS URI validation: Validates `deliverableUri` via `validateSafeExternalUri` (blocks `javascript:`, `data:`, loopback `127.0.0.0/8`, `::ffff:127.0.0.1`, link-local `169.254.169.254`, and private networks).
  - Summary sanitization: Enforces 40–1,000 characters via `sanitizePlainText`.
  - Idempotency & provenance: Deduplicates `job_submit:${session.uid}:${idempotencyKey}` (`409 DUPLICATE_SUBMISSION_BLOCKED`) and assigns `provenance: 'SELF_REPORTED'` (`verifiedDeliveriesIncrement: 0`) until independent verification.

#### 6. Sentinel Risk Assessment Publication (`POST /api/v1/sentinel/preflight`)
- **Required Role**: `admin` (`ROLE_HIERARCHY === 4`).
- **Security Checks**:
  - Any non-admin caller attempting to publish or overwrite a pool risk score or status is rejected with `403 SENTINEL_SCORE_FORGERY_BLOCKED`.
  - Validates pool pair format, `riskScore` bounds (`[0, 10]`), and `status in ['SAFE', 'WATCH', 'HIGH', 'CRITICAL']`.

#### 7. Cryptographic Witness Key & Session Key Rotation (`POST /api/v1/admin/rotate-key`)
- **Required Role**: `admin` (`ROLE_HIERARCHY === 4`) + recent reauthentication (`requireRecentReauthMs: 900_000` — within 15 minutes).
- **Security Checks**:
  - Rate limit: 10 requests / 60s per IP (`429 RATE_LIMIT_EXCEEDED`).
  - Privilege & step-up check: Verifies `session.role === 'admin'` and `Date.now() - session.reauthenticatedAtMs <= 900_000` (`403 REAUTHENTICATION_REQUIRED` if stale).
  - Execution: Calls `rotateSessionSigningSecret(false)` to generate a new 256-bit HMAC key epoch (`hmac_epoch_vN`) in the durable security ledger and records the new Ed25519 witness epoch (`newEpochId`).

#### 8. Server-Side Ed25519 Witness Attestation & Verification (`POST /api/v1/witness/attest`, `POST /api/v1/witness/verify`, `GET /api/v1/sentinel/agents/:id`)
- **Security Checks**:
  - Canonicalizes the input JSON payload per **RFC 8785 (JSON Canonicalization Scheme)** (`canonicalizeJsonRfc8785`).
  - Signs the canonical UTF-8 byte sequence on the server using Node.js `crypto.sign(null, Buffer.from(canonicalJson, 'utf8'), privKey)` with the server's durable Ed25519 private key.
  - Verifies signatures via `crypto.verify(null, ...)` and rejects any signature whose `keyEpochId` appears in `state.revokedWitnessKeyEpochs`.
  - For Agent Credit Bureau lookups (`GET /api/v1/sentinel/agents/:id` and UI BirthCert verification), `verifyDuesProofBirthCert` rejects `PROVISIONAL` (`UNOBSERVED` unknown agents), `DUES_DEFAULT_REVOKED` (`frantic_129`), and `Revoked` key epochs, and preset demo profiles (`antigravityandrew`, `jeeves_hermes`, `osai2026`) explicitly disclose `'0.00 USDC / 0.00 SOL On-Chain (Simulated Sandbox Demo — No Real Financial Bond Staked)'`.
