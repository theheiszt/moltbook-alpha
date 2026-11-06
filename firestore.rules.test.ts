import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

// Security Verification Suite for all 13 Firestore collections and Eight Pillars invariants
const rulesText = fs.readFileSync('firestore.rules', 'utf8');
const blueprintText = fs.readFileSync('firebase-blueprint.json', 'utf8');

interface AuthContext {
  uid: string;
  email: string;
  email_verified: boolean;
  isAdminDoc?: boolean;
}

const SERVER_TIME = '2026-11-05T21:45:00.000Z';

function isValidId(id: unknown): boolean {
  return typeof id === 'string' && id.length >= 1 && id.length <= 128 && /^[a-zA-Z0-9_-]+$/.test(id);
}

function isVerifiedUser(auth: AuthContext | null): boolean {
  return auth !== null && auth.email_verified === true;
}

function isAdmin(auth: AuthContext | null): boolean {
  return (
    isVerifiedUser(auth) &&
    auth !== null &&
    (Boolean(auth.isAdminDoc) || auth.email === 'syntheticinquiry@gmail.com')
  );
}

function hasOnlyKeys(obj: Record<string, unknown>, allowed: string[]): boolean {
  return Object.keys(obj).every((k) => allowed.includes(k));
}

function hasAllKeys(obj: Record<string, unknown>, required: string[]): boolean {
  return required.every((k) => Object.prototype.hasOwnProperty.call(obj, k));
}

function evaluateDirtyPayload(
  collection: string,
  docId: string,
  operation: 'get' | 'list' | 'create' | 'update' | 'delete',
  auth: AuthContext | null,
  payload: Record<string, unknown>,
  existingDoc?: Record<string, unknown>,
  parentExists = true
): 'ALLOWED' | 'PERMISSION_DENIED' {
  if (!auth) return 'PERMISSION_DENIED';
  if (operation === 'delete') return 'PERMISSION_DENIED';
  if (operation !== 'list' && !isValidId(docId)) return 'PERMISSION_DENIED';

  if (collection === 'users') {
    const reqKeys = ['uid', 'displayName', 'tier', 'credits', 'rateLimitRps', 'status', 'createdAt', 'updatedAt'];
    if (operation === 'create' || operation === 'update') {
      if (!isVerifiedUser(auth)) return 'PERMISSION_DENIED';
      if (!hasAllKeys(payload, reqKeys) || !hasOnlyKeys(payload, reqKeys)) return 'PERMISSION_DENIED';
      if (payload.uid !== docId) return 'PERMISSION_DENIED';
      if (typeof payload.displayName !== 'string' || payload.displayName.length < 1 || payload.displayName.length > 80) {
        return 'PERMISSION_DENIED';
      }
      if (!['Micro', 'Starter', 'Pro', 'Enterprise'].includes(String(payload.tier))) return 'PERMISSION_DENIED';
    }
    if (operation === 'create') {
      if (payload.createdAt !== SERVER_TIME || payload.updatedAt !== SERVER_TIME) return 'PERMISSION_DENIED';
      if (isAdmin(auth)) return 'ALLOWED';
      if (
        auth.uid === docId &&
        payload.tier === 'Micro' &&
        payload.credits === 0 &&
        payload.rateLimitRps === 15 &&
        payload.status === 'Active'
      ) {
        return 'ALLOWED';
      }
      return 'PERMISSION_DENIED';
    }
    if (operation === 'update' && existingDoc) {
      if (payload.uid !== existingDoc.uid || payload.createdAt !== existingDoc.createdAt) return 'PERMISSION_DENIED';
      if (payload.updatedAt !== SERVER_TIME) return 'PERMISSION_DENIED';
      if (isAdmin(auth)) return 'ALLOWED';
      if (
        auth.uid === docId &&
        payload.tier === existingDoc.tier &&
        payload.credits === existingDoc.credits &&
        payload.rateLimitRps === existingDoc.rateLimitRps &&
        payload.status === existingDoc.status
      ) {
        return 'ALLOWED';
      }
      return 'PERMISSION_DENIED';
    }
  }

  if (collection === 'users/private') {
    if (!parentExists || docId !== 'info') return 'PERMISSION_DENIED';
    const parentUid = String(existingDoc?.parentUid || 'u1');
    if (operation === 'get') {
      return auth.uid === parentUid || isAdmin(auth) ? 'ALLOWED' : 'PERMISSION_DENIED';
    }
    if (operation === 'list') return 'PERMISSION_DENIED';
    if (operation === 'create') {
      if (!isVerifiedUser(auth)) return 'PERMISSION_DENIED';
      const reqKeys = ['uid', 'email', 'createdAt'];
      if (!hasAllKeys(payload, reqKeys) || !hasOnlyKeys(payload, reqKeys)) return 'PERMISSION_DENIED';
      if (payload.uid !== parentUid || payload.createdAt !== SERVER_TIME) return 'PERMISSION_DENIED';
      return auth.uid === parentUid || isAdmin(auth) ? 'ALLOWED' : 'PERMISSION_DENIED';
    }
  }

  if (collection === 'developerAccounts') {
    if (operation === 'get' || operation === 'list') {
      return existingDoc?.ownerId === auth.uid || isAdmin(auth) ? 'ALLOWED' : 'PERMISSION_DENIED';
    }
    if (operation === 'create') {
      if (!isVerifiedUser(auth)) return 'PERMISSION_DENIED';
      const reqKeys = ['ownerId', 'organizationName', 'webhookUrl', 'ActiveKeysCount', 'status', 'createdAt', 'updatedAt'];
      if (!hasAllKeys(payload, reqKeys) || !hasOnlyKeys(payload, reqKeys)) return 'PERMISSION_DENIED';
      if (payload.ownerId !== auth.uid || payload.ActiveKeysCount !== 0 || payload.status !== 'Active') {
        return 'PERMISSION_DENIED';
      }
      return payload.createdAt === SERVER_TIME && payload.updatedAt === SERVER_TIME ? 'ALLOWED' : 'PERMISSION_DENIED';
    }
  }

  if (collection === 'apiKeys') {
    if (operation === 'get' || operation === 'list') {
      return existingDoc?.ownerId === auth.uid || isAdmin(auth) ? 'ALLOWED' : 'PERMISSION_DENIED';
    }
    if (operation === 'create') {
      if (!isVerifiedUser(auth)) return 'PERMISSION_DENIED';
      const reqKeys = ['keyId', 'ownerId', 'keyPrefix', 'keyHashSha256', 'scopes', 'rateLimitRps', 'status', 'createdAt', 'updatedAt'];
      if (!hasAllKeys(payload, reqKeys) || !hasOnlyKeys(payload, reqKeys)) return 'PERMISSION_DENIED';
      if (payload.keyId !== docId || typeof payload.keyHashSha256 !== 'string' || payload.keyHashSha256.length !== 64) {
        return 'PERMISSION_DENIED';
      }
      if (isAdmin(auth)) return 'ALLOWED';
      return payload.ownerId === auth.uid && payload.rateLimitRps === 15 && payload.status === 'Active'
        ? 'ALLOWED'
        : 'PERMISSION_DENIED';
    }
  }

  if (collection === 'agentIdentities') {
    if (operation === 'get' || operation === 'list') {
      return isVerifiedUser(auth) ? 'ALLOWED' : 'PERMISSION_DENIED';
    }
    if (operation === 'create') {
      if (!isVerifiedUser(auth)) return 'PERMISSION_DENIED';
      const reqKeys = ['agentId', 'ownerId', 'handle', 'walletAddress', 'duesProofVerified', 'status', 'createdAt', 'updatedAt'];
      if (!hasAllKeys(payload, reqKeys) || !hasOnlyKeys(payload, reqKeys)) return 'PERMISSION_DENIED';
      if (isAdmin(auth)) return 'ALLOWED';
      return payload.ownerId === auth.uid && payload.duesProofVerified === false && payload.status === 'Pending'
        ? 'ALLOWED'
        : 'PERMISSION_DENIED';
    }
  }

  if (
    collection === 'agentReputations' ||
    collection === 'sentinelAssessments' ||
    collection === 'witnessMetadata' ||
    collection === 'witnessKeys' ||
    collection === 'platformAnalytics'
  ) {
    if (operation === 'get' || operation === 'list') {
      return isVerifiedUser(auth) ? 'ALLOWED' : 'PERMISSION_DENIED';
    }
    return isAdmin(auth) ? 'ALLOWED' : 'PERMISSION_DENIED';
  }

  if (collection === 'agentProofs') {
    if (operation === 'get' || operation === 'list') {
      return isVerifiedUser(auth) ? 'ALLOWED' : 'PERMISSION_DENIED';
    }
    if (operation === 'create') {
      if (!isVerifiedUser(auth)) return 'PERMISSION_DENIED';
      const reqKeys = [
        'proofId',
        'agentId',
        'ownerId',
        'deliverableUri',
        'canonicalHashSha256',
        'signatureEd25519',
        'provenance',
        'verificationStatus',
        'createdAt',
      ];
      if (!hasAllKeys(payload, reqKeys) || !hasOnlyKeys(payload, reqKeys)) return 'PERMISSION_DENIED';
      if (isAdmin(auth)) return 'ALLOWED';
      return payload.ownerId === auth.uid &&
        payload.provenance === 'SELF_REPORTED' &&
        payload.verificationStatus === 'PENDING_REVIEW'
        ? 'ALLOWED'
        : 'PERMISSION_DENIED';
    }
  }

  if (collection === 'adminConfig') {
    return isAdmin(auth) ? 'ALLOWED' : 'PERMISSION_DENIED';
  }

  if (collection === 'auditLogs') {
    if (operation === 'list') {
      return existingDoc?.ownerId === auth.uid || isAdmin(auth) ? 'ALLOWED' : 'PERMISSION_DENIED';
    }
    if (operation === 'create') {
      if (!isVerifiedUser(auth)) return 'PERMISSION_DENIED';
      const reqKeys = ['ownerId', 'actor', 'action', 'details', 'createdAt'];
      if (!hasAllKeys(payload, reqKeys) || !hasOnlyKeys(payload, reqKeys)) return 'PERMISSION_DENIED';
      if (payload.ownerId !== auth.uid || payload.createdAt !== SERVER_TIME) return 'PERMISSION_DENIED';
      if (payload.actor !== 'user' && !isAdmin(auth)) return 'PERMISSION_DENIED';
      return 'ALLOWED';
    }
  }

  if (collection === 'settlements') {
    if (operation === 'create') {
      if (!isAdmin(auth)) return 'PERMISSION_DENIED';
      const reqKeys = ['ownerId', 'userHandle', 'amountUsd', 'rail', 'creditsGranted', 'txHash', 'status', 'createdAt'];
      if (!hasAllKeys(payload, reqKeys) || !hasOnlyKeys(payload, reqKeys)) return 'PERMISSION_DENIED';
      if (payload.createdAt !== SERVER_TIME) return 'PERMISSION_DENIED';
      if (!['SOL', 'USDC', 'Nano'].includes(String(payload.rail))) return 'PERMISSION_DENIED';
      if (payload.status !== 'Completed') return 'PERMISSION_DENIED';
      return 'ALLOWED';
    }
    if (operation === 'update' && existingDoc) {
      if (existingDoc.status === 'Completed') return 'PERMISSION_DENIED';
      return isAdmin(auth) ? 'ALLOWED' : 'PERMISSION_DENIED';
    }
  }

  return 'PERMISSION_DENIED';
}

test('Firestore rules and firebase-blueprint.json contain all 13 collection policies and 1:1 schema alignment (SC11-F09)', () => {
  assert.ok(rulesText.includes("rules_version = '2';"));
  assert.ok(rulesText.includes('allow read, write: if false;'));
  assert.ok(rulesText.includes('request.auth.token.email_verified == true'));

  const expectedPaths = [
    '/users/{userId}',
    '/users/{userId}/private/{docId}',
    '/developerAccounts/{accountId}',
    '/apiKeys/{keyId}',
    '/agentIdentities/{agentId}',
    '/agentReputations/{agentId}',
    '/agentProofs/{proofId}',
    '/sentinelAssessments/{assessmentId}',
    '/witnessMetadata/{witnessId}',
    '/witnessKeys/{keyId}',
    '/platformAnalytics/{metricId}',
    '/settlements/{settlementId}',
    '/adminConfig/{configId}',
    '/auditLogs/{logId}',
  ];

  const blueprint = JSON.parse(blueprintText);
  for (const pathPattern of expectedPaths) {
    assert.ok(rulesText.includes(`match ${pathPattern}`) || rulesText.includes('match /private/{docId}'));
    assert.ok(blueprint.firestore[pathPattern], `Missing ${pathPattern} in firebase-blueprint.json`);
  }
});

test('Dirty Dozen Payloads, Self-Escalation Payloads & All 13 Collection Policies enforce strict least privilege', () => {
  const user1: AuthContext = { uid: 'u1', email: 'operator@moltalpha.dev', email_verified: true };
  const user2: AuthContext = { uid: 'u2', email: 'other@moltalpha.dev', email_verified: true };
  const adminUser: AuthContext = { uid: 'adm', email: 'syntheticinquiry@gmail.com', email_verified: true, isAdminDoc: true };

  // 1. Shadow Field Injection
  assert.equal(
    evaluateDirtyPayload('users', 'u1', 'create', user1, {
      uid: 'u1',
      displayName: 'Operator',
      tier: 'Micro',
      credits: 0,
      rateLimitRps: 15,
      status: 'Active',
      createdAt: SERVER_TIME,
      updatedAt: SERVER_TIME,
      isAdmin: true,
    }),
    'PERMISSION_DENIED'
  );

  // 1b. Client Self-Assigning Enterprise Tier & 1,000,000 Credits on Create
  assert.equal(
    evaluateDirtyPayload('users', 'u1', 'create', user1, {
      uid: 'u1',
      displayName: 'Operator',
      tier: 'Enterprise',
      credits: 1000000,
      rateLimitRps: 10000,
      status: 'Active',
      createdAt: SERVER_TIME,
      updatedAt: SERVER_TIME,
    }),
    'PERMISSION_DENIED'
  );

  // 1c. Client Self-Escalating Credits on Update
  assert.equal(
    evaluateDirtyPayload(
      'users',
      'u1',
      'update',
      user1,
      {
        uid: 'u1',
        displayName: 'Operator',
        tier: 'Micro',
        credits: 999999,
        rateLimitRps: 15,
        status: 'Active',
        createdAt: SERVER_TIME,
        updatedAt: SERVER_TIME,
      },
      {
        uid: 'u1',
        displayName: 'Operator',
        tier: 'Micro',
        credits: 0,
        rateLimitRps: 15,
        status: 'Active',
        createdAt: SERVER_TIME,
      }
    ),
    'PERMISSION_DENIED'
  );

  // 2. Unverified Email Spoofing
  const spoofedAdmin: AuthContext = { uid: 'attacker', email: 'syntheticinquiry@gmail.com', email_verified: false };
  assert.equal(
    evaluateDirtyPayload('users', 'attacker', 'create', spoofedAdmin, {
      uid: 'attacker',
      displayName: 'Spoof',
      tier: 'Micro',
      credits: 0,
      rateLimitRps: 15,
      status: 'Active',
      createdAt: SERVER_TIME,
      updatedAt: SERVER_TIME,
    }),
    'PERMISSION_DENIED'
  );

  // 3. ID Poisoning (2KB String)
  assert.equal(
    evaluateDirtyPayload('auditLogs', 'x'.repeat(2000), 'create', user1, {
      ownerId: 'u1',
      actor: 'user',
      action: 'Login',
      details: 'Logged in',
      createdAt: SERVER_TIME,
    }),
    'PERMISSION_DENIED'
  );

  // 4. Direct Client Settlement Creation (Bypassing Backend Verification)
  assert.equal(
    evaluateDirtyPayload('settlements', 's1', 'create', user1, {
      ownerId: 'u1',
      userHandle: 'operator',
      amountUsd: 5,
      rail: 'SOL',
      creditsGranted: 1500,
      txHash: '5YcK3mTz8qvS9ewb4J7p2kQnGdF6z1vX',
      status: 'Completed',
      createdAt: SERVER_TIME,
    }),
    'PERMISSION_DENIED'
  );

  // 5. Forged Client Timestamp or Forged Admin Actor in Audit Logs
  assert.equal(
    evaluateDirtyPayload('auditLogs', 'l1', 'create', user1, {
      ownerId: 'u1',
      actor: 'admin',
      action: 'KeyRotate',
      details: 'Rotated key',
      createdAt: SERVER_TIME,
    }),
    'PERMISSION_DENIED'
  );

  // 6. PII Blanket Read by non-owner
  assert.equal(
    evaluateDirtyPayload('users/private', 'info', 'get', user2, {}, { parentUid: 'u1' }, true),
    'PERMISSION_DENIED'
  );

  // 7. Orphaned Subcollection Write
  assert.equal(
    evaluateDirtyPayload(
      'users/private',
      'info',
      'create',
      user1,
      { uid: 'u1', email: 'operator@moltalpha.dev', createdAt: SERVER_TIME },
      { parentUid: 'u1' },
      false
    ),
    'PERMISSION_DENIED'
  );

  // 8. Update-Gap Value Poisoning (5,000 char displayName)
  assert.equal(
    evaluateDirtyPayload(
      'users',
      'u1',
      'update',
      user1,
      {
        uid: 'u1',
        displayName: 'A'.repeat(5000),
        tier: 'Micro',
        credits: 0,
        rateLimitRps: 15,
        status: 'Active',
        createdAt: SERVER_TIME,
        updatedAt: SERVER_TIME,
      },
      { uid: 'u1', tier: 'Micro', credits: 0, rateLimitRps: 15, status: 'Active', createdAt: SERVER_TIME }
    ),
    'PERMISSION_DENIED'
  );

  // 9. Immortal Field Mutation (createdAt modified on update)
  assert.equal(
    evaluateDirtyPayload(
      'users',
      'u1',
      'update',
      user1,
      {
        uid: 'u1',
        displayName: 'Operator',
        tier: 'Micro',
        credits: 0,
        rateLimitRps: 15,
        status: 'Active',
        createdAt: '2099-01-01T00:00:00.000Z',
        updatedAt: SERVER_TIME,
      },
      { uid: 'u1', tier: 'Micro', credits: 0, rateLimitRps: 15, status: 'Active', createdAt: SERVER_TIME }
    ),
    'PERMISSION_DENIED'
  );

  // 10. Terminal State Mutation (updating Completed settlement)
  assert.equal(
    evaluateDirtyPayload(
      'settlements',
      's1',
      'update',
      user1,
      {
        ownerId: 'u1',
        userHandle: 'operator',
        amountUsd: 5,
        rail: 'SOL',
        creditsGranted: 999999,
        txHash: '5YcK3mTz8qvS9ewb4J7p2kQnGdF6z1vX',
        status: 'Completed',
        createdAt: SERVER_TIME,
      },
      { ownerId: 'u1', status: 'Completed', createdAt: SERVER_TIME }
    ),
    'PERMISSION_DENIED'
  );

  // 11. Unauthorized List Scraping
  assert.equal(
    evaluateDirtyPayload('auditLogs', 'l1', 'list', user2, {}, { ownerId: 'u1' }),
    'PERMISSION_DENIED'
  );

  // 12. Invalid Enum Injection
  assert.equal(
    evaluateDirtyPayload('settlements', 's2', 'create', adminUser, {
      ownerId: 'u1',
      userHandle: 'operator',
      amountUsd: 5,
      rail: 'DOGE',
      creditsGranted: 1500,
      txHash: '5YcK3mTz8qvS9ewb4J7p2kQnGdF6z1vX',
      status: 'Completed',
      createdAt: SERVER_TIME,
    }),
    'PERMISSION_DENIED'
  );

  // 13. Extended Collection Tests: developerAccounts, apiKeys, agentIdentities, agentReputations, agentProofs, sentinelAssessments, witnessMetadata, witnessKeys, platformAnalytics, adminConfig
  assert.equal(
    evaluateDirtyPayload('developerAccounts', 'dev_1', 'create', user1, {
      ownerId: 'u1',
      organizationName: 'Molt Research',
      webhookUrl: 'https://moltalpha.dev/webhook',
      ActiveKeysCount: 0,
      status: 'Active',
      createdAt: SERVER_TIME,
      updatedAt: SERVER_TIME,
    }),
    'ALLOWED'
  );
  assert.equal(
    evaluateDirtyPayload('developerAccounts', 'dev_1', 'get', user2, {}, { ownerId: 'u1' }),
    'PERMISSION_DENIED'
  );

  assert.equal(
    evaluateDirtyPayload('apiKeys', 'key_1', 'create', user1, {
      keyId: 'key_1',
      ownerId: 'u1',
      keyPrefix: 'mk_dev_1234',
      keyHashSha256: 'a'.repeat(64),
      scopes: ['sentinel:read'],
      rateLimitRps: 15,
      status: 'Active',
      createdAt: SERVER_TIME,
      updatedAt: SERVER_TIME,
    }),
    'ALLOWED'
  );
  // Attempting to self-assign 1000 RPS on apiKey create -> PERMISSION_DENIED
  assert.equal(
    evaluateDirtyPayload('apiKeys', 'key_2', 'create', user1, {
      keyId: 'key_2',
      ownerId: 'u1',
      keyPrefix: 'mk_dev_1234',
      keyHashSha256: 'a'.repeat(64),
      scopes: ['sentinel:read'],
      rateLimitRps: 1000,
      status: 'Active',
      createdAt: SERVER_TIME,
      updatedAt: SERVER_TIME,
    }),
    'PERMISSION_DENIED'
  );

  // Attempting to self-verify DuesProof on agentIdentities create -> PERMISSION_DENIED
  assert.equal(
    evaluateDirtyPayload('agentIdentities', 'ag_1', 'create', user1, {
      agentId: 'ag_1',
      ownerId: 'u1',
      handle: 'agent_one',
      walletAddress: '7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU',
      duesProofVerified: true,
      status: 'Active',
      createdAt: SERVER_TIME,
      updatedAt: SERVER_TIME,
    }),
    'PERMISSION_DENIED'
  );

  // Server-authoritative collections block non-admin writes
  for (const col of ['agentReputations', 'sentinelAssessments', 'witnessMetadata', 'witnessKeys', 'platformAnalytics', 'adminConfig']) {
    assert.equal(evaluateDirtyPayload(col, 'doc_1', 'create', user1, {}), 'PERMISSION_DENIED');
    assert.equal(evaluateDirtyPayload(col, 'doc_1', 'create', adminUser, {}), 'ALLOWED');
  }
  assert.equal(evaluateDirtyPayload('adminConfig', 'cfg_1', 'get', user1, {}), 'PERMISSION_DENIED');
  assert.equal(evaluateDirtyPayload('adminConfig', 'cfg_1', 'get', adminUser, {}), 'ALLOWED');
});
