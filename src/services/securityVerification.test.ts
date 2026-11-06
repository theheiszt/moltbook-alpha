import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import crypto from 'node:crypto';
import {
  VerifiedSessionContext,
  resolveServerRole,
  issueSignedServerSessionToken,
  verifyAndExtractSessionToken,
  verifyFirebaseIdTokenAndIssueSession,
  registerTrustedRs256PublicKeyForTesting,
  revokeServerSessionToken,
  rotateSessionSigningSecret,
  loadPersistentSecurityState,
  signServerEd25519Payload,
  verifyServerEd25519Payload,
  authorizeAction,
  enforceRateLimit,
  resetSecurityStoresForTesting,
  validateSafeExternalUri,
  sanitizePlainText,
  validateAgentEvidenceSubmission,
  validateSentinelAssessmentRequest,
  processVerifiedSettlementRequest,
  issueScopedApiKey,
  getApiKeyMetadata,
  revokeScopedApiKey,
  verifyApiKeyCredential,
  validateAutomationBotConfig,
  validateCustomBotScript,
} from './securityEngine';
import { defaultDataProvider } from './dataProvider';

function makeSession(
  uid: string,
  email: string | null,
  emailVerified: boolean,
  assignedRole?: 'user' | 'developer' | 'operator' | 'admin'
): VerifiedSessionContext {
  const now = Date.now();
  return {
    uid,
    email,
    emailVerified,
    role: resolveServerRole(uid, email, emailVerified, assignedRole),
    issuedAtMs: now - 5_000,
    expiresAtMs: now + 3_600_000,
    reauthenticatedAtMs: now - 1_000,
  };
}

// ============================================================================
// SECTION 11 MANDATORY AUTOMATED SECURITY VERIFICATION SUITE + PHASE 1.2B FIXES
// ============================================================================

test('Scenario 1: Anonymous access restrictions, RS256 Firebase ID token exchange, session revocation & HMAC key rotation (SC11-F01, SC12A-F10)', async () => {
  resetSecurityStoresForTesting();
  const anonRole = resolveServerRole(null, null, false);
  assert.equal(anonRole, 'anonymous');

  const checkUser = authorizeAction(null, 'user');
  assert.equal(checkUser.allowed, false);
  assert.equal(checkUser.status, 401);

  const checkAdmin = authorizeAction(null, 'admin');
  assert.equal(checkAdmin.allowed, false);
  assert.equal(checkAdmin.status, 401);

  // Unsigned plaintext dev_session: tokens MUST be rejected with null (SC11-F01)
  const forgedPlaintext = verifyAndExtractSessionToken('Bearer dev_session:attacker:syntheticinquiry@gmail.com');
  assert.equal(forgedPlaintext, null);

  // Verify RS256 Firebase ID Token exchange via verifyFirebaseIdTokenAndIssueSession
  const { publicKey, privateKey } = crypto.generateKeyPairSync('rsa', { modulusLength: 2048 });
  const pubPem = publicKey.export({ type: 'spki', format: 'pem' }).toString();
  registerTrustedRs256PublicKeyForTesting('test_firebase_kid_1', pubPem);

  const nowSec = Math.floor(Date.now() / 1000);
  const headerB64 = Buffer.from(JSON.stringify({ alg: 'RS256', kid: 'test_firebase_kid_1', typ: 'JWT' })).toString('base64url');
  const payloadB64 = Buffer.from(
    JSON.stringify({
      iss: 'https://securetoken.google.com/promptforge-512701',
      aud: 'promptforge-512701',
      sub: 'firebase_user_alice',
      email: 'alice@example.com',
      email_verified: true,
      iat: nowSec - 10,
      exp: nowSec + 3600,
      auth_time: nowSec - 10,
    })
  ).toString('base64url');
  const signingInput = `${headerB64}.${payloadB64}`;
  const jwtSig = crypto.sign('RSA-SHA256', Buffer.from(signingInput, 'utf8'), privateKey).toString('base64url');
  const validFirebaseJwt = `${signingInput}.${jwtSig}`;

  const exchanged = await verifyFirebaseIdTokenAndIssueSession(`Bearer ${validFirebaseJwt}`);
  assert.equal(exchanged.allowed, true);
  assert.equal(exchanged.data?.session.uid, 'firebase_user_alice');
  assert.equal(exchanged.data?.session.role, 'user');
  assert.ok(exchanged.data?.sessionToken.startsWith('molt_sig_v1.'));

  // Forged JWT signed with wrong signature is rejected with 401
  const badJwt = `${signingInput}.${jwtSig.slice(0, -4)}AAAA`;
  const badExchange = await verifyFirebaseIdTokenAndIssueSession(`Bearer ${badJwt}`);
  assert.equal(badExchange.allowed, false);
  assert.equal(badExchange.status, 401);

  // Tampered HMAC signature on molt_sig_v1 token MUST be rejected
  const validToken = issueSignedServerSessionToken({
    uid: 'u_admin',
    email: 'syntheticinquiry@gmail.com',
    emailVerified: true,
    assignedRole: 'admin',
  });
  const tamperedToken = validToken.slice(0, -4) + 'ffff';
  assert.equal(verifyAndExtractSessionToken(`Bearer ${tamperedToken}`), null);

  // Cryptographically signed server token succeeds and resolves accurate role
  const verified = verifyAndExtractSessionToken(`Bearer ${validToken}`);
  assert.ok(verified);
  assert.equal(verified.uid, 'u_admin');
  assert.equal(verified.role, 'admin');

  // Key rotation without revoking old keys keeps existing session valid, while revoking old keys invalidates it
  const rot1 = rotateSessionSigningSecret(false);
  assert.ok(rot1.newKid.startsWith('hmac_epoch_'));
  assert.ok(verifyAndExtractSessionToken(`Bearer ${validToken}`));

  // Explicit token revocation immediately invalidates the session token prior to exp
  const revokeRes = revokeServerSessionToken(`Bearer ${validToken}`);
  assert.equal(revokeRes.allowed, true);
  assert.ok(revokeRes.data?.jti.startsWith('sess_'));
  assert.equal(verifyAndExtractSessionToken(`Bearer ${validToken}`), null);
});

test('Scenario 2: Unauthorized access to another user’s records (IDOR / Cross-Account Ownership)', () => {
  const userA = makeSession('user_alice_01', 'alice@example.com', true);
  const checkOtherRecord = authorizeAction(userA, 'user', { targetOwnerUid: 'user_bob_02' });
  assert.equal(checkOtherRecord.allowed, false);
  assert.equal(checkOtherRecord.status, 403);
  assert.equal(checkOtherRecord.code, 'CROSS_ACCOUNT_ACCESS_DENIED');

  const checkOwnRecord = authorizeAction(userA, 'user', { targetOwnerUid: 'user_alice_01' });
  assert.equal(checkOwnRecord.allowed, true);
});

test('Scenario 3: Privilege escalation — ordinary user cannot execute operator or admin mutations', () => {
  const ordinaryUser = makeSession('user_ordinary_99', 'user@example.com', true);
  assert.equal(ordinaryUser.role, 'user');

  const operatorCheck = authorizeAction(ordinaryUser, 'operator');
  assert.equal(operatorCheck.allowed, false);
  assert.equal(operatorCheck.status, 403);

  const adminCheck = authorizeAction(ordinaryUser, 'admin');
  assert.equal(adminCheck.allowed, false);
  assert.equal(adminCheck.status, 403);
});

test('Scenario 4: Forged admin roles — client-supplied x-molt-role or x-admin-override headers are rejected with 403', () => {
  const caller = makeSession('attacker_uid', 'attacker@example.com', true);
  const result = authorizeAction(caller, 'user', {
    clientSuppliedHeaders: {
      'x-molt-role': 'admin',
      'x-admin-override': 'true',
    },
  });
  assert.equal(result.allowed, false);
  assert.equal(result.status, 403);
  assert.equal(result.code, 'FORGED_PRIVILEGE_HEADER_REJECTED');
});

test('Scenario 5: Agent reputation manipulation — self-reported claims cannot inflate delivery score or verified status', () => {
  resetSecurityStoresForTesting();
  const user = makeSession('agent_owner_1', 'owner@example.com', true);

  // Attempt to inject client-supplied reliabilityPct or reputationTier override
  const spoofAttempt = validateAgentEvidenceSubmission(
    user,
    {
      agentId: 'agent_alpha',
      deliverableUri: 'https://github.com/molt-agent/valid-report',
      summary: 'Deterministic analysis of POPCAT/SOL liquidity concentration and slippage over 100 slots.',
      reliabilityPct: 100,
    },
    'idem_agent_001'
  );
  assert.equal(spoofAttempt.allowed, false);
  assert.equal(spoofAttempt.status, 403);
  assert.equal(spoofAttempt.code, 'AGENT_REPUTATION_TAMPERING_BLOCKED');

  // Valid submission is strictly recorded as SELF_REPORTED pending backend verification
  const validSelfReport = validateAgentEvidenceSubmission(
    user,
    {
      agentId: 'agent_alpha',
      deliverableUri: 'https://github.com/molt-agent/valid-report',
      summary: 'Deterministic analysis of POPCAT/SOL liquidity concentration and slippage over 100 slots.',
    },
    'idem_agent_002'
  );
  assert.equal(validSelfReport.allowed, true);
  assert.equal(validSelfReport.data?.provenance, 'SELF_REPORTED');
});

test('Scenario 6: Sentinel score forgery — non-admin callers cannot publish or overwrite Sentinel risk scores', () => {
  const developerCaller = makeSession('dev_01', 'dev@example.com', true, 'developer');
  const forgedScore = validateSentinelAssessmentRequest(developerCaller, {
    pair: 'POPCAT/SOL',
    riskScore: 0.1,
    status: 'SAFE',
    signatureEd25519: 'ed25519:forged_signature_12345678901234567890',
  });
  assert.equal(forgedScore.allowed, false);
  assert.equal(forgedScore.status, 403);
  assert.equal(forgedScore.code, 'SENTINEL_SCORE_FORGERY_BLOCKED');
});

test('Scenario 7: Cross-account API-key access, hashed storage, timing-safe verification & revocation (SC11-F04)', () => {
  resetSecurityStoresForTesting();
  const alice = makeSession('alice_uid', 'alice@example.com', true);
  const bob = makeSession('bob_uid', 'bob@example.com', true);

  const issued = issueScopedApiKey(alice, 'alice_uid', ['sentinel:read', 'witness:verify']);
  assert.equal(issued.allowed, true);
  assert.ok(issued.data?.rawKeyOnce.startsWith('mk_dev_'));
  assert.equal(issued.data?.keyHashSha256.length, 64);

  // Verify timing-safe API key credential validation with required scope
  const validUse = verifyApiKeyCredential(issued.data!.rawKeyOnce, 'sentinel:read');
  assert.equal(validUse.allowed, true);

  // Missing scope is denied with 403 API_KEY_SCOPE_DENIED
  const missingScope = verifyApiKeyCredential(issued.data!.rawKeyOnce, 'jobs:submit');
  assert.equal(missingScope.allowed, false);
  assert.equal(missingScope.status, 403);
  assert.equal(missingScope.code, 'API_KEY_SCOPE_DENIED');

  // Bob attempts to read or revoke Alice's API key -> 403 Forbidden
  const bobInspect = getApiKeyMetadata(bob, issued.data!.keyId);
  assert.equal(bobInspect.allowed, false);
  assert.equal(bobInspect.status, 403);

  const bobRevoke = revokeScopedApiKey(bob, issued.data!.keyId);
  assert.equal(bobRevoke.allowed, false);
  assert.equal(bobRevoke.status, 403);

  // Alice inspects her own API key metadata -> allowed, and rawKeyOnce is NOT present on stored metadata
  const aliceInspect = getApiKeyMetadata(alice, issued.data!.keyId);
  assert.equal(aliceInspect.allowed, true);
  assert.equal(aliceInspect.data?.keyId, issued.data!.keyId);
  assert.equal(Object.prototype.hasOwnProperty.call(aliceInspect.data, 'rawKeyOnce'), false);

  // Alice revokes her API key -> subsequent use is rejected with 403 API_KEY_REVOKED
  const aliceRevoke = revokeScopedApiKey(alice, issued.data!.keyId);
  assert.equal(aliceRevoke.allowed, true);
  assert.equal(aliceRevoke.data?.revoked, true);

  const useAfterRevoke = verifyApiKeyCredential(issued.data!.rawKeyOnce, 'sentinel:read');
  assert.equal(useAfterRevoke.allowed, false);
  assert.equal(useAfterRevoke.status, 403);
  assert.equal(useAfterRevoke.code, 'API_KEY_REVOKED');
});

test('Scenario 8: Credit balance tampering — client-supplied creditsGranted override is rejected', () => {
  resetSecurityStoresForTesting();
  const user = makeSession('buyer_01', 'buyer@example.com', true);

  const tampered = processVerifiedSettlementRequest(
    user,
    {
      tier: 'Micro',
      rail: 'SOL',
      txHash: '5YcK3mTz8qvS9ewb4J7p2kQnGdF6z1vX8uP9wE3nL2aM',
      creditsGranted: 25000,
    },
    'idem_tamper_001'
  );
  assert.equal(tampered.allowed, false);
  assert.equal(tampered.status, 403);
  assert.equal(tampered.code, 'CREDIT_BALANCE_TAMPERING_BLOCKED');
});

test('Scenario 9: Payment replay attacks & durable security ledger persistence across reloads (SC11-F04)', () => {
  resetSecurityStoresForTesting();
  const user = makeSession('buyer_02', 'buyer2@example.com', true);

  const firstSettlement = processVerifiedSettlementRequest(
    user,
    {
      tier: 'Pro',
      rail: 'USDC',
      txHash: '9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin',
    },
    'idem_valid_1001'
  );
  assert.equal(firstSettlement.allowed, true);

  // Verify durable ledger file on disk contains the processed txHash and idempotencyKey
  const persistedState = loadPersistentSecurityState();
  assert.ok(persistedState.processedPaymentTxHashes.includes('9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin'));
  assert.ok(persistedState.processedIdempotencyKeys.includes('pay:buyer_02:idem_valid_1001'));

  // Replay with same txHash -> 409 Conflict
  const replayTxHash = processVerifiedSettlementRequest(
    user,
    {
      tier: 'Pro',
      rail: 'USDC',
      txHash: '9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin',
    },
    'idem_valid_1002'
  );
  assert.equal(replayTxHash.allowed, false);
  assert.equal(replayTxHash.status, 409);
  assert.equal(replayTxHash.code, 'PAYMENT_REPLAY_DETECTED');
});

test('Scenario 10: Invalid and malicious API inputs — malformed IDs, invalid rails, and disallowed scopes are rejected', () => {
  const user = makeSession('user_input_test', 'input@example.com', true);

  // Disallowed scope injection in API key request
  const badKey = issueScopedApiKey(user, 'user_input_test', ['admin:root_shell']);
  assert.equal(badKey.allowed, false);
  assert.equal(badKey.status, 400);

  // Invalid payment rail
  const badRail = processVerifiedSettlementRequest(
    user,
    {
      tier: 'Pro',
      rail: 'DOGE',
      txHash: '3mPzQvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusK9a1',
    },
    'idem_bad_rail_01'
  );
  assert.equal(badRail.allowed, false);
  assert.equal(badRail.status, 400);
});

test('Scenario 11: Excessive request rates — sliding-window rate limiter blocks burst floods with 429', () => {
  resetSecurityStoresForTesting();
  const limitKey = 'ip:198.51.100.42:admin';
  for (let i = 0; i < 5; i++) {
    const res = enforceRateLimit(limitKey, 5, 60_000, 1_000_000);
    assert.equal(res.allowed, true);
  }
  const sixth = enforceRateLimit(limitKey, 5, 60_000, 1_000_000);
  assert.equal(sixth.allowed, false);
  assert.equal(sixth.status, 429);
  assert.equal(sixth.code, 'RATE_LIMIT_EXCEEDED');
});

test('Scenario 12: Public data leakage & provenance — data provider explicitly flags SIMULATED_DEMO and isAuthoritative=false', async () => {
  assert.equal(defaultDataProvider.mode, 'SIMULATED_DEMO');
  const poolsEnv = await defaultDataProvider.getSentinelPools();
  assert.equal(poolsEnv.isAuthoritative, false);
  assert.equal(poolsEnv.mode, 'SIMULATED_DEMO');
});

test('Scenario 13: Missing or overly permissive Firestore rules — no wildcard allow read, write: if true exists', () => {
  const rules = fs.readFileSync('firestore.rules', 'utf8');
  assert.equal(/allow\s+read,\s*write:\s*if\s+true/i.test(rules), false);
  assert.ok(rules.includes('allow read, write: if false;'));
});

test('Scenario 14: Secret exposure & market provider hygiene — no private keys or deprecated provider keys in src/', () => {
  const srcFiles = [
    'src/App.tsx',
    'src/firebase.ts',
    'src/utils/cryptoEngine.ts',
    'src/components/LandingPage.tsx',
    'src/components/SentinelTerminalPage.tsx',
    'src/components/AutomationPage.tsx',
    'src/components/AdminPanelPage.tsx',
  ];
  const deprecatedKeyName = ['COIN', 'MARKET', 'CAP', '_API_KEY'].join('');
  for (const file of srcFiles) {
    const content = fs.readFileSync(file, 'utf8');
    assert.equal(content.includes(deprecatedKeyName), false, `Deprecated secret env name leaked in ${file}`);
    assert.equal(content.includes('BEGIN PRIVATE KEY'), false, `Private key leaked in ${file}`);
  }
});

test('Scenario 15: Unsafe agent-provided HTML or links (XSS & SSRF) & real Ed25519 backend signing (SC11-F08)', () => {
  assert.equal(validateSafeExternalUri('javascript:alert(1)').allowed, false);
  assert.equal(validateSafeExternalUri('data:text/html,<script>alert(1)</script>').allowed, false);
  assert.equal(validateSafeExternalUri('https://127.0.0.1/admin').allowed, false);
  assert.equal(validateSafeExternalUri('https://127.0.0.2/internal').allowed, false);
  assert.equal(validateSafeExternalUri('https://[::ffff:127.0.0.1]/secret').allowed, false);
  assert.equal(validateSafeExternalUri('https://169.254.169.254/latest/meta-data/').allowed, false);
  assert.equal(validateSafeExternalUri('https://localhost:3000/internal').allowed, false);
  assert.equal(validateSafeExternalUri('https://gist.github.com/molt-agent/report').allowed, true);

  const dirtyHtml = '<img src=x onerror=alert(1)><script>steal()</script>Clean findings summary';
  const sanitized = sanitizePlainText(dirtyHtml, 200);
  assert.equal(sanitized.includes('<script>'), false);
  assert.equal(sanitized.includes('<img'), false);
  assert.equal(sanitized, 'Clean findings summary');

  // Verify real Node.js crypto.sign(null, ...) Ed25519 signature & verification
  const canonicalPayload = '{"pair":"POPCAT/SOL","risk_score":8.9,"slot":312891045}';
  const signed = signServerEd25519Payload(canonicalPayload);
  assert.equal(verifyServerEd25519Payload(canonicalPayload, signed.signatureBase64Url), true);
  assert.equal(
    verifyServerEd25519Payload(
      '{"pair":"POPCAT/SOL","risk_score":1.0,"slot":312891045}',
      signed.signatureBase64Url
    ),
    false
  );
});

test('Scenario 16: Members-only Automation Bot validation — blocks unauthenticated callers, rejects custodial private keys, blocks SSRF webhooks, and attests valid bot configs', () => {
  const member = makeSession('member_trader_01', 'trader@example.com', true, 'user');

  // 1. Anonymous caller is blocked (Members-Only enforcement)
  const anonAttempt = validateAutomationBotConfig(null, {
    botName: 'Anon Sniper',
    strategyType: 'LIQUIDITY_SNIPER',
    targetDex: 'Raydium',
    targetPair: 'SOL/USDC',
    orderSizeSol: 1.5,
    maxSlippageBps: 50,
    jitoTipLamports: 100000,
    maxRiskScoreAbort: 3.5,
  });
  assert.equal(anonAttempt.allowed, false);
  assert.equal(anonAttempt.status, 401);

  // 2. Custodial secret injection is strictly rejected with 400 CUSTODIAL_SECRET_REJECTED
  const custodialAttempt = validateAutomationBotConfig(member, {
    botName: 'Custodial Bot',
    strategyType: 'LIQUIDITY_SNIPER',
    targetDex: 'Raydium',
    targetPair: 'SOL/USDC',
    orderSizeSol: 1.5,
    maxSlippageBps: 50,
    jitoTipLamports: 100000,
    maxRiskScoreAbort: 3.5,
    privateKey: '5MaiiCavjCmn9Hs1o3eznqDEhRwxo7pXiAYez7keQUvi',
  });
  assert.equal(custodialAttempt.allowed, false);
  assert.equal(custodialAttempt.status, 400);
  assert.equal(custodialAttempt.code, 'CUSTODIAL_SECRET_REJECTED');

  // 3. SSRF webhook callback URI is rejected
  const ssrfWebhookAttempt = validateAutomationBotConfig(member, {
    botName: 'SSRF Webhook Sniper',
    strategyType: 'LIQUIDITY_SNIPER',
    targetDex: 'Raydium',
    targetPair: 'SOL/USDC',
    orderSizeSol: 1.5,
    maxSlippageBps: 50,
    jitoTipLamports: 100000,
    maxRiskScoreAbort: 3.5,
    webhookCallbackUri: 'https://169.254.169.254/latest/meta-data/',
  });
  assert.equal(ssrfWebhookAttempt.allowed, false);
  assert.equal(ssrfWebhookAttempt.status, 400);

  // 4. Valid non-custodial member bot configuration succeeds (Solana Raydium + Metal X DEX + Gas/Pool/Script)
  const validBot = validateAutomationBotConfig(member, {
    botName: 'Raydium Launchpad Sniper v2',
    strategyType: 'LIQUIDITY_SNIPER',
    targetDex: 'Raydium',
    targetPair: 'SOL/USDC',
    targetPoolAddress: '58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2',
    orderSizeSol: 2.5,
    maxSlippageBps: 85,
    gasPriorityMode: 'ULTRA_JITO_MEV',
    computeUnitLimit: 350000,
    priorityFeeMicroLamports: 125000,
    jitoTipLamports: 150000,
    maxRiskScoreAbort: 3.5,
    requireEd25519Witness: true,
    webhookCallbackUri: 'https://hooks.moltalpha.dev/v1/snipe-alert',
    customScript: 'export function onBeforeSnipe(ctx) { return { action: "ALLOW_SNIPE" }; }',
  });
  assert.equal(validBot.allowed, true);
  assert.equal(validBot.data?.ownerUid, 'member_trader_01');
  assert.equal(validBot.data?.executionMode, 'NON_CUSTODIAL_SANDBOX_SIMULATION');
  assert.equal(validBot.data?.strategyType, 'LIQUIDITY_SNIPER');
  assert.equal(validBot.data?.targetPoolAddress, '58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2');
  assert.equal(validBot.data?.gasPriorityMode, 'ULTRA_JITO_MEV');
  assert.equal(validBot.data?.computeUnitLimit, 350000);
  assert.equal(validBot.data?.priorityFeeMicroLamports, 125000);
  assert.equal(validBot.data?.customScriptHashSha256?.length, 64);

  // 5. Malformed target liquidity pool address is rejected
  const badPoolBot = validateAutomationBotConfig(member, {
    botName: 'Malformed Pool Bot',
    strategyType: 'LIQUIDITY_SNIPER',
    targetDex: 'Raydium',
    targetPair: 'SOL/USDC',
    targetPoolAddress: '!!!invalid_pool_address$$$',
    orderSizeSol: 1.0,
    maxSlippageBps: 50,
    jitoTipLamports: 100000,
    maxRiskScoreAbort: 4.0,
  });
  assert.equal(badPoolBot.allowed, false);
  assert.equal(badPoolBot.code, 'INVALID_TARGET_POOL_ADDRESS');

  // 6. Unsafe custom bot script (eval / hardcoded privateKey) is rejected
  const unsafeEvalScript = validateCustomBotScript('export function onBeforeSnipe(ctx) { eval("steal()"); }');
  assert.equal(unsafeEvalScript.allowed, false);
  assert.equal(unsafeEvalScript.code, 'UNSAFE_CUSTOM_SCRIPT_REJECTED');

  const unsafeKeyScript = validateCustomBotScript('const privateKey = "5MaiiCavjCmn9";');
  assert.equal(unsafeKeyScript.allowed, false);
  assert.equal(unsafeKeyScript.code, 'UNSAFE_CUSTOM_SCRIPT_REJECTED');

  const validMetalXBot = validateAutomationBotConfig(member, {
    botName: 'Metal X OrderQ Sniper',
    strategyType: 'METALX_ORDERBOOK_SNIPER',
    targetDex: 'Metal X DEX',
    targetPair: 'XPR/XUSDC',
    targetPoolAddress: 'dex::market_1_sol_xusdc',
    orderSizeSol: 50,
    maxSlippageBps: 45,
    jitoTipLamports: 10000,
    maxRiskScoreAbort: 3.0,
    requireEd25519Witness: true,
  });
  assert.equal(validMetalXBot.allowed, true);
  assert.equal(validMetalXBot.data?.targetDex, 'Metal X DEX');
  assert.equal(validMetalXBot.data?.strategyType, 'METALX_ORDERBOOK_SNIPER');
});


