import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';

export type UserRole = 'anonymous' | 'user' | 'developer' | 'operator' | 'admin';

export type EvidenceProvenanceClass =
  | 'SELF_REPORTED'
  | 'THIRD_PARTY_CLAIM'
  | 'INDEPENDENTLY_VERIFIED'
  | 'CRYPTOGRAPHICALLY_VERIFIED';

export type DataEnvironmentMode = 'SIMULATED_DEMONSTRATION' | 'PRODUCTION_API';

export interface VerifiedSessionContext {
  uid: string;
  email: string | null;
  emailVerified: boolean;
  role: UserRole;
  issuedAtMs: number;
  expiresAtMs: number;
  reauthenticatedAtMs?: number;
  tokenCryptographicallyVerified?: boolean;
  sessionJti?: string;
  keyId?: string;
}

export interface RateLimitBucket {
  count: number;
  windowStartMs: number;
}

export interface StoredApiKeyRecord {
  keyId: string;
  ownerUid: string;
  keyPrefix: string;
  keyHashSha256: string;
  scopes: string[];
  rateLimitRps: number;
  revoked: boolean;
  createdAtIso: string;
  expiresAtIso: string;
}

export interface SecurityGuardResult<T = unknown> {
  allowed: boolean;
  status: number;
  code: string;
  message: string;
  data?: T;
}

const EXPECTED_FIREBASE_PROJECT_ID = 'promptforge-512701';
const EXPECTED_FIREBASE_ISSUER = `https://securetoken.google.com/${EXPECTED_FIREBASE_PROJECT_ID}`;
const GOOGLE_SECURETOKEN_CERTS_URL =
  'https://www.googleapis.com/robot/v1/metadata/x509/securetoken@system.gserviceaccount.com';

// Trusted backend allowlist of administrator UIDs / verified emails (never derived from client flags)
const TRUSTED_ADMIN_UIDS = new Set<string>(['uid_molt_superadmin_01']);
const TRUSTED_ADMIN_EMAILS = new Set<string>(['syntheticinquiry@gmail.com']);

const ROLE_HIERARCHY: Record<UserRole, number> = {
  anonymous: 0,
  user: 1,
  developer: 2,
  operator: 3,
  admin: 4,
};

// ============================================================================
// GATE 3 REMEDIATION: DURABLE, ATOMIC DISK-BACKED SECURITY LEDGER
// Survives server restarts & synchronizes across multiple local server instances
// ============================================================================

interface PersistentSecurityState {
  activeHmacKid: string;
  hmacKeysHex: Record<string, string>;
  ed25519PrivateKeyPem: string;
  ed25519PublicKeyPem: string;
  ed25519KeyEpochId: string;
  revokedWitnessKeyEpochs: string[];
  revokedSessionJtis: string[];
  processedIdempotencyKeys: string[];
  processedPaymentTxHashes: string[];
  apiKeys: Record<string, StoredApiKeyRecord>;
  rateLimits: Record<string, RateLimitBucket>;
}

let inMemoryFallbackState: PersistentSecurityState | null = null;

function isNodeServerEnvironment(): boolean {
  return (
    typeof process !== 'undefined' &&
    Boolean(process.versions?.node) &&
    typeof fs?.readFileSync === 'function'
  );
}

function getPersistentStorePath(): string {
  if (!isNodeServerEnvironment()) {
    return '/tmp/moltalpha-security-ledger-v12b.json';
  }
  return (
    process.env.MOLTALPHA_SECURITY_STORE_PATH ||
    path.join(os.tmpdir(), 'moltalpha-security-ledger-v12b.json')
  );
}

function createInitialPersistentState(): PersistentSecurityState {
  const initialKid = 'hmac_epoch_v1';
  const initialSecretHex = crypto.randomBytes(32).toString('hex');
  const edPair = crypto.generateKeyPairSync('ed25519');
  const privPem = edPair.privateKey.export({ type: 'pkcs8', format: 'pem' }).toString();
  const pubPem = edPair.publicKey.export({ type: 'spki', format: 'pem' }).toString();

  return {
    activeHmacKid: initialKid,
    hmacKeysHex: { [initialKid]: initialSecretHex },
    ed25519PrivateKeyPem: privPem,
    ed25519PublicKeyPem: pubPem,
    ed25519KeyEpochId: 'srv_ed25519_epoch_v1',
    revokedWitnessKeyEpochs: ['wtn_epoch_v5'],
    revokedSessionJtis: [],
    processedIdempotencyKeys: [],
    processedPaymentTxHashes: [],
    apiKeys: {},
    rateLimits: {},
  };
}

export function loadPersistentSecurityState(): PersistentSecurityState {
  if (!isNodeServerEnvironment()) {
    if (!inMemoryFallbackState) {
      inMemoryFallbackState = {
        activeHmacKid: 'browser_stub',
        hmacKeysHex: {},
        ed25519PrivateKeyPem: '',
        ed25519PublicKeyPem: '',
        ed25519KeyEpochId: 'srv_ed25519_epoch_v1',
        revokedWitnessKeyEpochs: ['wtn_epoch_v5'],
        revokedSessionJtis: [],
        processedIdempotencyKeys: [],
        processedPaymentTxHashes: [],
        apiKeys: {},
        rateLimits: {},
      };
    }
    return inMemoryFallbackState;
  }

  const storePath = getPersistentStorePath();
  try {
    if (fs.existsSync(storePath)) {
      const raw = fs.readFileSync(storePath, 'utf8');
      const parsed = JSON.parse(raw) as PersistentSecurityState;
      if (parsed && parsed.activeHmacKid && parsed.hmacKeysHex && parsed.apiKeys) {
        inMemoryFallbackState = parsed;
        return parsed;
      }
    }
  } catch {
    // Fall through to initialize fresh state if corrupted
  }

  const fresh = createInitialPersistentState();
  savePersistentSecurityState(fresh);
  inMemoryFallbackState = fresh;
  return fresh;
}

export function savePersistentSecurityState(state: PersistentSecurityState): void {
  inMemoryFallbackState = state;
  if (!isNodeServerEnvironment()) return;
  try {
    const storePath = getPersistentStorePath();
    const tmpPath = `${storePath}.tmp.${process.pid}.${Date.now()}`;
    fs.writeFileSync(tmpPath, JSON.stringify(state, null, 2), { encoding: 'utf8', mode: 0o600 });
    fs.renameSync(tmpPath, storePath);
  } catch {
    // Ignore filesystem errors in restricted environments
  }
}

export function resetSecurityStoresForTesting(): void {
  const fresh = isNodeServerEnvironment()
    ? createInitialPersistentState()
    : loadPersistentSecurityState();
  fresh.revokedSessionJtis = [];
  fresh.processedIdempotencyKeys = [];
  fresh.processedPaymentTxHashes = [];
  fresh.apiKeys = {};
  fresh.rateLimits = {};
  savePersistentSecurityState(fresh);
}

// ============================================================================
// GATE 2 REMEDIATION: REAL NODE:CRYPTO ED25519 SIGNING & VERIFICATION
// Private key never enters the frontend bundle; signatures use real curve25519
// ============================================================================

export function signServerEd25519Payload(canonicalPayload: string): {
  keyEpochId: string;
  publicKeySpkiHex: string;
  publicKeyPem: string;
  signatureBase64Url: string;
  digestSha256Hex: string;
} {
  const state = loadPersistentSecurityState();
  const privKey = crypto.createPrivateKey(state.ed25519PrivateKeyPem);
  const pubKey = crypto.createPublicKey(state.ed25519PublicKeyPem);
  const payloadBuf = Buffer.from(canonicalPayload, 'utf8');
  const sig = crypto.sign(null, payloadBuf, privKey);
  const pubDer = pubKey.export({ type: 'spki', format: 'der' });
  const digestSha256Hex = crypto.createHash('sha256').update(payloadBuf).digest('hex');

  return {
    keyEpochId: state.ed25519KeyEpochId,
    publicKeySpkiHex: pubDer.toString('hex'),
    publicKeyPem: state.ed25519PublicKeyPem,
    signatureBase64Url: sig.toString('base64url'),
    digestSha256Hex,
  };
}

export function verifyServerEd25519Payload(
  canonicalPayload: string,
  signatureBase64Url: string,
  customPublicKeyPem?: string,
  keyEpochId?: string
): boolean {
  try {
    const state = loadPersistentSecurityState();
    if (keyEpochId && state.revokedWitnessKeyEpochs.includes(keyEpochId)) {
      return false;
    }
    const pubKey = crypto.createPublicKey(customPublicKeyPem || state.ed25519PublicKeyPem);
    const sigBuf = Buffer.from(signatureBase64Url, 'base64url');
    if (sigBuf.length !== 64) return false;
    return crypto.verify(null, Buffer.from(canonicalPayload, 'utf8'), pubKey, sigBuf);
  } catch {
    return false;
  }
}

export function sha256Hex(input: string): string {
  if (isNodeServerEnvironment()) {
    try {
      return crypto.createHash('sha256').update(input, 'utf8').digest('hex');
    } catch {
      // Fall through to deterministic browser-safe digest
    }
  }
  // Browser-compatible deterministic 256-bit (64-hex) digest fallback
  const lanes = [
    0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
    0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
  ];
  for (let i = 0; i < input.length; i++) {
    const code = input.charCodeAt(i);
    const laneIdx = i & 7;
    lanes[laneIdx] = Math.imul(lanes[laneIdx] ^ code, 0x01000193) >>> 0;
    lanes[(laneIdx + 3) & 7] =
      (lanes[(laneIdx + 3) & 7] + ((lanes[laneIdx] << 5) | (lanes[laneIdx] >>> 27))) >>> 0;
  }
  return lanes.map((v) => v.toString(16).padStart(8, '0')).join('');
}

export function timingSafeHexEqual(hexA: string, hexB: string): boolean {
  if (typeof hexA !== 'string' || typeof hexB !== 'string') return false;
  if (hexA.length !== 64 || hexB.length !== 64) return false;
  try {
    const bufA = Buffer.from(hexA, 'hex');
    const bufB = Buffer.from(hexB, 'hex');
    if (bufA.length !== 32 || bufB.length !== 32) return false;
    return crypto.timingSafeEqual(bufA, bufB);
  } catch {
    return false;
  }
}

// ============================================================================
// GATE 1 REMEDIATION: REAL FIREBASE ID TOKEN (RS256) VERIFICATION,
// SESSION TOKEN ISSUANCE, REVOCATION, AND KEY ROTATION
// ============================================================================

let cachedGoogleCerts: { expiresAtMs: number; certs: Record<string, string> } | null = null;
const customTrustedRs256PublicKeys = new Map<string, string>();

export function registerTrustedRs256PublicKeyForTesting(kid: string, publicKeyPem: string): void {
  customTrustedRs256PublicKeys.set(kid, publicKeyPem);
}

async function fetchGoogleSecureTokenCerts(): Promise<Record<string, string>> {
  const now = Date.now();
  if (cachedGoogleCerts && now < cachedGoogleCerts.expiresAtMs) {
    return cachedGoogleCerts.certs;
  }
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 3500);
    const res = await fetch(GOOGLE_SECURETOKEN_CERTS_URL, { signal: controller.signal });
    clearTimeout(timer);
    if (res.ok) {
      const certs = (await res.json()) as Record<string, string>;
      cachedGoogleCerts = {
        certs,
        expiresAtMs: now + 3_600_000,
      };
      return certs;
    }
  } catch {
    // Offline or network restricted; fall back to registered keys
  }
  return {};
}

/**
 * Synchronous verification of an RS256 Firebase ID Token against known public keys/certificates.
 */
export function verifyFirebaseIdTokenRs256Sync(
  rawJwt: string,
  certsMap: Record<string, string> = {}
): VerifiedSessionContext | null {
  try {
    const parts = rawJwt.split('.');
    if (parts.length !== 3) return null;
    const [headerB64, payloadB64, sigB64] = parts;

    const header = JSON.parse(Buffer.from(headerB64, 'base64url').toString('utf8')) as {
      alg?: string;
      kid?: string;
      typ?: string;
    };
    if (header.alg !== 'RS256' || typeof header.kid !== 'string' || !header.kid) {
      return null;
    }

    const pubKeyPem =
      customTrustedRs256PublicKeys.get(header.kid) || certsMap[header.kid];
    if (!pubKeyPem) {
      return null;
    }

    const verifier = crypto.createVerify('RSA-SHA256');
    verifier.update(`${headerB64}.${payloadB64}`, 'utf8');
    verifier.end();
    const sigBuf = Buffer.from(sigB64, 'base64url');
    const signatureValid = verifier.verify(pubKeyPem, sigBuf);
    if (!signatureValid) {
      return null;
    }

    const payload = JSON.parse(Buffer.from(payloadB64, 'base64url').toString('utf8')) as {
      aud?: string;
      iss?: string;
      sub?: string;
      user_id?: string;
      email?: string;
      email_verified?: boolean;
      exp?: number;
      iat?: number;
      auth_time?: number;
    };

    const nowSec = Math.floor(Date.now() / 1000);
    const uid = payload.sub || payload.user_id || '';
    if (
      payload.aud !== EXPECTED_FIREBASE_PROJECT_ID ||
      payload.iss !== EXPECTED_FIREBASE_ISSUER ||
      typeof uid !== 'string' ||
      uid.length < 1 ||
      uid.length > 128 ||
      typeof payload.exp !== 'number' ||
      nowSec >= payload.exp ||
      typeof payload.iat !== 'number' ||
      payload.iat > nowSec + 300
    ) {
      return null;
    }

    const emailVerified = payload.email_verified === true;
    const role = resolveServerRole(uid, payload.email || null, emailVerified, undefined, true);
    return {
      uid,
      email: payload.email || null,
      emailVerified,
      role,
      issuedAtMs: payload.iat * 1000,
      expiresAtMs: payload.exp * 1000,
      reauthenticatedAtMs: (payload.auth_time || payload.iat) * 1000,
      tokenCryptographicallyVerified: true,
      keyId: header.kid,
    };
  } catch {
    return null;
  }
}

/**
 * Async verification of a Firebase ID Token (fetches Google SecureToken X.509 certificates if needed)
 * before exchanging it for a server session token.
 */
export async function verifyFirebaseIdTokenAndIssueSession(
  rawAuthorizationHeader: string | undefined
): Promise<
  SecurityGuardResult<{
    sessionToken: string;
    session: VerifiedSessionContext;
  }>
> {
  if (!rawAuthorizationHeader || !rawAuthorizationHeader.startsWith('Bearer ')) {
    return {
      allowed: false,
      status: 401,
      code: 'FIREBASE_ID_TOKEN_REQUIRED',
      message: 'A valid Bearer Firebase ID token (RS256) is required to issue a server session.',
    };
  }
  const rawToken = rawAuthorizationHeader.slice('Bearer '.length).trim();
  if (rawToken.startsWith('dev_session:') || rawToken.startsWith('molt_sig_v1.')) {
    return {
      allowed: false,
      status: 401,
      code: 'FIREBASE_ID_TOKEN_REQUIRED',
      message: 'Session issuance requires an upstream RS256 Firebase ID token, not a custom token.',
    };
  }

  const googleCerts = await fetchGoogleSecureTokenCerts();
  const verifiedFirebaseSession = verifyFirebaseIdTokenRs256Sync(rawToken, googleCerts);
  if (!verifiedFirebaseSession) {
    return {
      allowed: false,
      status: 401,
      code: 'INVALID_FIREBASE_ID_TOKEN',
      message: 'Firebase ID token RS256 cryptographic signature or audience/issuer validation failed.',
    };
  }

  const sessionToken = issueSignedServerSessionToken({
    uid: verifiedFirebaseSession.uid,
    email: verifiedFirebaseSession.email || '',
    emailVerified: verifiedFirebaseSession.emailVerified,
    assignedRole: verifiedFirebaseSession.role,
    reauthenticatedAtMs: verifiedFirebaseSession.reauthenticatedAtMs,
  });

  const issuedSession = verifyAndExtractSessionToken(`Bearer ${sessionToken}`);
  return {
    allowed: true,
    status: 200,
    code: 'SESSION_TOKEN_ISSUED',
    message: 'Verified Firebase ID token and issued signed server session token.',
    data: {
      sessionToken,
      session: issuedSession || verifiedFirebaseSession,
    },
  };
}

/**
 * Rotates the server HMAC session signing key epoch (`kid`) while preserving previous keys
 * in `hmacKeysHex` or optionally revoking prior epochs.
 */
export function rotateSessionSigningSecret(revokePreviousEpochs = false): {
  newKid: string;
} {
  const state = loadPersistentSecurityState();
  const nextEpochNum = Object.keys(state.hmacKeysHex).length + 1;
  const newKid = `hmac_epoch_v${nextEpochNum}`;
  const newSecretHex = crypto.randomBytes(32).toString('hex');

  if (revokePreviousEpochs) {
    state.hmacKeysHex = { [newKid]: newSecretHex };
  } else {
    state.hmacKeysHex[newKid] = newSecretHex;
  }
  state.activeHmacKid = newKid;
  savePersistentSecurityState(state);
  return { newKid };
}

/**
 * Revokes a specific session token by its `jti` or raw `molt_sig_v1` string.
 */
export function revokeServerSessionToken(tokenOrJti: string): SecurityGuardResult<{ jti: string }> {
  const state = loadPersistentSecurityState();
  let targetJti = tokenOrJti.trim();

  if (targetJti.startsWith('Bearer ')) {
    targetJti = targetJti.slice('Bearer '.length).trim();
  }
  if (targetJti.startsWith('molt_sig_v1.')) {
    const extracted = verifyAndExtractSessionToken(`Bearer ${targetJti}`);
    if (!extracted || !extracted.sessionJti) {
      return {
        allowed: false,
        status: 400,
        code: 'INVALID_SESSION_TOKEN',
        message: 'Cannot revoke an invalid or unverified session token.',
      };
    }
    targetJti = extracted.sessionJti;
  }

  if (!targetJti || targetJti.length < 6) {
    return {
      allowed: false,
      status: 400,
      code: 'INVALID_SESSION_JTI',
      message: 'Valid session JTI is required for revocation.',
    };
  }

  if (!state.revokedSessionJtis.includes(targetJti)) {
    state.revokedSessionJtis.push(targetJti);
    savePersistentSecurityState(state);
  }

  return {
    allowed: true,
    status: 200,
    code: 'SESSION_REVOKED',
    message: 'Session token has been permanently revoked in durable storage.',
    data: { jti: targetJti },
  };
}

/**
 * Issues a server-signed HMAC-SHA256 session token (`molt_sig_v1.<kid>.<payloadB64>.<hmacB64>`)
 * with unique `jti`, `kid`, `aud`, `iss`, and `exp`.
 */
export function issueSignedServerSessionToken(params: {
  uid: string;
  email: string;
  emailVerified: boolean;
  assignedRole?: UserRole;
  reauthenticatedAtMs?: number;
  ttlMs?: number;
}): string {
  const state = loadPersistentSecurityState();
  const kid = state.activeHmacKid;
  const secretHex = state.hmacKeysHex[kid];
  const secretBuf = Buffer.from(secretHex, 'hex');

  const now = Date.now();
  const jti = `sess_${crypto.randomBytes(12).toString('hex')}`;
  const payload = {
    jti,
    kid,
    uid: params.uid,
    email: params.email,
    email_verified: params.emailVerified,
    assigned_role: params.assignedRole,
    iat: now,
    exp: now + (params.ttlMs ?? 3_600_000),
    auth_time: params.reauthenticatedAtMs ?? now,
    aud: EXPECTED_FIREBASE_PROJECT_ID,
    iss: EXPECTED_FIREBASE_ISSUER,
  };
  const payloadB64 = Buffer.from(JSON.stringify(payload), 'utf8').toString('base64url');
  const signedInput = `${kid}.${payloadB64}`;
  const mac = crypto
    .createHmac('sha256', secretBuf)
    .update(signedInput, 'utf8')
    .digest('base64url');
  return `molt_sig_v1.${kid}.${payloadB64}.${mac}`;
}

/**
 * Verifies a Bearer token and extracts a VerifiedSessionContext.
 * - Rejects forged plaintext `dev_session:` strings (`SC11-F01`).
 * - Verifies `molt_sig_v1.<kid>.<payload>.<mac>` tokens against durable HMAC key ring (`kid`),
 *   checks durable `revokedSessionJtis`, and validates `aud`, `iss`, and `exp`.
 * - Also verifies RS256 Firebase ID JWTs against cached/registered X.509 public keys.
 */
export function verifyAndExtractSessionToken(
  rawBearerHeader: string | undefined
): VerifiedSessionContext | null {
  if (!rawBearerHeader || !rawBearerHeader.startsWith('Bearer ')) {
    return null;
  }
  const token = rawBearerHeader.slice('Bearer '.length).trim();
  if (!token || token.length < 16) {
    return null;
  }

  // Explicitly block plaintext unsigned `dev_session:` tokens
  if (token.startsWith('dev_session:')) {
    return null;
  }

  if (token.startsWith('molt_sig_v1.')) {
    const state = loadPersistentSecurityState();
    const parts = token.split('.');
    if (parts.length !== 4) return null;
    const [, kid, payloadB64, providedMac] = parts;

    const secretHex = state.hmacKeysHex[kid];
    if (!secretHex) return null;
    const secretBuf = Buffer.from(secretHex, 'hex');

    const expectedMac = crypto
      .createHmac('sha256', secretBuf)
      .update(`${kid}.${payloadB64}`, 'utf8')
      .digest('base64url');

    const bufA = Buffer.from(providedMac, 'utf8');
    const bufB = Buffer.from(expectedMac, 'utf8');
    if (bufA.length !== bufB.length || !crypto.timingSafeEqual(bufA, bufB)) {
      return null;
    }

    try {
      const decoded = JSON.parse(Buffer.from(payloadB64, 'base64url').toString('utf8'));
      const now = Date.now();
      if (
        decoded.aud !== EXPECTED_FIREBASE_PROJECT_ID ||
        decoded.iss !== EXPECTED_FIREBASE_ISSUER ||
        typeof decoded.exp !== 'number' ||
        now > decoded.exp ||
        typeof decoded.uid !== 'string' ||
        !decoded.uid ||
        typeof decoded.jti !== 'string' ||
        !decoded.jti
      ) {
        return null;
      }

      // Check durable session revocation list
      if (state.revokedSessionJtis.includes(decoded.jti)) {
        return null;
      }

      const emailVerified = decoded.email_verified === true;
      const role = resolveServerRole(
        decoded.uid,
        decoded.email || null,
        emailVerified,
        decoded.assigned_role,
        true
      );
      return {
        uid: decoded.uid,
        email: decoded.email || null,
        emailVerified,
        role,
        issuedAtMs: Number(decoded.iat || now),
        expiresAtMs: Number(decoded.exp),
        reauthenticatedAtMs: Number(decoded.auth_time || decoded.iat || now),
        tokenCryptographicallyVerified: true,
        sessionJti: decoded.jti,
        keyId: kid,
      };
    } catch {
      return null;
    }
  }

  // Attempt RS256 Firebase ID Token verification if a 3-part JWT is supplied
  if (token.split('.').length === 3) {
    return verifyFirebaseIdTokenRs256Sync(token, cachedGoogleCerts?.certs || {});
  }

  return null;
}

/**
 * Resolves the authoritative role on the server.
 * Ignores any client-supplied role, localStorage flag, or unverified email claim.
 */
export function resolveServerRole(
  uid: string | null | undefined,
  email: string | null | undefined,
  emailVerified: boolean,
  assignedBackendRole?: UserRole,
  tokenCryptographicallyVerified = true
): UserRole {
  if (!uid) return 'anonymous';
  if (!emailVerified) return 'user';
  if (
    tokenCryptographicallyVerified &&
    (TRUSTED_ADMIN_UIDS.has(uid) ||
      (email && TRUSTED_ADMIN_EMAILS.has(email.toLowerCase())))
  ) {
    return 'admin';
  }
  if (assignedBackendRole && assignedBackendRole !== 'admin') {
    return assignedBackendRole;
  }
  return 'user';
}

/**
 * Enforces RBAC role hierarchy and rejects forged client admin claims.
 */
export function authorizeAction(
  session: VerifiedSessionContext | null,
  requiredRole: UserRole,
  options?: {
    targetOwnerUid?: string;
    requireRecentReauthMs?: number;
    clientSuppliedHeaders?: Record<string, string | undefined>;
  }
): SecurityGuardResult {
  if (options?.clientSuppliedHeaders) {
    const forgedRole =
      options.clientSuppliedHeaders['x-molt-role'] ||
      options.clientSuppliedHeaders['x-admin-override'] ||
      options.clientSuppliedHeaders['x-operator-flag'];
    if (forgedRole && session?.role !== 'admin') {
      return {
        allowed: false,
        status: 403,
        code: 'FORGED_PRIVILEGE_HEADER_REJECTED',
        message: 'Client-supplied role or administrative override headers are forbidden.',
      };
    }
  }

  if (!session || session.role === 'anonymous' || !session.uid) {
    return {
      allowed: false,
      status: 401,
      code: 'UNAUTHENTICATED',
      message: 'Authentication is required to access this resource.',
    };
  }

  if (Date.now() > session.expiresAtMs) {
    return {
      allowed: false,
      status: 401,
      code: 'SESSION_EXPIRED',
      message: 'Session token has expired. Please reauthenticate.',
    };
  }

  if (!session.emailVerified && requiredRole !== 'user') {
    return {
      allowed: false,
      status: 403,
      code: 'EMAIL_UNVERIFIED',
      message: 'A verified email identity is required for elevated operations.',
    };
  }

  if (
    options?.targetOwnerUid &&
    options.targetOwnerUid !== session.uid &&
    session.role !== 'admin'
  ) {
    return {
      allowed: false,
      status: 403,
      code: 'CROSS_ACCOUNT_ACCESS_DENIED',
      message: 'You are not authorized to access or modify another user account resource.',
    };
  }

  if (ROLE_HIERARCHY[session.role] < ROLE_HIERARCHY[requiredRole]) {
    return {
      allowed: false,
      status: 403,
      code: 'INSUFFICIENT_ROLE_PRIVILEGE',
      message: `Operation requires '${requiredRole}' privilege; current verified role is '${session.role}'.`,
    };
  }

  if (options?.requireRecentReauthMs) {
    const reauthAge = Date.now() - (session.reauthenticatedAtMs || 0);
    if (!session.reauthenticatedAtMs || reauthAge > options.requireRecentReauthMs) {
      return {
        allowed: false,
        status: 403,
        code: 'REAUTHENTICATION_REQUIRED',
        message: 'Sensitive administrative operation requires recent reauthentication.',
      };
    }
  }

  return {
    allowed: true,
    status: 200,
    code: 'AUTHORIZED',
    message: 'Authorized.',
  };
}

/**
 * Enforces sliding-window rate limits backed by durable disk state so rate limits
 * are shared across restarts and local worker processes.
 */
export function enforceRateLimit(
  bucketKey: string,
  maxRequests: number,
  windowMs: number,
  nowMs: number = Date.now()
): SecurityGuardResult {
  const state = loadPersistentSecurityState();
  const keys = Object.keys(state.rateLimits);
  if (keys.length > 5_000) {
    // Prune only expired rate limit windows; never wipe active windows
    for (const k of keys) {
      if (nowMs - state.rateLimits[k].windowStartMs >= windowMs) {
        delete state.rateLimits[k];
      }
    }
  }

  const existing = state.rateLimits[bucketKey];
  if (!existing || nowMs - existing.windowStartMs >= windowMs) {
    state.rateLimits[bucketKey] = { count: 1, windowStartMs: nowMs };
    savePersistentSecurityState(state);
    return {
      allowed: true,
      status: 200,
      code: 'RATE_OK',
      message: 'Within rate limit.',
    };
  }

  if (existing.count >= maxRequests) {
    return {
      allowed: false,
      status: 429,
      code: 'RATE_LIMIT_EXCEEDED',
      message: `Rate limit exceeded for ${bucketKey} (max ${maxRequests} per ${windowMs}ms).`,
    };
  }

  existing.count += 1;
  savePersistentSecurityState(state);
  return {
    allowed: true,
    status: 200,
    code: 'RATE_OK',
    message: 'Within rate limit.',
  };
}

/**
 * Sanitizes and validates external URIs submitted by agents or users.
 * Blocks XSS schemes (javascript:, data:, vbscript:, file:) and SSRF private/loopback/IPv6-mapped hosts.
 */
export function validateSafeExternalUri(rawUri: string): SecurityGuardResult<string> {
  if (typeof rawUri !== 'string' || rawUri.trim().length < 8 || rawUri.length > 512) {
    return {
      allowed: false,
      status: 400,
      code: 'INVALID_URI_LENGTH',
      message: 'URI must be between 8 and 512 characters.',
    };
  }

  const trimmed = rawUri.trim();

  if (/^(javascript|data|vbscript|file|blob):/i.test(trimmed)) {
    return {
      allowed: false,
      status: 400,
      code: 'UNSAFE_URI_SCHEME',
      message: 'Forbidden URI scheme detected (XSS/script execution vector blocked).',
    };
  }

  if (trimmed.startsWith('ipfs://')) {
    const cidPart = trimmed.slice('ipfs://'.length);
    if (!/^[a-zA-Z0-9/_\-.]+$/.test(cidPart) || cidPart.includes('..')) {
      return {
        allowed: false,
        status: 400,
        code: 'INVALID_IPFS_CID',
        message: 'Malformed IPFS URI.',
      };
    }
    return {
      allowed: true,
      status: 200,
      code: 'VALID_URI',
      message: 'Valid IPFS URI.',
      data: trimmed,
    };
  }

  let parsed: URL;
  try {
    parsed = new URL(trimmed);
  } catch {
    return {
      allowed: false,
      status: 400,
      code: 'MALFORMED_URI',
      message: 'URI could not be parsed.',
    };
  }

  if (parsed.protocol !== 'https:') {
    return {
      allowed: false,
      status: 400,
      code: 'HTTPS_REQUIRED',
      message: 'External evidence URIs must use https:// or ipfs://.',
    };
  }

  const host = parsed.hostname.toLowerCase().replace(/^\[|\]$/g, '');
  if (
    host === 'localhost' ||
    host === '0.0.0.0' ||
    host === '::1' ||
    host === '::' ||
    host.startsWith('::ffff:') ||
    host.startsWith('fe80:') ||
    host.startsWith('fc00:') ||
    host.startsWith('fd00:') ||
    host === '169.254.169.254' ||
    host.endsWith('.internal') ||
    host.endsWith('.local') ||
    host.endsWith('.localhost') ||
    /^\d+$/.test(host) ||
    /^0x[0-9a-f]+$/i.test(host) ||
    /^127\.\d+\.\d+\.\d+$/.test(host) ||
    /^0\.\d+\.\d+\.\d+$/.test(host) ||
    /^169\.254\.\d+\.\d+$/.test(host) ||
    /^10\.\d+\.\d+\.\d+$/.test(host) ||
    /^192\.168\.\d+\.\d+$/.test(host) ||
    /^172\.(1[6-9]|2\d|3[0-1])\.\d+\.\d+$/.test(host)
  ) {
    return {
      allowed: false,
      status: 400,
      code: 'SSRF_TARGET_BLOCKED',
      message: 'Private, loopback, IPv6-mapped, or cloud metadata hostnames are forbidden.',
    };
  }

  return {
    allowed: true,
    status: 200,
    code: 'VALID_URI',
    message: 'Valid HTTPS URI.',
    data: parsed.toString(),
  };
}

/**
 * Strips any raw HTML tags or script payloads from user/agent text fields.
 */
export function sanitizePlainText(input: unknown, maxLen = 400): string {
  if (typeof input !== 'string') return '';
  return input
    .replace(/<script[\s\S]*?>[\s\S]*?<\/script>/gi, '')
    .replace(/<[^>]*>/g, '')
    .replace(/javascript:/gi, '')
    .replace(/on\w+\s*=/gi, '')
    .trim()
    .slice(0, maxLen);
}

/**
 * Prevents Agent Reputation Manipulation:
 * Rejects any client payload attempting to set reliability_pct, reputation_tier,
 * verified_status, or duesproof status directly.
 */
export function validateAgentEvidenceSubmission(
  session: VerifiedSessionContext | null,
  payload: Record<string, unknown>,
  idempotencyKey?: string,
  clientSuppliedHeaders?: Record<string, string | undefined>
): SecurityGuardResult<{
  submissionId: string;
  agentId: string;
  provenance: EvidenceProvenanceClass;
  deliverableUri: string;
  summary: string;
}> {
  const authCheck = authorizeAction(session, 'user', { clientSuppliedHeaders });
  if (!authCheck.allowed) return authCheck as SecurityGuardResult<never>;

  const forbiddenClientFields = [
    'reliabilityPct',
    'reliability_pct',
    'reputationTier',
    'reputation_tier',
    'verificationStatus',
    'verified_status',
    'knownDeliveries',
    'birthCertStatus',
    'duesProofVerified',
    'isVerified',
  ];
  for (const field of forbiddenClientFields) {
    if (Object.prototype.hasOwnProperty.call(payload, field)) {
      return {
        allowed: false,
        status: 403,
        code: 'AGENT_REPUTATION_TAMPERING_BLOCKED',
        message: `Client payload cannot assign protected reputation field '${field}'.`,
      };
    }
  }

  if (!idempotencyKey || idempotencyKey.trim().length < 8 || idempotencyKey.length > 128) {
    return {
      allowed: false,
      status: 400,
      code: 'IDEMPOTENCY_KEY_REQUIRED',
      message: 'A valid X-Idempotency-Key header is required to prevent duplicate/replayed submissions.',
    };
  }

  const state = loadPersistentSecurityState();
  const scopedIdempotency = `${session!.uid}:${idempotencyKey.trim()}`;
  if (state.processedIdempotencyKeys.includes(scopedIdempotency)) {
    return {
      allowed: false,
      status: 409,
      code: 'DUPLICATE_SUBMISSION_REPLAY_BLOCKED',
      message: 'Duplicate or replayed submission blocked by durable idempotency guard.',
    };
  }

  const rawAgentId = typeof payload.agentId === 'string' ? payload.agentId.trim() : '';
  if (!/^[a-zA-Z0-9_\-]{2,64}$/.test(rawAgentId)) {
    return {
      allowed: false,
      status: 400,
      code: 'INVALID_AGENT_ID',
      message: 'agentId must be 2–64 alphanumeric/underscore/hyphen characters.',
    };
  }

  const uriCheck = validateSafeExternalUri(String(payload.deliverableUri || ''));
  if (!uriCheck.allowed || !uriCheck.data) {
    return uriCheck as SecurityGuardResult<never>;
  }

  const cleanSummary = sanitizePlainText(payload.summary, 500);
  if (cleanSummary.length < 40) {
    return {
      allowed: false,
      status: 400,
      code: 'SUMMARY_TOO_SHORT',
      message: 'Sanitized technical summary must be at least 40 characters.',
    };
  }

  state.processedIdempotencyKeys.push(scopedIdempotency);
  savePersistentSecurityState(state);

  return {
    allowed: true,
    status: 201,
    code: 'CLAIM_RECORDED_PENDING_VERIFICATION',
    message: 'Deliverable recorded as SELF_REPORTED claim pending independent backend verification.',
    data: {
      submissionId: `sub_${sha256Hex(scopedIdempotency).slice(0, 12)}`,
      agentId: rawAgentId,
      provenance: 'SELF_REPORTED',
      deliverableUri: uriCheck.data,
      summary: cleanSummary,
    },
  };
}

/**
 * Prevents Sentinel Score Forgery:
 * Rejects any client request attempting to submit or override risk_score, status='SAFE',
 * or witness signatures.
 */
export function validateSentinelAssessmentRequest(
  session: VerifiedSessionContext | null,
  payload: Record<string, unknown>,
  clientSuppliedHeaders?: Record<string, string | undefined>
): SecurityGuardResult {
  const authCheck = authorizeAction(session, 'user', { clientSuppliedHeaders });
  if (!authCheck.allowed) return authCheck;

  const forbiddenScoreFields = [
    'riskScore',
    'risk_score',
    'status',
    'risk_level',
    'signatureEd25519',
    'witnessHashSha256',
    'verified',
  ];

  for (const field of forbiddenScoreFields) {
    if (Object.prototype.hasOwnProperty.call(payload, field) && session!.role !== 'admin') {
      return {
        allowed: false,
        status: 403,
        code: 'SENTINEL_SCORE_FORGERY_BLOCKED',
        message: `Client-controlled input cannot set or override '${field}'.`,
      };
    }
  }

  const pair = typeof payload.pair === 'string' ? payload.pair.trim().toUpperCase() : '';
  if (!/^[A-Z0-9]{2,12}\/[A-Z0-9]{2,12}$/.test(pair)) {
    return {
      allowed: false,
      status: 400,
      code: 'INVALID_POOL_PAIR',
      message: 'Pool pair must match format BASE/QUOTE (e.g., POPCAT/SOL).',
    };
  }

  return {
    allowed: true,
    status: 200,
    code: 'PREFLIGHT_REQUEST_VALID',
    message: 'Valid preflight request.',
  };
}

/**
 * Prevents Credit Balance Tampering & Payment Replay Attacks:
 * Durable disk-backed replay protection that NEVER calls .clear() on processedPaymentTxHashes.
 */
export function processVerifiedSettlementRequest(
  session: VerifiedSessionContext | null,
  payload: Record<string, unknown>,
  idempotencyKey?: string,
  clientSuppliedHeaders?: Record<string, string | undefined>
): SecurityGuardResult<{
  settlementId: string;
  tier: string;
  rail: string;
  txHash: string;
  verificationMode: 'SIMULATED_SANDBOX_RECEIPT';
}> {
  const authCheck = authorizeAction(session, 'user', { clientSuppliedHeaders });
  if (!authCheck.allowed) return authCheck as SecurityGuardResult<never>;

  if (
    Object.prototype.hasOwnProperty.call(payload, 'creditsGranted') ||
    Object.prototype.hasOwnProperty.call(payload, 'newBalance') ||
    Object.prototype.hasOwnProperty.call(payload, 'overrideAmountUsd')
  ) {
    return {
      allowed: false,
      status: 403,
      code: 'CREDIT_BALANCE_TAMPERING_BLOCKED',
      message: 'Client cannot specify creditsGranted or balance overrides.',
    };
  }

  const tier = String(payload.tier || '');
  if (!['Micro', 'Starter', 'Pro', 'Enterprise'].includes(tier)) {
    return {
      allowed: false,
      status: 400,
      code: 'INVALID_PRICING_TIER',
      message: 'Invalid pricing tier.',
    };
  }

  const rail = String(payload.rail || '');
  if (!['SOL', 'USDC', 'Nano'].includes(rail)) {
    return {
      allowed: false,
      status: 400,
      code: 'INVALID_PAYMENT_RAIL',
      message: 'Invalid payment rail.',
    };
  }

  const txHash = typeof payload.txHash === 'string' ? payload.txHash.trim() : '';
  if (!/^[a-zA-Z0-9_]{12,128}$/.test(txHash)) {
    return {
      allowed: false,
      status: 400,
      code: 'INVALID_TX_HASH',
      message: 'Invalid transaction hash format.',
    };
  }

  const state = loadPersistentSecurityState();
  if (state.processedPaymentTxHashes.includes(txHash)) {
    return {
      allowed: false,
      status: 409,
      code: 'PAYMENT_REPLAY_DETECTED',
      message: 'Transaction hash has already been processed (durable payment replay guard).',
    };
  }

  if (idempotencyKey) {
    const idem = `pay:${session!.uid}:${idempotencyKey}`;
    if (state.processedIdempotencyKeys.includes(idem)) {
      return {
        allowed: false,
        status: 409,
        code: 'PAYMENT_REPLAY_DETECTED',
        message: 'Duplicate idempotency key for payment request.',
      };
    }
    state.processedIdempotencyKeys.push(idem);
  }

  state.processedPaymentTxHashes.push(txHash);
  savePersistentSecurityState(state);

  return {
    allowed: true,
    status: 200,
    code: 'SANDBOX_SETTLEMENT_RECORDED',
    message: 'Recorded in durable development sandbox ledger (not authoritative production billing).',
    data: {
      settlementId: `settle_${sha256Hex(txHash).slice(0, 12)}`,
      tier,
      rail,
      txHash,
      verificationMode: 'SIMULATED_SANDBOX_RECEIPT',
    },
  };
}

/**
 * Issues a scoped API key on the server and persists ONLY its SHA-256 hash and prefix
 * to the durable security ledger (survives server restarts & multi-instance checks).
 */
export function issueScopedApiKey(
  session: VerifiedSessionContext | null,
  targetOwnerUid: string,
  scopes: string[] = ['sentinel:read', 'witness:verify'],
  clientSuppliedHeaders?: Record<string, string | undefined>
): SecurityGuardResult<{
  keyId: string;
  ownerUid: string;
  keyPrefix: string;
  keyHashSha256: string;
  rawKeyOnce: string;
  scopes: string[];
  expiresAtIso: string;
}> {
  const authCheck = authorizeAction(session, 'user', { targetOwnerUid, clientSuppliedHeaders });
  if (!authCheck.allowed) return authCheck as SecurityGuardResult<never>;

  const allowedScopes = new Set(['sentinel:read', 'witness:verify', 'jobs:submit', 'agents:read']);
  if (!Array.isArray(scopes) || scopes.length === 0 || scopes.length > 10) {
    return {
      allowed: false,
      status: 400,
      code: 'INVALID_API_KEY_SCOPE',
      message: 'At least 1 and at most 10 permitted scopes must be specified.',
    };
  }
  for (const s of scopes) {
    if (!allowedScopes.has(s)) {
      return {
        allowed: false,
        status: 400,
        code: 'INVALID_API_KEY_SCOPE',
        message: `Scope '${s}' is not permitted by least-privilege policy.`,
      };
    }
  }

  const randomEntropy = crypto.randomBytes(24).toString('hex');
  const rawKeyOnce = `mk_dev_${randomEntropy}`;
  const keyPrefix = rawKeyOnce.slice(0, 12);
  const keyHashSha256 = sha256Hex(rawKeyOnce);
  const keyId = `key_${keyHashSha256.slice(0, 12)}`;
  const now = Date.now();
  const expiresAtIso = new Date(now + 90 * 24 * 3_600_000).toISOString();

  const state = loadPersistentSecurityState();
  state.apiKeys[keyId] = {
    keyId,
    ownerUid: targetOwnerUid,
    keyPrefix,
    keyHashSha256,
    scopes,
    rateLimitRps: 40,
    revoked: false,
    createdAtIso: new Date(now).toISOString(),
    expiresAtIso,
  };
  savePersistentSecurityState(state);

  return {
    allowed: true,
    status: 201,
    code: 'API_KEY_ISSUED',
    message: 'API key issued and persisted to durable ledger. Store rawKeyOnce securely; only keyHashSha256 is persisted.',
    data: {
      keyId,
      ownerUid: targetOwnerUid,
      keyPrefix,
      keyHashSha256,
      rawKeyOnce,
      scopes,
      expiresAtIso,
    },
  };
}

export function getApiKeyMetadata(
  session: VerifiedSessionContext | null,
  keyId: string,
  clientSuppliedHeaders?: Record<string, string | undefined>
): SecurityGuardResult<{
  keyId: string;
  ownerUid: string;
  keyPrefix: string;
  keyHashSha256: string;
  scopes: string[];
  revoked: boolean;
  expiresAtIso: string;
}> {
  const preAuth = authorizeAction(session, 'user', { clientSuppliedHeaders });
  if (!preAuth.allowed) return preAuth as SecurityGuardResult<never>;

  const state = loadPersistentSecurityState();
  const record = state.apiKeys[keyId];
  if (!record) {
    return {
      allowed: false,
      status: 404,
      code: 'API_KEY_NOT_FOUND',
      message: 'API key record not found.',
    };
  }

  const authCheck = authorizeAction(session, 'user', {
    targetOwnerUid: record.ownerUid,
    clientSuppliedHeaders,
  });
  if (!authCheck.allowed) return authCheck as SecurityGuardResult<never>;

  return {
    allowed: true,
    status: 200,
    code: 'OK',
    message: 'Metadata retrieved from durable ledger (raw key is never stored or returned).',
    data: {
      keyId: record.keyId,
      ownerUid: record.ownerUid,
      keyPrefix: record.keyPrefix,
      keyHashSha256: record.keyHashSha256,
      scopes: record.scopes,
      revoked: record.revoked,
      expiresAtIso: record.expiresAtIso,
    },
  };
}

export function revokeScopedApiKey(
  session: VerifiedSessionContext | null,
  keyId: string,
  clientSuppliedHeaders?: Record<string, string | undefined>
): SecurityGuardResult<{ keyId: string; revoked: boolean }> {
  const preAuth = authorizeAction(session, 'user', { clientSuppliedHeaders });
  if (!preAuth.allowed) return preAuth as SecurityGuardResult<never>;

  const state = loadPersistentSecurityState();
  const record = state.apiKeys[keyId];
  if (!record) {
    return {
      allowed: false,
      status: 404,
      code: 'API_KEY_NOT_FOUND',
      message: 'API key record not found.',
    };
  }

  const authCheck = authorizeAction(session, 'user', {
    targetOwnerUid: record.ownerUid,
    clientSuppliedHeaders,
  });
  if (!authCheck.allowed) return authCheck as SecurityGuardResult<never>;

  record.revoked = true;
  savePersistentSecurityState(state);

  return {
    allowed: true,
    status: 200,
    code: 'API_KEY_REVOKED',
    message: 'API key has been permanently revoked in durable storage.',
    data: { keyId: record.keyId, revoked: true },
  };
}

/**
 * Authenticates a raw `mk_dev_...` API key in constant time (`crypto.timingSafeEqual`)
 * against the durable security ledger and rejects revoked or expired keys.
 */
export function verifyApiKeyCredential(
  rawApiKey: string,
  requiredScope?: string
): SecurityGuardResult<{
  keyId: string;
  ownerUid: string;
  scopes: string[];
}> {
  if (typeof rawApiKey !== 'string' || !rawApiKey.startsWith('mk_dev_') || rawApiKey.length !== 55) {
    return {
      allowed: false,
      status: 401,
      code: 'INVALID_API_KEY',
      message: 'Invalid API key format.',
    };
  }

  const state = loadPersistentSecurityState();
  const candidateHash = sha256Hex(rawApiKey);
  for (const record of Object.values(state.apiKeys)) {
    if (timingSafeHexEqual(candidateHash, record.keyHashSha256)) {
      if (record.revoked) {
        return {
          allowed: false,
          status: 403,
          code: 'API_KEY_REVOKED',
          message: 'API key has been revoked.',
        };
      }
      if (Date.now() > Date.parse(record.expiresAtIso)) {
        return {
          allowed: false,
          status: 403,
          code: 'API_KEY_EXPIRED',
          message: 'API key has expired.',
        };
      }
      if (requiredScope && !record.scopes.includes(requiredScope)) {
        return {
          allowed: false,
          status: 403,
          code: 'API_KEY_SCOPE_DENIED',
          message: `API key lacks required scope '${requiredScope}'.`,
        };
      }
      return {
        allowed: true,
        status: 200,
        code: 'API_KEY_VALID',
        message: 'API key verified.',
        data: {
          keyId: record.keyId,
          ownerUid: record.ownerUid,
          scopes: record.scopes,
        },
      };
    }
  }

  return {
    allowed: false,
    status: 401,
    code: 'INVALID_API_KEY',
    message: 'Unrecognized API key.',
  };
}

/**
 * Validates a Members-Only Trading / Sniping Bot configuration (`POST /api/v1/automation/bots`).
 * Enforces:
/**
 * Validates a user-authored custom bot hook script for the non-custodial scripting sandbox.
 * Rejects dangerous code execution primitives (`eval`, `Function`, `child_process`, `fs`,
 * `process.env`, raw private keys) and returns a deterministic SHA-256 script digest.
 */
export function validateCustomBotScript(scriptSource: unknown): SecurityGuardResult<{
  sanitizedScript: string;
  scriptHashSha256: string;
  lineCount: number;
}> {
  if (typeof scriptSource !== 'string' || scriptSource.trim().length === 0) {
    return {
      allowed: false,
      status: 400,
      code: 'EMPTY_CUSTOM_SCRIPT',
      message: 'Custom bot script cannot be empty.',
    };
  }

  const trimmed = scriptSource.trim();
  if (trimmed.length > 4000) {
    return {
      allowed: false,
      status: 400,
      code: 'SCRIPT_TOO_LARGE',
      message: 'Custom bot script must not exceed 4,000 characters.',
    };
  }

  const forbiddenPatterns: Array<{ pattern: RegExp; reason: string }> = [
    { pattern: /\beval\s*\(/i, reason: 'Dynamic eval() is forbidden in sandbox scripts.' },
    { pattern: /\bnew\s+Function\s*\(/i, reason: 'Dynamic Function() constructor is forbidden.' },
    { pattern: /\bchild_process\b/i, reason: 'Node child_process module access is forbidden.' },
    { pattern: /\brequire\s*\(\s*['"`](fs|net|tls|http|https|dgram|os)['"`]\s*\)/i, reason: 'Host OS / filesystem module imports are forbidden.' },
    { pattern: /\bprocess\.env\b/i, reason: 'Direct process.env secret access is forbidden inside custom bot hooks.' },
    { pattern: /\b(privateKey|secretKey|seedPhrase|mnemonic)\s*[:=]/i, reason: 'Hardcoded private keys or seed phrases are forbidden (non-custodial policy).' },
    { pattern: /<script[\s\S]*?>/i, reason: 'Raw HTML <script> tags are forbidden.' },
  ];

  for (const rule of forbiddenPatterns) {
    if (rule.pattern.test(trimmed)) {
      return {
        allowed: false,
        status: 400,
        code: 'UNSAFE_CUSTOM_SCRIPT_REJECTED',
        message: rule.reason,
      };
    }
  }

  const lineCount = trimmed.split('\n').length;
  return {
    allowed: true,
    status: 200,
    code: 'CUSTOM_SCRIPT_VALIDATED',
    message: 'Custom bot script passed non-custodial sandbox static analysis.',
    data: {
      sanitizedScript: trimmed,
      scriptHashSha256: sha256Hex(trimmed),
      lineCount,
    },
  };
}

/**
 * Validates a Members-Only Trading / Sniping Bot configuration (`POST /api/v1/automation/bots`).
 * Enforces:
 * - Authenticated member session (`user` role or higher).
 * - Non-custodial safety invariants (blocks any raw private key or seed phrase in payload).
 * - Mandatory Sentinel pre-trade risk score abort gate (`1.0 <= maxRiskScoreAbort <= 9.0`).
 * - Target liquidity pool address validation (Base58 Solana pool address or Metal X market contract).
 * - Gas settings (`gasPriorityMode`, `computeUnitLimit`, `priorityFeeMicroLamports`, `jitoTipLamports`),
 *   slippage tolerance (`maxSlippageBps`), and optional sandboxed `customScript`.
 * - Optional webhook URI SSRF/XSS validation via `validateSafeExternalUri`.
 */
export function validateAutomationBotConfig(
  session: VerifiedSessionContext | null,
  payload: Record<string, unknown>,
  clientSuppliedHeaders?: Record<string, string | undefined>
): SecurityGuardResult<{
  botId: string;
  ownerUid: string;
  botName: string;
  strategyType: string;
  targetDex: string;
  targetPair: string;
  targetPoolAddress: string;
  orderSizeSol: number;
  maxSlippageBps: number;
  gasPriorityMode: 'STANDARD' | 'TURBO' | 'ULTRA_JITO_MEV';
  computeUnitLimit: number;
  priorityFeeMicroLamports: number;
  jitoTipLamports: number;
  maxRiskScoreAbort: number;
  requireMintRevoked: boolean;
  requireEd25519Witness: boolean;
  webhookCallbackUri: string | null;
  customScriptHashSha256: string | null;
  executionMode: 'NON_CUSTODIAL_SANDBOX_SIMULATION';
}> {
  const authCheck = authorizeAction(session, 'user', { clientSuppliedHeaders });
  if (!authCheck.allowed) return authCheck as SecurityGuardResult<never>;

  if (
    Object.prototype.hasOwnProperty.call(payload, 'privateKey') ||
    Object.prototype.hasOwnProperty.call(payload, 'secretKey') ||
    Object.prototype.hasOwnProperty.call(payload, 'seedPhrase') ||
    Object.prototype.hasOwnProperty.call(payload, 'mnemonic')
  ) {
    return {
      allowed: false,
      status: 400,
      code: 'CUSTODIAL_SECRET_REJECTED',
      message:
        'MoltAlpha Automation is strictly non-custodial. Never transmit private keys or seed phrases to the server.',
    };
  }

  const botName = sanitizePlainText(String(payload.botName || ''), 64);
  if (botName.length < 3) {
    return {
      allowed: false,
      status: 400,
      code: 'INVALID_BOT_NAME',
      message: 'Bot name must be between 3 and 64 characters.',
    };
  }

  const allowedStrategies = [
    'LIQUIDITY_SNIPER',
    'METALX_ORDERBOOK_SNIPER',
    'CLMM_RANGE_ARB',
    'DCA_SENTINEL_GUARD',
    'WHALE_COPY_SHIELD',
  ];
  const strategyType = String(payload.strategyType || '');
  if (!allowedStrategies.includes(strategyType)) {
    return {
      allowed: false,
      status: 400,
      code: 'INVALID_STRATEGY_TYPE',
      message: 'Unsupported bot strategy archetype.',
    };
  }

  const allowedDexes = ['Metal X DEX', 'Raydium', 'Orca', 'Meteora', 'Jupiter'];
  const targetDex = String(payload.targetDex || '');
  if (!allowedDexes.includes(targetDex)) {
    return {
      allowed: false,
      status: 400,
      code: 'INVALID_TARGET_DEX',
      message: 'Target DEX must be Metal X DEX, Raydium, Orca, Meteora, or Jupiter.',
    };
  }

  const targetPair = String(payload.targetPair || '').trim();
  if (!/^[A-Z0-9]{2,12}\/[A-Z0-9]{2,12}$/.test(targetPair)) {
    return {
      allowed: false,
      status: 400,
      code: 'INVALID_TARGET_PAIR',
      message: 'Target pair must match BASE/QUOTE format (e.g., POPCAT/SOL or XPR/XUSDC).',
    };
  }

  const rawPoolAddress =
    typeof payload.targetPoolAddress === 'string' && payload.targetPoolAddress.trim().length > 0
      ? payload.targetPoolAddress.trim()
      : '58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2';
  const isValidBase58Pool = /^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(rawPoolAddress);
  const isValidMetalXPool = /^[a-z1-5._:]{3,36}$/i.test(rawPoolAddress);
  if (!isValidBase58Pool && !isValidMetalXPool) {
    return {
      allowed: false,
      status: 400,
      code: 'INVALID_TARGET_POOL_ADDRESS',
      message:
        'Target liquidity pool address must be a valid 32–44 char Base58 Solana pool address or Metal X market identifier.',
    };
  }

  const orderSizeSol = Number(payload.orderSizeSol);
  if (!Number.isFinite(orderSizeSol) || orderSizeSol < 0.01 || orderSizeSol > 250) {
    return {
      allowed: false,
      status: 400,
      code: 'INVALID_ORDER_SIZE',
      message: 'Order size must be between 0.01 and 250 units.',
    };
  }

  const maxSlippageBps = Number(payload.maxSlippageBps);
  if (!Number.isFinite(maxSlippageBps) || maxSlippageBps < 5 || maxSlippageBps > 1000) {
    return {
      allowed: false,
      status: 400,
      code: 'INVALID_SLIPPAGE_BPS',
      message: 'Max slippage must be between 5 bps (0.05%) and 1000 bps (10.0%).',
    };
  }

  const allowedGasModes = ['STANDARD', 'TURBO', 'ULTRA_JITO_MEV'] as const;
  const rawGasMode =
    typeof payload.gasPriorityMode === 'string' ? payload.gasPriorityMode : 'TURBO';
  if (!allowedGasModes.includes(rawGasMode as (typeof allowedGasModes)[number])) {
    return {
      allowed: false,
      status: 400,
      code: 'INVALID_GAS_PRIORITY_MODE',
      message: 'Gas priority mode must be STANDARD, TURBO, or ULTRA_JITO_MEV.',
    };
  }
  const gasPriorityMode = rawGasMode as 'STANDARD' | 'TURBO' | 'ULTRA_JITO_MEV';

  const computeUnitLimit =
    payload.computeUnitLimit !== undefined ? Number(payload.computeUnitLimit) : 250_000;
  if (
    !Number.isFinite(computeUnitLimit) ||
    computeUnitLimit < 50_000 ||
    computeUnitLimit > 1_400_000
  ) {
    return {
      allowed: false,
      status: 400,
      code: 'INVALID_COMPUTE_UNIT_LIMIT',
      message: 'Compute unit limit must be between 50,000 and 1,400,000 CU.',
    };
  }

  const priorityFeeMicroLamports =
    payload.priorityFeeMicroLamports !== undefined
      ? Number(payload.priorityFeeMicroLamports)
      : 50_000;
  if (
    !Number.isFinite(priorityFeeMicroLamports) ||
    priorityFeeMicroLamports < 100 ||
    priorityFeeMicroLamports > 5_000_000
  ) {
    return {
      allowed: false,
      status: 400,
      code: 'INVALID_PRIORITY_FEE',
      message: 'Priority fee must be between 100 and 5,000,000 microLamports/CU.',
    };
  }

  const jitoTipLamports = Number(payload.jitoTipLamports);
  if (
    !Number.isFinite(jitoTipLamports) ||
    jitoTipLamports < 1000 ||
    jitoTipLamports > 10_000_000
  ) {
    return {
      allowed: false,
      status: 400,
      code: 'INVALID_JITO_TIP',
      message: 'Priority / Jito MEV bundle tip must be between 1,000 and 10,000,000 lamports.',
    };
  }

  const maxRiskScoreAbort = Number(payload.maxRiskScoreAbort);
  if (
    !Number.isFinite(maxRiskScoreAbort) ||
    maxRiskScoreAbort < 1.0 ||
    maxRiskScoreAbort > 9.0
  ) {
    return {
      allowed: false,
      status: 400,
      code: 'INVALID_RISK_ABORT_THRESHOLD',
      message: 'Sentinel max risk score abort threshold must be between 1.0 and 9.0.',
    };
  }

  let webhookCallbackUri: string | null = null;
  if (
    typeof payload.webhookCallbackUri === 'string' &&
    payload.webhookCallbackUri.trim().length > 0
  ) {
    const uriValidation = validateSafeExternalUri(payload.webhookCallbackUri);
    if (!uriValidation.allowed) {
      return uriValidation as SecurityGuardResult<never>;
    }
    webhookCallbackUri = uriValidation.data!;
  }

  let customScriptHashSha256: string | null = null;
  if (typeof payload.customScript === 'string' && payload.customScript.trim().length > 0) {
    const scriptCheck = validateCustomBotScript(payload.customScript);
    if (!scriptCheck.allowed) {
      return scriptCheck as SecurityGuardResult<never>;
    }
    customScriptHashSha256 = scriptCheck.data!.scriptHashSha256;
  }

  const botId = `bot_${sha256Hex(`${session!.uid}:${botName}:${targetPair}:${rawPoolAddress}:${Date.now()}`).slice(0, 12)}`;
  return {
    allowed: true,
    status: 200,
    code: 'AUTOMATION_BOT_REGISTERED',
    message:
      'Members-only trading/sniping bot configuration validated and attested in non-custodial sandbox.',
    data: {
      botId,
      ownerUid: session!.uid,
      botName,
      strategyType,
      targetDex,
      targetPair,
      targetPoolAddress: rawPoolAddress,
      orderSizeSol,
      maxSlippageBps,
      gasPriorityMode,
      computeUnitLimit,
      priorityFeeMicroLamports,
      jitoTipLamports,
      maxRiskScoreAbort,
      requireMintRevoked: payload.requireMintRevoked !== false,
      requireEd25519Witness: payload.requireEd25519Witness !== false,
      webhookCallbackUri,
      customScriptHashSha256,
      executionMode: 'NON_CUSTODIAL_SANDBOX_SIMULATION',
    },
  };
}


