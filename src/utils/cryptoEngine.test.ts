import test from 'node:test';
import assert from 'node:assert/strict';
import {
  classifyRiskScore,
  formatCompactUsd,
  canonicalizeJsonRfc8785,
  buildWitnessAttestation,
  verifyWitnessAttestation,
  verifyDuesProofBirthCert,
  lookupAgentDossier,
  calculateMultiRailQuote,
  rotateWitnessKeys,
  INITIAL_POOLS,
  INITIAL_WITNESS_KEYS,
} from './cryptoEngine';

test('classifyRiskScore categorizes microstructure risk scores accurately', () => {
  assert.equal(classifyRiskScore(2.8), 'SAFE');
  assert.equal(classifyRiskScore(4.9), 'SAFE');
  assert.equal(classifyRiskScore(5.6), 'WATCH');
  assert.equal(classifyRiskScore(7.1), 'HIGH');
  assert.equal(classifyRiskScore(8.9), 'CRITICAL');
});

test('formatCompactUsd formats millions and billions cleanly', () => {
  assert.equal(formatCompactUsd(148_200_000), '$148.2M');
  assert.equal(formatCompactUsd(1_240_000_000), '$1.24B');
  assert.equal(formatCompactUsd(6_400_000), '$6.4M');
});

test('canonicalizeJsonRfc8785 recursively sorts object keys in UTF-16 code-unit order without whitespace', () => {
  const unsorted = {
    version: '1.0',
    type: 'risk_assessment',
    pool: 'BCnkYex2...Zq9',
    nested: { z: 1, a: 2, m: [3, { b: true, a: false }] },
  };
  const canonical = canonicalizeJsonRfc8785(unsorted);
  assert.equal(
    canonical,
    '{"nested":{"a":2,"m":[3,{"a":false,"b":true}],"z":1},"pool":"BCnkYex2...Zq9","type":"risk_assessment","version":"1.0"}'
  );
});

test('buildWitnessAttestation & verifyWitnessAttestation enforce RFC 8785 digest, signature binding, and reject tampering (SC11-F02)', () => {
  const popcatPool = INITIAL_POOLS.find((p) => p.pair === 'POPCAT/SOL')!;
  const witness = buildWitnessAttestation(popcatPool, INITIAL_WITNESS_KEYS[0]);

  assert.equal(witness.targetPair, 'POPCAT/SOL');
  assert.equal(witness.slot, 312891045);
  assert.equal(witness.witnessHashSha256.length, 64);
  assert.equal(witness.signatureEd25519.length, 64);
  assert.equal(verifyWitnessAttestation(witness), true);

  // Verify keys in canonicalJson are strictly sorted per RFC 8785
  const parsed = JSON.parse(witness.canonicalJson);
  const keys = Object.keys(parsed);
  const sortedKeys = [...keys].sort();
  assert.deepEqual(keys, sortedKeys);
  assert.equal(parsed.type, 'risk_assessment');
  assert.equal(parsed.risk_score, 8.9);
  assert.equal(parsed.liquidity_usd, 32100000);
  assert.equal(parsed.volume_24h_usd, 6400000);
  assert.equal(parsed.status, 'CRITICAL');

  // Negative Test 1: Tamper with risk_score inside canonicalJson -> MUST FAIL
  const tamperedRisk = {
    ...witness,
    canonicalJson: witness.canonicalJson.replace('"risk_score": 8.9', '"risk_score": 1.1'),
  };
  assert.equal(verifyWitnessAttestation(tamperedRisk), false);

  // Negative Test 2: Tamper with status inside canonicalJson -> MUST FAIL
  const tamperedStatus = {
    ...witness,
    canonicalJson: witness.canonicalJson.replace('"status": "CRITICAL"', '"status": "SAFE"'),
  };
  assert.equal(verifyWitnessAttestation(tamperedStatus), false);

  // Negative Test 3: Tamper with signatureEd25519 -> MUST FAIL
  const tamperedSig = {
    ...witness,
    signatureEd25519: (witness.signatureEd25519[0] === 'A' ? 'B' : 'A') + witness.signatureEd25519.slice(1),
  };
  assert.equal(verifyWitnessAttestation(tamperedSig), false);

  // Negative Test 4: Revoked witness key epoch -> MUST FAIL
  const revokedKeys = INITIAL_WITNESS_KEYS.map((k) =>
    k.keyId === witness.keyEpochId ? { ...k, status: 'Revoked' as const } : k
  );
  assert.equal(verifyWitnessAttestation(witness, revokedKeys), false);
});

test('lookupAgentDossier returns UNVERIFIED/UNOBSERVED for unknown agents, enforces honest demo bond disclosure, and rejects PROVISIONAL or Revoked BirthCerts (SC11-F03, SC12A-F11)', () => {
  const knownAgent = lookupAgentDossier('antigravityandrew');
  assert.equal(knownAgent.reputationTier, 'VERIFIED_OPERATOR');
  assert.equal(knownAgent.reliabilityPct, 100);
  assert.equal(verifyDuesProofBirthCert(knownAgent.birthCert), true);

  // Confirm no fabricated 500 USDC + 2.50 SOL bond is claimed as real staked funds
  assert.equal(knownAgent.birthCert.duesStakedFormatted.includes('500.00 USDC'), false);
  assert.ok(knownAgent.birthCert.duesStakedFormatted.includes('Simulated Sandbox Demo'));

  // Tampering with BirthCert canonicalBirthCertJson invalidates verification
  const tamperedCert = {
    ...knownAgent.birthCert,
    canonicalBirthCertJson: knownAgent.birthCert.canonicalBirthCertJson.replace(
      '"status": "DUESPROOF_VERIFIED"',
      '"status": "FORGED"'
    ),
  };
  assert.equal(verifyDuesProofBirthCert(tamperedCert), false);

  // Revoking the witness key epoch invalidates BirthCert verification
  const revokedKeys = INITIAL_WITNESS_KEYS.map((k) =>
    k.keyId === 'wtn_epoch_v7' ? { ...k, status: 'Revoked' as const } : k
  );
  assert.equal(verifyDuesProofBirthCert(knownAgent.birthCert, revokedKeys), false);

  // Defaulted / revoked agent BirthCert MUST return false on verification
  const defaultedAgent = lookupAgentDossier('frantic_129');
  assert.equal(defaultedAgent.birthCert.status, 'DUES_DEFAULT_REVOKED');
  assert.equal(verifyDuesProofBirthCert(defaultedAgent.birthCert), false);

  // Unknown agent handle must NOT fabricate 100% VERIFIED_OPERATOR standing and PROVISIONAL cert MUST fail verification
  const unknownAgent = lookupAgentDossier('unknown_unobserved_agent_99');
  assert.equal(unknownAgent.reputationTier, 'UNVERIFIED');
  assert.equal(unknownAgent.walletAddress, null);
  assert.equal(unknownAgent.reliabilityPct, null);
  assert.equal(unknownAgent.knownDeliveries, 0);
  assert.equal(unknownAgent.verificationStatus, 'UNOBSERVED');
  assert.equal(unknownAgent.publishedWork.length, 0);
  assert.equal(unknownAgent.birthCert.status, 'PROVISIONAL');
  assert.equal(verifyDuesProofBirthCert(unknownAgent.birthCert), false);
});

test('calculateMultiRailQuote computes accurate SOL, USDC, and Zero-Fee Nano settlements', () => {
  const solQuote = calculateMultiRailQuote('Pro', 'SOL');
  assert.equal(solQuote.usdAmount, 5.0);
  assert.equal(solQuote.creditsToGrant, 1500);
  assert.ok(solQuote.railAmountFormatted.endsWith('SOL'));

  const usdcQuote = calculateMultiRailQuote('Starter', 'USDC');
  assert.equal(usdcQuote.usdAmount, 1.0);
  assert.equal(usdcQuote.creditsToGrant, 150);
  assert.equal(usdcQuote.railAmountFormatted, '1.00 USDC');

  const nanoQuote = calculateMultiRailQuote('Micro', 'Nano');
  assert.equal(nanoQuote.usdAmount, 0.25);
  assert.equal(nanoQuote.creditsToGrant, 25);
  assert.ok(nanoQuote.networkFeeFormatted.includes('Zero-Fee'));
});

test('rotateWitnessKeys promotes new Ed25519 key epoch to Active and rotates prior Active key', () => {
  const { updatedKeys, newActiveKey } = rotateWitnessKeys(INITIAL_WITNESS_KEYS, 8);
  assert.equal(newActiveKey.keyId, 'wtn_epoch_v8');
  assert.equal(newActiveKey.status, 'Active');
  assert.equal(updatedKeys[0].keyId, 'wtn_epoch_v8');
  assert.equal(updatedKeys[1].keyId, 'wtn_epoch_v7');
  assert.equal(updatedKeys[1].status, 'Rotated');
});
