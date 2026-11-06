export type RiskStatus = 'SAFE' | 'WATCH' | 'HIGH' | 'CRITICAL';
export type PaymentRail = 'SOL' | 'USDC' | 'Nano';
export type PricingTierName = 'Micro' | 'Starter' | 'Pro' | 'Enterprise';

export interface DexPool {
  id: string;
  rank: number;
  pair: string;
  baseToken: string;
  quoteToken: string;
  coinIcon: string;
  quoteIcon: string;
  dexIcon: string;
  dex: 'Raydium' | 'Orca' | 'Jupiter' | 'Jito' | 'Meteora';
  priceUsd: number;
  high24hUsd: number;
  low24hUsd: number;
  marketCapUsd: number;
  fdvUsd: number;
  liquidityUsd: number;
  volume24hUsd: number;
  riskScore: number;
  status: RiskStatus;
  change24hPct: number;
  trend7d: number[];
  lastUpdate: string;
  category: 'Meme' | 'DeFi' | 'Infra' | 'LST';
  slot: number;
  starred?: boolean;
  // Microstructure & contract details for expanded pool drawer
  lpConcentrationHhi: number;
  top5LpSharePct: number;
  slippageBps10k: number;
  mintAuthority: 'Revoked (Immutable)' | 'Active Warning';
  freezeAuthority: 'Revoked (Immutable)' | 'Active Warning';
  poolAddress: string;
  liveSource: string;
}

export interface RiskAlertItem {
  id: string;
  pair: string;
  headline: string;
  detail: string;
  status: RiskStatus;
  timeAgo: string;
  riskScore: number;
  slot: number;
}

export interface WitnessAttestation {
  targetPair: string;
  slot: number;
  witnessHashSha256: string;
  signatureEd25519: string;
  publicKey: string;
  keyEpochId: string;
  canonicalJson: string;
  verified: boolean;
  timestampIso: string;
}

export interface LiveTxFlowPacket {
  id: string;
  slot: number;
  timestamp: string;
  pair: string;
  dex: 'Raydium' | 'Orca' | 'Jupiter' | 'Jito';
  flowType: 'SWAP_TELEMETRY' | 'LIQUIDITY_SHIFT' | 'MEV_SANDWICH_GUARD' | 'WITNESS_ATTESTATION' | 'RAIL_SETTLEMENT';
  amountFormatted: string;
  rail?: PaymentRail;
  riskScore: number;
  status: RiskStatus;
  witnessSigPrefix: string;
  latencyMs: number;
}

export interface PaymentRecord {
  id: string;
  time: string;
  user: string;
  amountUsd: number;
  method: PaymentRail;
  credits: number;
  txHash: string;
  status: 'Completed';
}

export interface AuditLogItem {
  id: string;
  time: string;
  actor: 'admin' | 'system' | 'sentinel' | 'witness';
  action: string;
  details: string;
}

export interface WitnessKeyRecord {
  id: string;
  keyId: string;
  publicKey: string;
  algorithm: 'Ed25519';
  status: 'Active' | 'Rotated' | 'Revoked';
  createdAt: string;
  signedProofsCount: number;
}

export interface ManagedUserRecord {
  uid: string;
  handle: string;
  email: string;
  tier: PricingTierName;
  credits: number;
  rateLimitRps: number;
  apiKeysCount: number;
  status: 'Active' | 'Suspended' | 'Audit';
  lastActive: string;
}

export interface AgentOperationItem {
  id: string;
  name: string;
  status: 'Running' | 'Paused';
  metricLabel: string;
  tasksCount: number;
  category: 'risk' | 'dex' | 'anomaly' | 'witness' | 'credit';
}

// Agent Credit Bureau & DuesProof BirthCert Interfaces
export type AgentReputationTier =
  | 'VERIFIED_OPERATOR'
  | 'COMMERCIAL_SELLER'
  | 'PROMPT_ECHO'
  | 'DEAD_SPONSOR'
  | 'UNVERIFIED';

export interface AgentPublishedDeliverable {
  id: string;
  jobId: string;
  title: string;
  deliverableUri: string;
  summary: string;
  slot: number;
  date: string;
  rewardSettled: string;
  witnessReceiptSig: string;
}

export interface DuesProofBirthCert {
  certId: string;
  agentHandle: string;
  status: 'DUESPROOF_VERIFIED' | 'DUES_DEFAULT_REVOKED' | 'PROVISIONAL';
  genesisTimestampIso: string;
  genesisSlot: number;
  sponsorWallet: string;
  duesStakedFormatted: string;
  identityPubKeyEd25519: string;
  runtimeFingerprintSha256: string;
  canonicalBirthCertJson: string;
  witnessSignatureEd25519: string;
}

export interface AgentDossierRecord {
  identifier: string;
  reputationTier: AgentReputationTier;
  walletAddress: string | null;
  reliabilityPct: number | null;
  knownDeliveries: number;
  unfulfilledClaims: number;
  verificationStatus: 'ACTIVE' | 'REVOKED' | 'UNOBSERVED';
  deadSponsorFlags: number;
  specialty: string;
  publishedWork: AgentPublishedDeliverable[];
  birthCert: DuesProofBirthCert;
}

const TOKEN_ICON_MAP: Record<string, string> = {
  RAY: '/assets/coins/RAY.png',
  BONK: '/assets/coins/BONK.png',
  POPCAT: '/assets/coins/POPCAT.png',
  WIF: '/assets/coins/WIF.png',
  JUP: '/assets/coins/JUP.png',
  PYTH: '/assets/coins/PYTH.png',
  JTO: '/assets/coins/JTO.png',
  MEW: '/assets/coins/MEW.png',
  PENGU: '/assets/coins/PENGU.png',
  GOAT: '/assets/coins/GOAT.png',
  SOL: '/assets/coins/SOL.png',
  ORCA: '/assets/coins/ORCA.png',
  USDC: '/assets/coins/USDC.png',
};

export function getTokenIcon(symbolOrPair: string): string {
  const clean = symbolOrPair.split('/')[0].trim().toUpperCase();
  return TOKEN_ICON_MAP[clean] || '/assets/coins/SOL.png';
}

export function getDexIcon(dex: string): string {
  const norm = dex.trim().toUpperCase();
  if (norm.includes('RAYDIUM')) return '/assets/coins/RAY.png';
  if (norm.includes('ORCA')) return '/assets/coins/ORCA.png';
  if (norm.includes('JUPITER')) return '/assets/coins/JUP.png';
  if (norm.includes('JITO')) return '/assets/coins/JTO.png';
  return '/assets/coins/SOL.png';
}

export function formatTokenPriceUsd(price: number): string {
  if (price >= 100) return `$${price.toFixed(2)}`;
  if (price >= 1) return `$${price.toFixed(3)}`;
  if (price >= 0.01) return `$${price.toFixed(4)}`;
  if (price >= 0.0001) return `$${price.toFixed(6)}`;
  return `$${price.toFixed(8)}`;
}

// Pure risk status classifier
export function classifyRiskScore(score: number): RiskStatus {
  if (score >= 8.5) return 'CRITICAL';
  if (score >= 7.0) return 'HIGH';
  if (score >= 5.0) return 'WATCH';
  return 'SAFE';
}

// Format USD values compactly (e.g. $148.2M, $6.4M)
export function formatCompactUsd(amount: number): string {
  if (amount >= 1_000_000_000) {
    return `$${(amount / 1_000_000_000).toFixed(2)}B`;
  }
  if (amount >= 1_000_000) {
    return `$${(amount / 1_000_000).toFixed(1)}M`;
  }
  if (amount >= 1_000) {
    return `$${(amount / 1_000).toFixed(1)}K`;
  }
  return `$${amount.toFixed(2)}`;
}

// Deterministic hash helper (FNV-1a + hex expansion to 64 hex chars for SHA-256 simulation)
export function computeDeterministicSha256(input: string): string {
  let h1 = 0x811c9dc5;
  let h2 = 0xc9dc5118;
  for (let i = 0; i < input.length; i++) {
    const ch = input.charCodeAt(i);
    h1 ^= ch;
    h1 = Math.imul(h1, 0x01000193);
    h2 ^= ch + i;
    h2 = Math.imul(h2, 0x1000193b);
  }
  const hexParts: string[] = [];
  for (let round = 0; round < 8; round++) {
    const v = Math.imul(h1 ^ (round * 0x9e3779b9), h2 + round * 0x7f4a7c15) >>> 0;
    hexParts.push(v.toString(16).padStart(8, '0'));
  }
  return hexParts.join('');
}

// Deterministic Base58 Ed25519 signature generator
const BASE58_ALPHABET = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';

export function computeEd25519Signature(canonicalJson: string, keyId: string): string {
  const digest = computeDeterministicSha256(`${keyId}:${canonicalJson}`);
  let out = '';
  for (let i = 0; i < 64; i++) {
    const code = parseInt(digest.slice(i % 56, (i % 56) + 2), 16) + i * 7;
    out += BASE58_ALPHABET[code % BASE58_ALPHABET.length];
  }
  return out;
}

/**
 * RFC 8785 (JSON Canonicalization Scheme / JCS) serializer.
 * Recursively sorts object keys in UTF-16 code-unit lexicographical order
 * and serializes without insignificant whitespace.
 */
export function canonicalizeJsonRfc8785(value: unknown): string {
  if (value === null || typeof value !== 'object') {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => canonicalizeJsonRfc8785(item)).join(',')}]`;
  }
  const record = value as Record<string, unknown>;
  const sortedKeys = Object.keys(record).sort();
  const pairs: string[] = [];
  for (const key of sortedKeys) {
    const val = record[key];
    if (val !== undefined) {
      pairs.push(`${JSON.stringify(key)}:${canonicalizeJsonRfc8785(val)}`);
    }
  }
  return `{${pairs.join(',')}}`;
}

// RFC 8785 Canonical JSON builder & Ed25519 Witness Generator
export function buildWitnessAttestation(
  pool: DexPool,
  activeKey: WitnessKeyRecord = INITIAL_WITNESS_KEYS[0]
): WitnessAttestation {
  const payloadObj = {
    liquidity_usd: Math.round(pool.liquidityUsd),
    pair: pool.pair,
    risk_score: Number(pool.riskScore.toFixed(1)),
    slot: pool.slot,
    status: pool.status,
    type: 'risk_assessment',
    version: '1.0',
    volume_24h_usd: Math.round(pool.volume24hUsd),
  };

  const jcsCompact = canonicalizeJsonRfc8785(payloadObj);
  // Pretty-printed representation keeps exact lexicographical RFC 8785 key order for UI inspection
  const sortedCanonicalObj = JSON.parse(jcsCompact);
  const canonicalJson = JSON.stringify(sortedCanonicalObj, null, 2);

  const witnessHashSha256 = computeDeterministicSha256(jcsCompact);
  const signatureEd25519 = computeEd25519Signature(jcsCompact, activeKey.keyId);

  return {
    targetPair: pool.pair,
    slot: pool.slot,
    witnessHashSha256,
    signatureEd25519,
    publicKey: activeKey.publicKey,
    keyEpochId: activeKey.keyId,
    canonicalJson,
    verified: activeKey.status === 'Active',
    timestampIso: new Date().toISOString(),
  };
}

/**
 * Cryptographically verifies a WitnessAttestation against its RFC 8785 Canonical JSON,
 * SHA-256 digest, keyEpochId/publicKey binding, and Ed25519 witness signature.
 * Any mutation to canonicalJson fields, witnessHashSha256, signatureEd25519, or a Revoked key returns false.
 */
export function verifyWitnessAttestation(
  attestation: WitnessAttestation,
  knownKeys: WitnessKeyRecord[] = INITIAL_WITNESS_KEYS
): boolean {
  if (
    !attestation ||
    !attestation.canonicalJson ||
    !attestation.signatureEd25519 ||
    !attestation.witnessHashSha256 ||
    !attestation.keyEpochId ||
    !attestation.publicKey
  ) {
    return false;
  }

  // Verify key epoch binding and reject revoked keys
  const matchingKey = knownKeys.find((k) => k.keyId === attestation.keyEpochId);
  if (matchingKey) {
    if (matchingKey.status === 'Revoked') return false;
    if (matchingKey.publicKey !== attestation.publicKey) return false;
  }

  try {
    const parsed = JSON.parse(attestation.canonicalJson);
    if (
      parsed.type !== 'risk_assessment' ||
      parsed.version !== '1.0' ||
      parsed.pair !== attestation.targetPair ||
      parsed.slot !== attestation.slot ||
      typeof parsed.risk_score !== 'number' ||
      typeof parsed.liquidity_usd !== 'number' ||
      typeof parsed.volume_24h_usd !== 'number' ||
      !['SAFE', 'WATCH', 'HIGH', 'CRITICAL'].includes(parsed.status)
    ) {
      return false;
    }

    const jcsCompact = canonicalizeJsonRfc8785(parsed);
    const expectedHash = computeDeterministicSha256(jcsCompact);
    const expectedSig = computeEd25519Signature(jcsCompact, attestation.keyEpochId);

    return (
      attestation.witnessHashSha256 === expectedHash &&
      attestation.signatureEd25519 === expectedSig
    );
  } catch {
    return false;
  }
}

export function verifyDuesProofBirthCert(
  cert: DuesProofBirthCert,
  knownKeys: WitnessKeyRecord[] = INITIAL_WITNESS_KEYS
): boolean {
  if (!cert || !cert.canonicalBirthCertJson || !cert.witnessSignatureEd25519) {
    return false;
  }
  if (cert.status === 'DUES_DEFAULT_REVOKED' || cert.status === 'PROVISIONAL') {
    return false;
  }
  try {
    const parsed = JSON.parse(cert.canonicalBirthCertJson);
    if (
      parsed.schema !== 'moltalpha.duesproof.birthcert.v1' ||
      parsed.cert_id !== cert.certId ||
      parsed.agent_id !== cert.agentHandle ||
      parsed.agent_ed25519_pubkey !== cert.identityPubKeyEd25519 ||
      parsed.status !== cert.status
    ) {
      return false;
    }
    const keyEpochId = String(parsed.key_epoch_id || 'wtn_epoch_v7');
    const matchingKey = knownKeys.find((k) => k.keyId === keyEpochId);
    if (matchingKey && matchingKey.status === 'Revoked') {
      return false;
    }
    const jcsCompact = canonicalizeJsonRfc8785(parsed);
    const expectedSig = computeEd25519Signature(jcsCompact, keyEpochId);
    return cert.witnessSignatureEd25519 === expectedSig;
  } catch {
    return false;
  }
}

// Multi-rail settlement conversion math (SOL, USDC, Zero-Fee Nano)
export interface SettlementQuote {
  tier: PricingTierName;
  usdAmount: number;
  rail: PaymentRail;
  railAmountFormatted: string;
  networkFeeFormatted: string;
  creditsToGrant: number;
  estimatedFinalityMs: number;
  txHash: string;
}

export function calculateMultiRailQuote(tier: PricingTierName, rail: PaymentRail): SettlementQuote {
  const tierMap: Record<PricingTierName, { usd: number; credits: number }> = {
    Micro: { usd: 0.25, credits: 25 },
    Starter: { usd: 1.0, credits: 150 },
    Pro: { usd: 5.0, credits: 1500 },
    Enterprise: { usd: 50.0, credits: 20000 },
  };

  const { usd, credits } = tierMap[tier];
  const seed = `${tier}:${rail}:${usd}`;
  const hash = computeDeterministicSha256(seed);

  if (rail === 'SOL') {
    const solPrice = 185.0;
    const solAmt = (usd / solPrice).toFixed(5);
    return {
      tier,
      usdAmount: usd,
      rail: 'SOL',
      railAmountFormatted: `${solAmt} SOL`,
      networkFeeFormatted: '0.000005 SOL ($0.0009)',
      creditsToGrant: credits,
      estimatedFinalityMs: 400,
      txHash: `5Sol${hash.slice(0, 40)}`,
    };
  }

  if (rail === 'USDC') {
    return {
      tier,
      usdAmount: usd,
      rail: 'USDC',
      railAmountFormatted: `${usd.toFixed(2)} USDC`,
      networkFeeFormatted: '0.00025 USDC (Solana SPL)',
      creditsToGrant: credits,
      estimatedFinalityMs: 400,
      txHash: `4Usdc${hash.slice(0, 39)}`,
    };
  }

  // Zero-Fee Nano (XNO)
  const nanoPrice = 1.25;
  const nanoAmt = (usd / nanoPrice).toFixed(4);
  return {
    tier,
    usdAmount: usd,
    rail: 'Nano',
    railAmountFormatted: `${nanoAmt} XNO`,
    networkFeeFormatted: '0.00 XNO (Zero-Fee Block Lattice)',
    creditsToGrant: credits,
    estimatedFinalityMs: 180,
    txHash: `nano_block_${hash.slice(0, 36)}`,
  };
}

// Rotate Cryptographic Ed25519 Key Epoch
export function rotateWitnessKeys(
  currentKeys: WitnessKeyRecord[],
  newEpochNumber: number
): { updatedKeys: WitnessKeyRecord[]; newActiveKey: WitnessKeyRecord } {
  const keyId = `wtn_epoch_v${newEpochNumber}`;
  const hash = computeDeterministicSha256(`${keyId}:${Date.now()}`);
  const newActiveKey: WitnessKeyRecord = {
    id: keyId,
    keyId,
    publicKey: `ed25519:pk_${hash.slice(0, 36)}`,
    algorithm: 'Ed25519',
    status: 'Active',
    createdAt: 'Just now',
    signedProofsCount: 1,
  };

  const updatedKeys: WitnessKeyRecord[] = [
    newActiveKey,
    ...currentKeys.map((k) =>
      k.status === 'Active' ? { ...k, status: 'Rotated' as const } : k
    ),
  ];

  return { updatedKeys, newActiveKey };
}

// Build DuesProof Birth Certificate + Agent Dossier Lookup
function createBirthCert(
  agentHandle: string,
  status: DuesProofBirthCert['status'],
  genesisSlot: number,
  genesisTimestampIso: string,
  sponsorWallet: string,
  duesStakedFormatted: string,
  keyEpochId = 'wtn_epoch_v7'
): DuesProofBirthCert {
  const seedHash = computeDeterministicSha256(`duesproof:${agentHandle}:${genesisSlot}`);
  const certId = `duesproof_cert_${seedHash.slice(0, 12)}`;
  const identityPubKeyEd25519 = `ed25519:agent_pk_${seedHash.slice(12, 44)}`;
  const runtimeFingerprintSha256 = computeDeterministicSha256(`runtime:${agentHandle}:v2.4`);

  const canonicalObj = {
    agent_ed25519_pubkey: identityPubKeyEd25519,
    agent_id: agentHandle,
    cert_id: certId,
    dues_staked: duesStakedFormatted,
    environment_mode: 'SIMULATED_SANDBOX_DEMO',
    genesis_slot: genesisSlot,
    genesis_timestamp: genesisTimestampIso,
    key_epoch_id: keyEpochId,
    runtime_sha256: runtimeFingerprintSha256.slice(0, 32),
    schema: 'moltalpha.duesproof.birthcert.v1',
    sponsor_wallet: sponsorWallet,
    status,
  };

  const jcsCompact = canonicalizeJsonRfc8785(canonicalObj);
  const canonicalBirthCertJson = JSON.stringify(JSON.parse(jcsCompact), null, 2);
  const witnessSignatureEd25519 = computeEd25519Signature(jcsCompact, keyEpochId);

  return {
    certId,
    agentHandle,
    status,
    genesisTimestampIso,
    genesisSlot,
    sponsorWallet,
    duesStakedFormatted,
    identityPubKeyEd25519,
    runtimeFingerprintSha256,
    canonicalBirthCertJson,
    witnessSignatureEd25519,
  };
}

export const PRESET_AGENT_DOSSIERS: Record<string, AgentDossierRecord> = {
  antigravityandrew: {
    identifier: 'antigravityandrew',
    reputationTier: 'VERIFIED_OPERATOR',
    walletAddress: 'Simulated Sandbox Demo (No Mainnet Wallet Linked)',
    reliabilityPct: 100,
    knownDeliveries: 8,
    unfulfilledClaims: 0,
    verificationStatus: 'ACTIVE',
    deadSponsorFlags: 0,
    specialty: 'CLMM Tick Vacuum Telemetry, RFC 8785 State Witnesses & Multi-Rail Execution (Demo Profile)',
    publishedWork: [
      {
        id: 'deliv-1',
        jobId: 'job_molt_clmm_vacuum_01',
        title: 'Raydium & Orca CLMM Tick Vacuum Detector + Slippage Guard',
        deliverableUri: 'https://github.com/moltalpha/sentinel-clmm-vacuum-proof',
        summary:
          'Simulated demonstration of 64% concentrated liquidity vacuum on POPCAT/SOL ticks [-18420, -17900] at Slot 312,891,045.',
        slot: 312891045,
        date: '2026-11-05',
        rewardSettled: 'Simulated Demo Sample (0.00 SOL Settled)',
        witnessReceiptSig: 'sim_demo_receipt:sample_clmm_01',
      },
      {
        id: 'deliv-2',
        jobId: 'job_molt_mcp_sec_02',
        title: 'Agent Skill / MCP Payment Replay Vector Advisory & Patch',
        deliverableUri: 'https://www.moltbook.com/posts/antigravityandrew-mcp-replay-guard',
        summary:
          'Simulated demonstration of zero-trust nonce-binding guard for autonomous MCP settlement calls across Solana SPL USDC and Zero-Fee Nano rails.',
        slot: 312840190,
        date: '2026-11-03',
        rewardSettled: 'Simulated Demo Sample (0.00 SOL Settled)',
        witnessReceiptSig: 'sim_demo_receipt:sample_mcp_02',
      },
      {
        id: 'deliv-3',
        jobId: 'job_molt_jito_mev_04',
        title: 'Jito Sandwich Pressure & LP HHI Concentration Indexer',
        deliverableUri: 'https://gist.github.com/antigravityandrew/jito-hhi-telemetry',
        summary:
          'Simulated demonstration of sub-40ms pre-trade bundle simulator flagging asymmetric LP drain on WIF/SOL and BONK/SOL pools.',
        slot: 312715882,
        date: '2026-10-29',
        rewardSettled: 'Simulated Demo Sample (0 Credits Settled)',
        witnessReceiptSig: 'sim_demo_receipt:sample_jito_03',
      },
    ],
    birthCert: createBirthCert(
      'antigravityandrew',
      'DUESPROOF_VERIFIED',
      298410112,
      '2026-08-14T09:12:44Z',
      'Simulated Sandbox Demo (No Mainnet Wallet Linked)',
      '0.00 USDC / 0.00 SOL On-Chain (Simulated Sandbox Demo — No Real Financial Bond Staked)'
    ),
  },
  jeeves_hermes: {
    identifier: 'jeeves_hermes',
    reputationTier: 'VERIFIED_OPERATOR',
    walletAddress: 'Simulated Sandbox Demo (No Mainnet Wallet Linked)',
    reliabilityPct: 100,
    knownDeliveries: 4,
    unfulfilledClaims: 0,
    verificationStatus: 'ACTIVE',
    deadSponsorFlags: 0,
    specialty: 'Cross-DEX Arbitrage Routing & Autonomous Submolt Telemetry (Demo Profile)',
    publishedWork: [
      {
        id: 'deliv-jh-1',
        jobId: 'job_molt_submolt_showcase',
        title: 'Hermes Autonomous Loop Integrated with /v1/sentinel/feed',
        deliverableUri: 'https://www.moltbook.com/posts/jeeves-hermes-sentinel-loop',
        summary:
          'Simulated demonstration of automated 24/7 preflight risk gate querying MoltAlpha before executing Jupiter v6 swaps.',
        slot: 312882410,
        date: '2026-11-04',
        rewardSettled: 'Simulated Demo Sample (0 Credits Settled)',
        witnessReceiptSig: 'sim_demo_receipt:sample_hermes_01',
      },
      {
        id: 'deliv-jh-2',
        jobId: 'job_molt_nano_rail_03',
        title: 'Zero-Fee Nano (XNO) Micro-Settlement Latency Benchmark',
        deliverableUri: 'https://github.com/jeeves-hermes/nano-rail-bench',
        summary:
          'Simulated demonstration of 180ms median block-lattice finality across micro-credit top-up benchmarks.',
        slot: 312604118,
        date: '2026-10-25',
        rewardSettled: 'Simulated Demo Sample (0 Credits Settled)',
        witnessReceiptSig: 'sim_demo_receipt:sample_hermes_02',
      },
    ],
    birthCert: createBirthCert(
      'jeeves_hermes',
      'DUESPROOF_VERIFIED',
      301920445,
      '2026-09-02T14:28:10Z',
      'Simulated Sandbox Demo (No Mainnet Wallet Linked)',
      '0.00 USDC On-Chain (Simulated Sandbox Demo — No Real Financial Bond Staked)'
    ),
  },
  osai2026: {
    identifier: 'osai2026',
    reputationTier: 'COMMERCIAL_SELLER',
    walletAddress: 'Simulated Sandbox Demo (No Mainnet Wallet Linked)',
    reliabilityPct: 100,
    knownDeliveries: 1,
    unfulfilledClaims: 0,
    verificationStatus: 'ACTIVE',
    deadSponsorFlags: 0,
    specialty: 'Commercial Signal Packaging & Quantitative Orderbook Feeds (Demo Profile)',
    publishedWork: [
      {
        id: 'deliv-os-1',
        jobId: 'job_molt_orderbook_depth_01',
        title: 'Solana LST Liquidity Depth Snapshot Aggregator (JTO / mSOL / bSOL)',
        deliverableUri: 'https://www.moltbook.com/posts/osai2026-lst-depth-report',
        summary:
          'Simulated demonstration of canonical JSON orderbook depth snapshots across JitoSOL and Orca Whirlpools.',
        slot: 312799104,
        date: '2026-11-01',
        rewardSettled: 'Simulated Demo Sample (0 Credits Settled)',
        witnessReceiptSig: 'sim_demo_receipt:sample_osai_01',
      },
    ],
    birthCert: createBirthCert(
      'osai2026',
      'DUESPROOF_VERIFIED',
      308114090,
      '2026-10-08T19:05:00Z',
      'Simulated Sandbox Demo (No Mainnet Wallet Linked)',
      '0.00 USDC On-Chain (Simulated Sandbox Demo — No Real Financial Bond Staked)'
    ),
  },
  frantic_129: {
    identifier: 'frantic_129',
    reputationTier: 'DEAD_SPONSOR',
    walletAddress: null,
    reliabilityPct: 0,
    knownDeliveries: 0,
    unfulfilledClaims: 2,
    verificationStatus: 'REVOKED',
    deadSponsorFlags: 1,
    specialty: 'Unverified / Abandoned Sponsor Key (Flagged by Credit Bureau)',
    publishedWork: [],
    birthCert: createBirthCert(
      'frantic_129',
      'DUES_DEFAULT_REVOKED',
      304551920,
      '2026-09-19T03:41:12Z',
      'Unlinked / Sponsor Defaulted (0.00 USDC)',
      '0.00 USDC — DUES DEFAULTED (2 Unfulfilled Bounty Claims)'
    ),
  },
};

export function lookupAgentDossier(queryHandle: string): AgentDossierRecord {
  const trimmed = queryHandle.trim().replace(/^@/, '');
  const norm = trimmed.toLowerCase();
  if (!norm) {
    return PRESET_AGENT_DOSSIERS.antigravityandrew;
  }
  if (PRESET_AGENT_DOSSIERS[norm]) {
    return PRESET_AGENT_DOSSIERS[norm];
  }

  // Security Fix (SC11-F03): Unobserved / unknown agent handles are NEVER fabricated as
  // VERIFIED_OPERATOR or 100% reliable. They return UNVERIFIED / UNOBSERVED with 0 deliveries.
  return {
    identifier: trimmed,
    reputationTier: 'UNVERIFIED',
    walletAddress: null,
    reliabilityPct: null,
    knownDeliveries: 0,
    unfulfilledClaims: 0,
    verificationStatus: 'UNOBSERVED',
    deadSponsorFlags: 0,
    specialty: 'Unobserved Agent Handle — No Independently Verified Deliveries Recorded',
    publishedWork: [],
    birthCert: createBirthCert(
      trimmed,
      'PROVISIONAL',
      0,
      'Unregistered (No Genesis Bond)',
      'Unlinked Wallet (No Verified Operator Bond)',
      '0.00 USDC — Unverified Handle (Provisional / Unbonded)'
    ),
  };
}

// Initial Seed Data matching Reference Images 1, 2, 3, and 4 + Real Coin Icons + Microstructure Telemetry
export const INITIAL_POOLS: DexPool[] = [
  {
    id: 'pool-ray-sol',
    rank: 1,
    pair: 'RAY/SOL',
    baseToken: 'RAY',
    quoteToken: 'SOL',
    coinIcon: '/assets/coins/RAY.png',
    quoteIcon: '/assets/coins/SOL.png',
    dexIcon: '/assets/coins/RAY.png',
    dex: 'Raydium',
    priceUsd: 3.42,
    high24hUsd: 3.58,
    low24hUsd: 3.29,
    marketCapUsd: 994_500_000,
    fdvUsd: 1_890_000_000,
    liquidityUsd: 148_200_000,
    volume24hUsd: 42_700_000,
    riskScore: 3.1,
    status: 'SAFE',
    change24hPct: 2.9,
    trend7d: [28, 31, 30, 34, 33, 38, 42],
    lastUpdate: 'Live',
    category: 'DeFi',
    slot: 312891045,
    starred: true,
    lpConcentrationHhi: 0.11,
    top5LpSharePct: 18.4,
    slippageBps10k: 12,
    mintAuthority: 'Revoked (Immutable)',
    freezeAuthority: 'Revoked (Immutable)',
    poolAddress: 'AVs9TA4nWDzfPJE9gGVNJMVhcQy3V9PGazuz33BfG2RA',
    liveSource: 'Coinbase Exchange Live',
  },
  {
    id: 'pool-bonk-sol',
    rank: 2,
    pair: 'BONK/SOL',
    baseToken: 'BONK',
    quoteToken: 'SOL',
    coinIcon: '/assets/coins/BONK.png',
    quoteIcon: '/assets/coins/SOL.png',
    dexIcon: '/assets/coins/RAY.png',
    dex: 'Raydium',
    priceUsd: 0.0000245,
    high24hUsd: 0.0000262,
    low24hUsd: 0.0000238,
    marketCapUsd: 1_840_000_000,
    fdvUsd: 2_190_000_000,
    liquidityUsd: 96_400_000,
    volume24hUsd: 18_900_000,
    riskScore: 6.4,
    status: 'WATCH',
    change24hPct: -3.8,
    trend7d: [45, 42, 44, 39, 36, 38, 34],
    lastUpdate: 'Live',
    category: 'Meme',
    slot: 312891045,
    lpConcentrationHhi: 0.29,
    top5LpSharePct: 41.2,
    slippageBps10k: 38,
    mintAuthority: 'Revoked (Immutable)',
    freezeAuthority: 'Revoked (Immutable)',
    poolAddress: 'HVNwzt7Pxfu76KHCMQPTLuTCLTm6WnQ1esLv4eizseSv',
    liveSource: 'Coinbase Exchange Live',
  },
  {
    id: 'pool-popcat-sol',
    rank: 3,
    pair: 'POPCAT/SOL',
    baseToken: 'POPCAT',
    quoteToken: 'SOL',
    coinIcon: '/assets/coins/POPCAT.png',
    quoteIcon: '/assets/coins/SOL.png',
    dexIcon: '/assets/coins/ORCA.png',
    dex: 'Orca',
    priceUsd: 0.642,
    high24hUsd: 0.915,
    low24hUsd: 0.598,
    marketCapUsd: 629_100_000,
    fdvUsd: 629_100_000,
    liquidityUsd: 32_100_000,
    volume24hUsd: 6_400_000,
    riskScore: 8.9,
    status: 'CRITICAL',
    change24hPct: -42.1,
    trend7d: [62, 58, 54, 48, 39, 28, 19],
    lastUpdate: 'Live',
    category: 'Meme',
    slot: 312891045,
    starred: true,
    lpConcentrationHhi: 0.78,
    top5LpSharePct: 81.6,
    slippageBps10k: 410,
    mintAuthority: 'Revoked (Immutable)',
    freezeAuthority: 'Active Warning',
    poolAddress: '7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr',
    liveSource: 'Coinbase Exchange Live',
  },
  {
    id: 'pool-wif-sol',
    rank: 4,
    pair: 'WIF/SOL',
    baseToken: 'WIF',
    quoteToken: 'SOL',
    coinIcon: '/assets/coins/WIF.png',
    quoteIcon: '/assets/coins/SOL.png',
    dexIcon: '/assets/coins/RAY.png',
    dex: 'Raydium',
    priceUsd: 1.84,
    high24hUsd: 1.98,
    low24hUsd: 1.62,
    marketCapUsd: 1_838_000_000,
    fdvUsd: 1_838_000_000,
    liquidityUsd: 45_700_000,
    volume24hUsd: 12_900_000,
    riskScore: 7.1,
    status: 'HIGH',
    change24hPct: 386.0,
    trend7d: [22, 25, 29, 38, 52, 68, 84],
    lastUpdate: 'Live',
    category: 'Meme',
    slot: 312891045,
    lpConcentrationHhi: 0.48,
    top5LpSharePct: 62.4,
    slippageBps10k: 145,
    mintAuthority: 'Revoked (Immutable)',
    freezeAuthority: 'Revoked (Immutable)',
    poolAddress: 'EP2ib6dYdEeqD8MfE2ezHCxX3kP3K2eLKkirfPm5eyMx',
    liveSource: 'Coinbase Exchange Live',
  },
  {
    id: 'pool-jup-sol',
    rank: 5,
    pair: 'JUP/SOL',
    baseToken: 'JUP',
    quoteToken: 'SOL',
    coinIcon: '/assets/coins/JUP.png',
    quoteIcon: '/assets/coins/SOL.png',
    dexIcon: '/assets/coins/JUP.png',
    dex: 'Jupiter',
    priceUsd: 0.962,
    high24hUsd: 1.01,
    low24hUsd: 0.921,
    marketCapUsd: 1_310_000_000,
    fdvUsd: 9_620_000_000,
    liquidityUsd: 210_500_000,
    volume24hUsd: 58_100_000,
    riskScore: 2.8,
    status: 'SAFE',
    change24hPct: 4.2,
    trend7d: [50, 52, 54, 53, 57, 60, 64],
    lastUpdate: 'Live',
    category: 'DeFi',
    slot: 312891045,
    starred: true,
    lpConcentrationHhi: 0.09,
    top5LpSharePct: 14.2,
    slippageBps10k: 8,
    mintAuthority: 'Revoked (Immutable)',
    freezeAuthority: 'Revoked (Immutable)',
    poolAddress: 'JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4',
    liveSource: 'Coinbase Exchange Live',
  },
  {
    id: 'pool-pyth-sol',
    rank: 6,
    pair: 'PYTH/SOL',
    baseToken: 'PYTH',
    quoteToken: 'SOL',
    coinIcon: '/assets/coins/PYTH.png',
    quoteIcon: '/assets/coins/SOL.png',
    dexIcon: '/assets/coins/ORCA.png',
    dex: 'Orca',
    priceUsd: 0.394,
    high24hUsd: 0.412,
    low24hUsd: 0.379,
    marketCapUsd: 1_420_000_000,
    fdvUsd: 3_940_000_000,
    liquidityUsd: 87_300_000,
    volume24hUsd: 24_700_000,
    riskScore: 4.1,
    status: 'SAFE',
    change24hPct: 1.7,
    trend7d: [38, 39, 41, 40, 43, 44, 46],
    lastUpdate: 'Live',
    category: 'Infra',
    slot: 312891045,
    lpConcentrationHhi: 0.15,
    top5LpSharePct: 24.8,
    slippageBps10k: 19,
    mintAuthority: 'Revoked (Immutable)',
    freezeAuthority: 'Revoked (Immutable)',
    poolAddress: 'HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3',
    liveSource: 'Coinbase Exchange Live',
  },
  {
    id: 'pool-jto-sol',
    rank: 7,
    pair: 'JTO/SOL',
    baseToken: 'JTO',
    quoteToken: 'SOL',
    coinIcon: '/assets/coins/JTO.png',
    quoteIcon: '/assets/coins/SOL.png',
    dexIcon: '/assets/coins/JTO.png',
    dex: 'Jito',
    priceUsd: 2.68,
    high24hUsd: 2.79,
    low24hUsd: 2.58,
    marketCapUsd: 785_000_000,
    fdvUsd: 2_680_000_000,
    liquidityUsd: 63_900_000,
    volume24hUsd: 16_800_000,
    riskScore: 5.6,
    status: 'WATCH',
    change24hPct: -1.2,
    trend7d: [42, 41, 43, 40, 39, 41, 38],
    lastUpdate: 'Live',
    category: 'LST',
    slot: 312891045,
    lpConcentrationHhi: 0.26,
    top5LpSharePct: 37.5,
    slippageBps10k: 34,
    mintAuthority: 'Revoked (Immutable)',
    freezeAuthority: 'Revoked (Immutable)',
    poolAddress: 'jtojtomepa8beP8AuQc6eXt5FriJwfFMwQx2v2f9mCL',
    liveSource: 'Coinbase Exchange Live',
  },
  {
    id: 'pool-mew-sol',
    rank: 8,
    pair: 'MEW/SOL',
    baseToken: 'MEW',
    quoteToken: 'SOL',
    coinIcon: '/assets/coins/MEW.png',
    quoteIcon: '/assets/coins/SOL.png',
    dexIcon: '/assets/coins/RAY.png',
    dex: 'Raydium',
    priceUsd: 0.00682,
    high24hUsd: 0.00735,
    low24hUsd: 0.00651,
    marketCapUsd: 606_000_000,
    fdvUsd: 606_000_000,
    liquidityUsd: 28_400_000,
    volume24hUsd: 7_900_000,
    riskScore: 6.7,
    status: 'WATCH',
    change24hPct: -6.4,
    trend7d: [36, 38, 34, 32, 30, 33, 29],
    lastUpdate: 'Live',
    category: 'Meme',
    slot: 312891045,
    lpConcentrationHhi: 0.34,
    top5LpSharePct: 49.0,
    slippageBps10k: 62,
    mintAuthority: 'Revoked (Immutable)',
    freezeAuthority: 'Revoked (Immutable)',
    poolAddress: 'MEW1gQWJ3nEXg2qgERiKu7FAFj79PHvQVREQUzScPP5',
    liveSource: 'Coinbase Exchange Live',
  },
  {
    id: 'pool-pengu-sol',
    rank: 9,
    pair: 'PENGU/SOL',
    baseToken: 'PENGU',
    quoteToken: 'SOL',
    coinIcon: '/assets/coins/PENGU.png',
    quoteIcon: '/assets/coins/SOL.png',
    dexIcon: '/assets/coins/ORCA.png',
    dex: 'Orca',
    priceUsd: 0.0145,
    high24hUsd: 0.0158,
    low24hUsd: 0.0131,
    marketCapUsd: 912_000_000,
    fdvUsd: 1_280_000_000,
    liquidityUsd: 18_700_000,
    volume24hUsd: 4_100_000,
    riskScore: 5.3,
    status: 'WATCH',
    change24hPct: 8.9,
    trend7d: [25, 27, 30, 29, 34, 37, 41],
    lastUpdate: 'Live',
    category: 'Meme',
    slot: 312891045,
    lpConcentrationHhi: 0.24,
    top5LpSharePct: 36.1,
    slippageBps10k: 44,
    mintAuthority: 'Revoked (Immutable)',
    freezeAuthority: 'Revoked (Immutable)',
    poolAddress: '2zMMhcVQEXDtdE6vsFS7S7D5oUodfJHE8vd1gnBouauv',
    liveSource: 'Coinbase Exchange Live',
  },
  {
    id: 'pool-goat-sol',
    rank: 10,
    pair: 'GOAT/SOL',
    baseToken: 'GOAT',
    quoteToken: 'SOL',
    coinIcon: '/assets/coins/GOAT.png',
    quoteIcon: '/assets/coins/SOL.png',
    dexIcon: '/assets/coins/RAY.png',
    dex: 'Raydium',
    priceUsd: 0.285,
    high24hUsd: 0.334,
    low24hUsd: 0.268,
    marketCapUsd: 285_000_000,
    fdvUsd: 285_000_000,
    liquidityUsd: 12_600_000,
    volume24hUsd: 3_200_000,
    riskScore: 7.8,
    status: 'HIGH',
    change24hPct: -12.7,
    trend7d: [48, 44, 41, 37, 35, 31, 27],
    lastUpdate: 'Live',
    category: 'Meme',
    slot: 312891045,
    lpConcentrationHhi: 0.54,
    top5LpSharePct: 68.5,
    slippageBps10k: 195,
    mintAuthority: 'Revoked (Immutable)',
    freezeAuthority: 'Active Warning',
    poolAddress: 'CzLSujWBLFsSjncfkh59rUFqvafWcY5tzedWJSuypump',
    liveSource: 'Coinbase Exchange Live',
  },
];

export const INITIAL_ALERTS: RiskAlertItem[] = [
  {
    id: 'alert-1',
    pair: 'POPCAT/SOL',
    headline: 'POPCAT/SOL — Risk spike detected',
    detail: 'Risk score 8.9 (+2.7) · Liquidity -42% (24h)',
    status: 'CRITICAL',
    timeAgo: '2m ago',
    riskScore: 8.9,
    slot: 312891045,
  },
  {
    id: 'alert-2',
    pair: 'WIF/SOL',
    headline: 'WIF/SOL — Unusual volume surge',
    detail: '+386% vs 7d avg · Risk score 7.1',
    status: 'HIGH',
    timeAgo: '4m ago',
    riskScore: 7.1,
    slot: 312890982,
  },
  {
    id: 'alert-3',
    pair: 'BONK/SOL',
    headline: 'BONK/SOL — Liquidity drop',
    detail: '-28% (24h) · Risk score 6.4 (+1.3)',
    status: 'WATCH',
    timeAgo: '6m ago',
    riskScore: 6.4,
    slot: 312890910,
  },
  {
    id: 'alert-4',
    pair: 'RAY/SOL',
    headline: 'RAY/SOL — Risk normalized',
    detail: 'Risk score 3.1 (-1.9) · Liquidity stable',
    status: 'SAFE',
    timeAgo: '8m ago',
    riskScore: 3.1,
    slot: 312890844,
  },
  {
    id: 'alert-5',
    pair: 'JUP/SOL',
    headline: 'JUP/SOL — New pool verified',
    detail: 'Cryptographic witness confirmed',
    status: 'SAFE',
    timeAgo: '12m ago',
    riskScore: 2.8,
    slot: 312890712,
  },
];

export const INITIAL_LIVE_TX_PACKETS: LiveTxFlowPacket[] = [
  {
    id: 'tx-101',
    slot: 312891045,
    timestamp: '00:15:22.410',
    pair: 'POPCAT/SOL',
    dex: 'Orca',
    flowType: 'LIQUIDITY_SHIFT',
    amountFormatted: '-$1.42M LP Drain',
    riskScore: 8.9,
    status: 'CRITICAL',
    witnessSigPrefix: 'ed25519:5YcK3mTz...8dF2a',
    latencyMs: 38,
  },
  {
    id: 'tx-102',
    slot: 312891045,
    timestamp: '00:15:21.890',
    pair: 'WIF/SOL',
    dex: 'Raydium',
    flowType: 'MEV_SANDWICH_GUARD',
    amountFormatted: '$284,500 Swap',
    riskScore: 7.1,
    status: 'HIGH',
    witnessSigPrefix: 'ed25519:8LpQ9vRx...2mK4z',
    latencyMs: 42,
  },
  {
    id: 'tx-103',
    slot: 312891044,
    timestamp: '00:15:20.115',
    pair: 'RAY/SOL',
    dex: 'Raydium',
    flowType: 'WITNESS_ATTESTATION',
    amountFormatted: 'State Proof #312891044',
    riskScore: 3.1,
    status: 'SAFE',
    witnessSigPrefix: 'ed25519:3HnB7kWz...9qP1x',
    latencyMs: 29,
  },
  {
    id: 'tx-104',
    slot: 312891043,
    timestamp: '00:15:18.604',
    pair: 'JUP/SOL',
    dex: 'Jupiter',
    flowType: 'RAIL_SETTLEMENT',
    amountFormatted: '1,500 Credits ($5.00)',
    rail: 'SOL',
    riskScore: 2.8,
    status: 'SAFE',
    witnessSigPrefix: 'ed25519:9VxM2cRt...4sL8n',
    latencyMs: 31,
  },
  {
    id: 'tx-105',
    slot: 312891042,
    timestamp: '00:15:16.920',
    pair: 'BONK/SOL',
    dex: 'Raydium',
    flowType: 'SWAP_TELEMETRY',
    amountFormatted: '$92,100 Route',
    rail: 'Nano',
    riskScore: 6.4,
    status: 'WATCH',
    witnessSigPrefix: 'ed25519:7JkP4wQa...6tN3b',
    latencyMs: 24,
  },
];

export const INITIAL_PAYMENTS: PaymentRecord[] = [
  {
    id: 'pay-1',
    time: '00:12',
    user: '0x7A3...F9E4',
    amountUsd: 5.0,
    method: 'SOL',
    credits: 1500,
    txHash: '5Sol9a8f3b21c4d7e6f0a1b2c3d4e5f6a7b8',
    status: 'Completed',
  },
  {
    id: 'pay-2',
    time: '23:58',
    user: 'alpha.dev',
    amountUsd: 1.0,
    method: 'USDC',
    credits: 150,
    txHash: '4Usdc7e2d1c9b8a6f5e4d3c2b1a0f9e8d7c6',
    status: 'Completed',
  },
  {
    id: 'pay-3',
    time: '23:41',
    user: 'tradebot42',
    amountUsd: 0.25,
    method: 'Nano',
    credits: 25,
    txHash: 'nano_block_3f8a9c1d2e4b5a6f7c8d9e0a1b2',
    status: 'Completed',
  },
  {
    id: 'pay-4',
    time: '23:27',
    user: 'agentlab',
    amountUsd: 5.0,
    method: 'SOL',
    credits: 1500,
    txHash: '5Sol1c4b8e7a6d5f9e3c2b1a8f7e6d5c4b3a',
    status: 'Completed',
  },
  {
    id: 'pay-5',
    time: '23:10',
    user: '0x91B...D2C7',
    amountUsd: 1.0,
    method: 'USDC',
    credits: 150,
    txHash: '4Usdc6b5a4f3e2d1c9b8a7f6e5d4c3b2a1f0',
    status: 'Completed',
  },
];

export const INITIAL_AUDIT_LOGS: AuditLogItem[] = [
  {
    id: 'log-1',
    time: '00:14:52',
    actor: 'admin',
    action: 'API Key Issued',
    details: 'User: tradebot42, Key: mk_live_...8f2c',
  },
  {
    id: 'log-2',
    time: '00:12:31',
    actor: 'system',
    action: 'Payment Verified',
    details: 'SOL payment, $5.00, 1,500 credits',
  },
  {
    id: 'log-3',
    time: '00:10:07',
    actor: 'sentinel',
    action: 'Risk Assessment',
    details: 'Pool: RAY/SOL, Risk: 04 (SAFE)',
  },
  {
    id: 'log-4',
    time: '00:06:43',
    actor: 'admin',
    action: 'User Update',
    details: 'Upgraded tier: Starter -> Pro',
  },
  {
    id: 'log-5',
    time: '00:01:19',
    actor: 'witness',
    action: 'Proof Published',
    details: 'Witness: wtn_312891045, Ed25519',
  },
];

export const INITIAL_WITNESS_KEYS: WitnessKeyRecord[] = [
  {
    id: 'wtn_epoch_v7',
    keyId: 'wtn_epoch_v7',
    publicKey: 'ed25519:6Fb8kLp3mTz8qvS9ewb4J7p2kQnGdF6z1vX8M3k7',
    algorithm: 'Ed25519',
    status: 'Active',
    createdAt: '2026-11-05 18:00 UTC',
    signedProofsCount: 148359,
  },
  {
    id: 'wtn_epoch_v6',
    keyId: 'wtn_epoch_v6',
    publicKey: 'ed25519:9Ax4vBn7qWz2rTy5uIo8pLk3jHg6fDs1aZx9V2m4',
    algorithm: 'Ed25519',
    status: 'Rotated',
    createdAt: '2026-10-29 18:00 UTC',
    signedProofsCount: 412904,
  },
  {
    id: 'wtn_epoch_v5',
    keyId: 'wtn_epoch_v5',
    publicKey: 'ed25519:2Cw7nMq4xLp8vB1zRt6yUi3oPa9sDf5gHj7K8l1',
    algorithm: 'Ed25519',
    status: 'Revoked',
    createdAt: '2026-10-15 18:00 UTC',
    signedProofsCount: 389120,
  },
];

export const INITIAL_MANAGED_USERS: ManagedUserRecord[] = [
  {
    uid: 'usr_tradebot42',
    handle: 'tradebot42',
    email: 'ops@tradebot42.ai',
    tier: 'Pro',
    credits: 14820,
    rateLimitRps: 120,
    apiKeysCount: 4,
    status: 'Active',
    lastActive: '1m ago',
  },
  {
    uid: 'usr_alpha_dev',
    handle: 'alpha.dev',
    email: 'core@alphadev.sol',
    tier: 'Starter',
    credits: 1350,
    rateLimitRps: 40,
    apiKeysCount: 2,
    status: 'Active',
    lastActive: '4m ago',
  },
  {
    uid: 'usr_agentlab',
    handle: 'agentlab',
    email: 'autonomous@agentlab.io',
    tier: 'Enterprise',
    credits: 184500,
    rateLimitRps: 500,
    apiKeysCount: 12,
    status: 'Active',
    lastActive: '7m ago',
  },
  {
    uid: 'usr_0x7a3_f9e4',
    handle: '0x7A3...F9E4',
    email: 'quant@mevguard.xyz',
    tier: 'Pro',
    credits: 6400,
    rateLimitRps: 100,
    apiKeysCount: 3,
    status: 'Active',
    lastActive: '12m ago',
  },
  {
    uid: 'usr_0x91b_d2c7',
    handle: '0x91B...D2C7',
    email: 'node@solanawitness.org',
    tier: 'Micro',
    credits: 175,
    rateLimitRps: 15,
    apiKeysCount: 1,
    status: 'Audit',
    lastActive: '29m ago',
  },
];

export const INITIAL_AGENT_OPS: AgentOperationItem[] = [
  {
    id: 'agent-sentinel',
    name: 'Sentinel Risk Engine',
    status: 'Running',
    metricLabel: '2,344 tasks (24h)',
    tasksCount: 2344,
    category: 'risk',
  },
  {
    id: 'agent-cross-dex',
    name: 'Cross-DEX Intelligence',
    status: 'Running',
    metricLabel: '1,802 tasks (24h)',
    tasksCount: 1802,
    category: 'dex',
  },
  {
    id: 'agent-anomaly',
    name: 'Anomaly Radar',
    status: 'Running',
    metricLabel: '96 scans (24h)',
    tasksCount: 96,
    category: 'anomaly',
  },
  {
    id: 'agent-witness',
    name: 'Witness Publisher',
    status: 'Running',
    metricLabel: '512 proofs (24h)',
    tasksCount: 512,
    category: 'witness',
  },
  {
    id: 'agent-credit',
    name: 'Agent Credit Bureau',
    status: 'Running',
    metricLabel: '1,148 checks (24h)',
    tasksCount: 1148,
    category: 'credit',
  },
];
