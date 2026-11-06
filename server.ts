import express, { Request, Response, NextFunction } from 'express';
import path from 'path';
import { fileURLToPath } from 'url';
import dotenv from 'dotenv';
import {
  VerifiedSessionContext,
  authorizeAction,
  enforceRateLimit,
  validateAgentEvidenceSubmission,
  validateSentinelAssessmentRequest,
  processVerifiedSettlementRequest,
  issueScopedApiKey,
  getApiKeyMetadata,
  revokeScopedApiKey,
  verifyAndExtractSessionToken,
  verifyFirebaseIdTokenAndIssueSession,
  revokeServerSessionToken,
  rotateSessionSigningSecret,
  signServerEd25519Payload,
  verifyServerEd25519Payload,
  validateAutomationBotConfig,
} from './src/services/securityEngine';
import {
  canonicalizeJsonRfc8785,
  lookupAgentDossier,
} from './src/utils/cryptoEngine';

dotenv.config();

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export interface TokenLiveTelemetry {
  symbol: string;
  solanaMintAddress: string;
  priceUsd: number | null;
  change24hPct: number | null;
  high24hUsd: number | null;
  low24hUsd: number | null;
  volume24hUsd: number | null;
  marketCapUsd: number | null;
  fdvUsd: number | null;
  stats24hAvailable: boolean;
  priceProvenance:
    | 'COINBASE_EXCHANGE_LIVE'
    | 'COINBASE_V2_SPOT_TICKER_UNVERIFIED_CHAIN'
    | 'UNAVAILABLE_UPSTREAM_SIMULATED_FALLBACK';
  source:
    | 'Coinbase Exchange Live'
    | 'Coinbase Spot Only (24h Stats Simulated Demo)'
    | 'Simulated Demo Fallback (Upstream Unavailable)';
  simulatedDemoFallback: {
    isSimulatedDemo: true;
    priceUsd: number;
    change24hPct: number;
    high24hUsd: number;
    low24hUsd: number;
    volume24hUsd: number;
    marketCapUsd: number;
    fdvUsd: number;
  };
  updatedAtIso: string;
}

const TRACKED_TOKENS: Array<{
  symbol: string;
  solanaMintAddress: string;
  coinbaseProduct: string | null;
  allowCoinbaseV2SpotFallback: boolean;
  fallbackPrice: number;
  fallbackChange24hPct: number;
  fallbackVolume24hUsd: number;
  circulatingSupply: number;
  totalSupply: number;
}> = [
  {
    symbol: 'SOL',
    solanaMintAddress: 'So11111111111111111111111111111111111111112',
    coinbaseProduct: 'SOL-USD',
    allowCoinbaseV2SpotFallback: true,
    fallbackPrice: 185.2,
    fallbackChange24hPct: 2.3,
    fallbackVolume24hUsd: 3_420_000_000,
    circulatingSupply: 488_000_000,
    totalSupply: 594_000_000,
  },
  {
    symbol: 'RAY',
    solanaMintAddress: '4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R',
    coinbaseProduct: null,
    allowCoinbaseV2SpotFallback: true,
    fallbackPrice: 3.42,
    fallbackChange24hPct: 2.9,
    fallbackVolume24hUsd: 42_700_000,
    circulatingSupply: 290_800_000,
    totalSupply: 555_000_000,
  },
  {
    symbol: 'BONK',
    solanaMintAddress: 'DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263',
    coinbaseProduct: 'BONK-USD',
    allowCoinbaseV2SpotFallback: true,
    fallbackPrice: 0.0000245,
    fallbackChange24hPct: -3.8,
    fallbackVolume24hUsd: 18_900_000,
    circulatingSupply: 75_100_000_000_000,
    totalSupply: 88_800_000_000_000,
  },
  {
    symbol: 'POPCAT',
    solanaMintAddress: '7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr',
    coinbaseProduct: null,
    allowCoinbaseV2SpotFallback: true,
    fallbackPrice: 0.642,
    fallbackChange24hPct: -42.1,
    fallbackVolume24hUsd: 6_400_000,
    circulatingSupply: 979_970_000,
    totalSupply: 979_970_000,
  },
  {
    symbol: 'WIF',
    solanaMintAddress: 'EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm',
    coinbaseProduct: 'WIF-USD',
    allowCoinbaseV2SpotFallback: true,
    fallbackPrice: 1.84,
    fallbackChange24hPct: 386.0,
    fallbackVolume24hUsd: 12_900_000,
    circulatingSupply: 998_900_000,
    totalSupply: 998_900_000,
  },
  {
    // Note (SC11-F06 / Gate 5): Coinbase v2 `/prices/JUP-USD/spot` resolves to legacy ERC-20 Jupiter Project ($0.00024).
    // Disable v2 spot fallback for JUP if Exchange `JUP-USD` stats are unavailable.
    symbol: 'JUP',
    solanaMintAddress: 'JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN',
    coinbaseProduct: 'JUP-USD',
    allowCoinbaseV2SpotFallback: false,
    fallbackPrice: 0.962,
    fallbackChange24hPct: 4.2,
    fallbackVolume24hUsd: 58_100_000,
    circulatingSupply: 1_350_000_000,
    totalSupply: 10_000_000_000,
  },
  {
    symbol: 'PYTH',
    solanaMintAddress: 'HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3',
    coinbaseProduct: 'PYTH-USD',
    allowCoinbaseV2SpotFallback: true,
    fallbackPrice: 0.394,
    fallbackChange24hPct: 1.7,
    fallbackVolume24hUsd: 24_700_000,
    circulatingSupply: 3_625_000_000,
    totalSupply: 10_000_000_000,
  },
  {
    symbol: 'JTO',
    solanaMintAddress: 'jtojtomepa8beP8AuQc6eXt5FriJwfFMwQx2v2f9mCL',
    coinbaseProduct: 'JTO-USD',
    allowCoinbaseV2SpotFallback: true,
    fallbackPrice: 2.68,
    fallbackChange24hPct: -1.2,
    fallbackVolume24hUsd: 16_800_000,
    circulatingSupply: 293_000_000,
    totalSupply: 1_000_000_000,
  },
  {
    symbol: 'MEW',
    solanaMintAddress: 'MEW1gQWJ3nEXg2qgERiKu7FAFj79PHvQVREQUzScPP5',
    coinbaseProduct: 'MEW-USD',
    allowCoinbaseV2SpotFallback: true,
    fallbackPrice: 0.00682,
    fallbackChange24hPct: -6.4,
    fallbackVolume24hUsd: 7_900_000,
    circulatingSupply: 88_888_888_888,
    totalSupply: 88_888_888_888,
  },
  {
    symbol: 'PENGU',
    solanaMintAddress: '2zMMhcVQEXDtdE6vsFS7S7D5oUodfJHE8vd1gnBouauv',
    coinbaseProduct: 'PENGU-USD',
    allowCoinbaseV2SpotFallback: true,
    fallbackPrice: 0.0145,
    fallbackChange24hPct: 8.9,
    fallbackVolume24hUsd: 4_100_000,
    circulatingSupply: 62_860_000_000,
    totalSupply: 88_888_888_888,
  },
  {
    symbol: 'GOAT',
    solanaMintAddress: 'CzLSujWBLFsSjncfkh59rUFqvafWcY5tzedWJSuypump',
    coinbaseProduct: null,
    allowCoinbaseV2SpotFallback: true,
    fallbackPrice: 0.285,
    fallbackChange24hPct: -12.7,
    fallbackVolume24hUsd: 3_200_000,
    circulatingSupply: 999_990_000,
    totalSupply: 1_000_000_000,
  },
];

let cachedTelemetry: {
  timestamp: number;
  solPriceUsd: number;
  tokens: Record<string, TokenLiveTelemetry>;
  providerSummary: string;
  sentinelScoringMode: 'SIMULATED_DEMO';
} | null = null;

async function fetchWithTimeout(
  url: string,
  options: RequestInit = {},
  timeoutMs = 4500
): Promise<globalThis.Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, {
      ...options,
      signal: controller.signal,
      headers: {
        Accept: 'application/json',
        'User-Agent': 'MoltAlpha-Sentinel-Telemetry/2.0',
        ...(options.headers || {}),
      },
    });
  } finally {
    clearTimeout(timer);
  }
}

async function fetchCoinbaseStats(product: string): Promise<{
  priceUsd: number;
  open24h: number;
  high24hUsd: number;
  low24hUsd: number;
  volumeBase24h: number;
  change24hPct: number;
} | null> {
  if (!/^[A-Z0-9]{2,10}-USD$/.test(product)) return null;
  try {
    const res = await fetchWithTimeout(
      `https://api.exchange.coinbase.com/products/${product}/stats`
    );
    if (!res.ok) return null;
    const data = (await res.json()) as {
      open?: string;
      high?: string;
      low?: string;
      last?: string;
      volume?: string;
    };
    const last = Number(data.last || 0);
    const open = Number(data.open || last);
    const high = Number(data.high || last);
    const low = Number(data.low || last);
    const volume = Number(data.volume || 0);
    if (!last || Number.isNaN(last) || last <= 0) return null;
    const change24hPct =
      open > 0 ? Number((((last - open) / open) * 100).toFixed(2)) : 0;
    return {
      priceUsd: last,
      open24h: open,
      high24hUsd: high,
      low24hUsd: low,
      volumeBase24h: volume,
      change24hPct,
    };
  } catch {
    return null;
  }
}

async function fetchCoinbaseSpotPrice(
  symbol: string,
  fallbackPrice: number
): Promise<number | null> {
  if (!/^[A-Z0-9]{2,10}$/.test(symbol)) return null;
  try {
    const res = await fetchWithTimeout(
      `https://api.coinbase.com/v2/prices/${symbol}-USD/spot`
    );
    if (!res.ok) return null;
    const json = (await res.json()) as {
      data?: { amount?: string };
    };
    const amount = Number(json?.data?.amount || 0);
    if (!amount || Number.isNaN(amount) || amount <= 0) return null;
    if (amount < fallbackPrice * 0.02 || amount > fallbackPrice * 50) {
      return null;
    }
    return amount;
  } catch {
    return null;
  }
}

async function getLiveMarketTelemetry() {
  const now = Date.now();
  if (cachedTelemetry && now - cachedTelemetry.timestamp < 20_000) {
    return cachedTelemetry;
  }

  const solCbStats = await fetchCoinbaseStats('SOL-USD');
  const solSpot =
    solCbStats?.priceUsd ?? (await fetchCoinbaseSpotPrice('SOL', 185.2)) ?? 185.2;

  const results = await Promise.all(
    TRACKED_TOKENS.map(async (token) => {
      const cbStats =
        token.symbol === 'SOL'
          ? solCbStats
          : token.coinbaseProduct
            ? await fetchCoinbaseStats(token.coinbaseProduct)
            : null;

      const cbSpot =
        !cbStats && token.allowCoinbaseV2SpotFallback
          ? await fetchCoinbaseSpotPrice(token.symbol, token.fallbackPrice)
          : null;

      // Gate 5 Remediation: Never silently invent 24h change, high, low, or volume when Coinbase Exchange 24h stats are unavailable.
      // Return null on live 24h fields when cbStats is missing, and isolate demo values inside simulatedDemoFallback.
      const livePriceUsd = cbStats?.priceUsd ?? cbSpot ?? null;
      const stats24hAvailable = Boolean(cbStats);
      const demoPrice = livePriceUsd ?? token.fallbackPrice;

      const priceProvenance: TokenLiveTelemetry['priceProvenance'] = cbStats
        ? 'COINBASE_EXCHANGE_LIVE'
        : cbSpot
          ? 'COINBASE_V2_SPOT_TICKER_UNVERIFIED_CHAIN'
          : 'UNAVAILABLE_UPSTREAM_SIMULATED_FALLBACK';

      const source: TokenLiveTelemetry['source'] = cbStats
        ? 'Coinbase Exchange Live'
        : cbSpot
          ? 'Coinbase Spot Only (24h Stats Simulated Demo)'
          : 'Simulated Demo Fallback (Upstream Unavailable)';

      const entry: TokenLiveTelemetry = {
        symbol: token.symbol,
        solanaMintAddress: token.solanaMintAddress,
        priceUsd: livePriceUsd,
        change24hPct: cbStats ? cbStats.change24hPct : null,
        high24hUsd: cbStats ? cbStats.high24hUsd : null,
        low24hUsd: cbStats ? cbStats.low24hUsd : null,
        volume24hUsd:
          cbStats && cbStats.volumeBase24h > 0
            ? cbStats.volumeBase24h * cbStats.priceUsd
            : null,
        marketCapUsd: livePriceUsd ? livePriceUsd * token.circulatingSupply : null,
        fdvUsd: livePriceUsd ? livePriceUsd * token.totalSupply : null,
        stats24hAvailable,
        priceProvenance,
        source,
        simulatedDemoFallback: {
          isSimulatedDemo: true,
          priceUsd: demoPrice,
          change24hPct: token.fallbackChange24hPct,
          high24hUsd: Number((demoPrice * 1.05).toPrecision(5)),
          low24hUsd: Number((demoPrice * 0.95).toPrecision(5)),
          volume24hUsd: token.fallbackVolume24hUsd,
          marketCapUsd: demoPrice * token.circulatingSupply,
          fdvUsd: demoPrice * token.totalSupply,
        },
        updatedAtIso: new Date().toISOString(),
      };
      return entry;
    })
  );

  const tokensMap: Record<string, TokenLiveTelemetry> = {};
  for (const item of results) {
    tokensMap[item.symbol] = item;
  }

  cachedTelemetry = {
    timestamp: now,
    solPriceUsd: solSpot,
    tokens: tokensMap,
    providerSummary: 'Coinbase Exchange Live · Missing 24h Stats Explicitly Null/Isolated',
    sentinelScoringMode: 'SIMULATED_DEMO',
  };

  return cachedTelemetry;
}

/**
 * Extracts and cryptographically validates session context from request headers.
 * Rejects unsigned `dev_session:` tokens (`SC11-F01` remediation).
 */
function extractSessionContext(req: Request): VerifiedSessionContext | null {
  return verifyAndExtractSessionToken(req.headers.authorization);
}

async function startServer() {
  const app = express();
  const PORT = 3000;

  app.use(express.json({ limit: '32kb' }));

  app.use((req: Request, res: Response, next: NextFunction) => {
    res.setHeader('X-Content-Type-Options', 'nosniff');
    res.setHeader('Referrer-Policy', 'strict-origin-when-cross-origin');
    res.setHeader(
      'Permissions-Policy',
      'camera=(), microphone=(), geolocation=(), payment=()'
    );
    res.setHeader(
      'Content-Security-Policy',
      "default-src 'self'; img-src 'self' data: blob: https:; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' data: https://fonts.gstatic.com; script-src 'self' 'unsafe-inline' 'unsafe-eval' https://apis.google.com https://*.firebaseapp.com; frame-src 'self' https://*.firebaseapp.com https://accounts.google.com https://apis.google.com; connect-src 'self' ws: wss: https://*.googleapis.com https://*.firebaseio.com https://*.firebaseapp.com wss://*.firebaseio.com https://api.exchange.coinbase.com https://api.coinbase.com; frame-ancestors *;"
    );

    const origin = req.headers.origin;
    const allowedOriginPattern =
      /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$|\.run\.app$|\.google\.com$/;
    if (origin && allowedOriginPattern.test(origin)) {
      res.setHeader('Access-Control-Allow-Origin', origin);
      res.setHeader('Vary', 'Origin');
    }
    if (req.method === 'OPTIONS') {
      res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
      res.setHeader(
        'Access-Control-Allow-Headers',
        'Content-Type, Authorization, X-Idempotency-Key'
      );
      res.status(204).end();
      return;
    }
    next();
  });

  // Global API Rate Limiter (60 requests / 60s per IP)
  app.use('/api', (req: Request, res: Response, next: NextFunction) => {
    const ip = req.ip || req.socket.remoteAddress || 'unknown_ip';
    const rl = enforceRateLimit(`ip:${ip}`, 60, 60_000);
    if (!rl.allowed) {
      res.status(rl.status).json({ ok: false, code: rl.code, error: rl.message });
      return;
    }
    next();
  });

  // Unified Anti-Privilege-Header Guard across all /api/v1/* endpoints (Remediation for SC11-F08)
  app.use('/api/v1', (req: Request, res: Response, next: NextFunction) => {
    const forgedHeader =
      req.headers['x-molt-role'] ||
      req.headers['x-admin-override'] ||
      req.headers['x-operator-flag'];
    if (forgedHeader) {
      res.status(403).json({
        allowed: false,
        status: 403,
        code: 'FORGED_PRIVILEGE_HEADER_REJECTED',
        message: 'Client-supplied role or administrative override headers are forbidden.',
      });
      return;
    }
    next();
  });

  // ==========================================================================
  // GATE 1 REMEDIATION: AUTHENTICATED SESSION ISSUANCE & REVOCATION ENDPOINTS
  // Validates RS256 Firebase ID Token before issuing a signed molt_sig_v1 token
  // ==========================================================================
  app.post('/api/v1/auth/session', async (req: Request, res: Response) => {
    // Reject any attempt to supply arbitrary uid, email, or role in the request body
    if (
      req.body &&
      (Object.prototype.hasOwnProperty.call(req.body, 'uid') ||
        Object.prototype.hasOwnProperty.call(req.body, 'email') ||
        Object.prototype.hasOwnProperty.call(req.body, 'role'))
    ) {
      res.status(403).json({
        allowed: false,
        status: 403,
        code: 'CLIENT_IDENTITY_INJECTION_BLOCKED',
        message: 'Session issuance derives identity strictly from a verified RS256 Firebase ID token.',
      });
      return;
    }

    const result = await verifyFirebaseIdTokenAndIssueSession(req.headers.authorization);
    res.status(result.status).json(result);
  });

  app.post('/api/v1/auth/revoke', (req: Request, res: Response) => {
    const session = extractSessionContext(req);
    if (!session || !session.sessionJti) {
      res.status(401).json({
        allowed: false,
        status: 401,
        code: 'UNAUTHENTICATED',
        message: 'A valid active session token is required to revoke the session.',
      });
      return;
    }
    const result = revokeServerSessionToken(session.sessionJti);
    res.status(result.status).json(result);
  });

  // ==========================================================================
  // GATE 2 REMEDIATION: TRUSTED BACKEND ED25519 SIGNING & VERIFICATION
  // ==========================================================================
  app.post('/api/v1/witness/attest', (req: Request, res: Response) => {
    const payloadObj = req.body?.payload;
    if (!payloadObj || typeof payloadObj !== 'object') {
      res.status(400).json({
        allowed: false,
        status: 400,
        code: 'INVALID_WITNESS_PAYLOAD',
        message: 'A JSON object payload is required for RFC 8785 canonicalization and Ed25519 signing.',
      });
      return;
    }
    const canonicalJson = canonicalizeJsonRfc8785(payloadObj);
    const attestation = signServerEd25519Payload(canonicalJson);
    res.status(200).json({
      allowed: true,
      status: 200,
      code: 'SERVER_ED25519_ATTESTED',
      canonicalJson,
      ...attestation,
    });
  });

  app.post('/api/v1/witness/verify', (req: Request, res: Response) => {
    const canonicalJson =
      typeof req.body?.canonicalJson === 'string'
        ? req.body.canonicalJson
        : req.body?.payload
          ? canonicalizeJsonRfc8785(req.body.payload)
          : '';
    const signatureBase64Url = String(req.body?.signatureBase64Url || '');
    const keyEpochId = req.body?.keyEpochId ? String(req.body.keyEpochId) : undefined;
    if (!canonicalJson || !signatureBase64Url) {
      res.status(400).json({
        allowed: false,
        status: 400,
        code: 'MISSING_VERIFICATION_FIELDS',
        verified: false,
      });
      return;
    }
    const verified = verifyServerEd25519Payload(
      canonicalJson,
      signatureBase64Url,
      undefined,
      keyEpochId
    );
    res.status(200).json({
      allowed: true,
      status: 200,
      verified,
    });
  });

  // Public Market Quotes from Coinbase Exchange + Explicit Null/Simulated Demo Provenance
  app.get('/api/market-intelligence', async (_req: Request, res: Response) => {
    try {
      const data = await getLiveMarketTelemetry();
      res.json({
        ok: true,
        ...data,
      });
    } catch {
      res.status(500).json({
        ok: false,
        error: 'Failed to fetch market telemetry.',
      });
    }
  });

  // Section 6: Agent Lookup Endpoint (GET /api/v1/sentinel/agents/:id)
  app.get('/api/v1/sentinel/agents/:id', (req: Request, res: Response) => {
    const rawId = String(req.params.id || '').trim();
    if (!/^[a-zA-Z0-9_\-@]{2,64}$/.test(rawId)) {
      res.status(400).json({
        ok: false,
        code: 'INVALID_AGENT_ID',
        error: 'Agent identifier must be 2–64 alphanumeric characters.',
      });
      return;
    }
    const dossier = lookupAgentDossier(rawId);
    const jcsBirthCert = canonicalizeJsonRfc8785(
      JSON.parse(dossier.birthCert.canonicalBirthCertJson)
    );
    const serverEd25519Attestation = signServerEd25519Payload(jcsBirthCert);
    res.json({
      ok: true,
      environmentMode: 'SIMULATED_DEMO',
      isAuthoritative: false,
      dossier,
      serverEd25519Attestation,
    });
  });

  // Section 6: Protected Agent Deliverable Submission (POST /api/v1/jobs/:id/submit)
  app.post('/api/v1/jobs/:id/submit', (req: Request, res: Response) => {
    const session = extractSessionContext(req);
    const idemKey = req.headers['x-idempotency-key'] as string | undefined;
    const result = validateAgentEvidenceSubmission(
      session,
      req.body || {},
      idemKey,
      req.headers as Record<string, string | undefined>
    );
    res.status(result.status).json(result);
  });

  // Section 7: Protected Sentinel Preflight Check (POST /api/v1/sentinel/preflight)
  app.post('/api/v1/sentinel/preflight', (req: Request, res: Response) => {
    const session = extractSessionContext(req);
    const result = validateSentinelAssessmentRequest(
      session,
      req.body || {},
      req.headers as Record<string, string | undefined>
    );
    res.status(result.status).json(result);
  });

  // Section 5 & 8: Protected Sandbox Settlement Verification (POST /api/v1/settlements/verify)
  app.post('/api/v1/settlements/verify', (req: Request, res: Response) => {
    const session = extractSessionContext(req);
    const idemKey = req.headers['x-idempotency-key'] as string | undefined;
    const result = processVerifiedSettlementRequest(
      session,
      req.body || {},
      idemKey,
      req.headers as Record<string, string | undefined>
    );
    res.status(result.status).json(result);
  });

  // Section 8: Protected API Key Issuance, Inspection & Revocation
  app.post('/api/v1/keys/issue', (req: Request, res: Response) => {
    const session = extractSessionContext(req);
    const targetUid = String(req.body?.ownerUid || session?.uid || '');
    const scopes = Array.isArray(req.body?.scopes) ? req.body.scopes : undefined;
    const result = issueScopedApiKey(
      session,
      targetUid,
      scopes,
      req.headers as Record<string, string | undefined>
    );
    res.status(result.status).json(result);
  });

  app.get('/api/v1/keys/:keyId', (req: Request, res: Response) => {
    const session = extractSessionContext(req);
    const result = getApiKeyMetadata(
      session,
      String(req.params.keyId || ''),
      req.headers as Record<string, string | undefined>
    );
    res.status(result.status).json(result);
  });

  app.post('/api/v1/keys/:keyId/revoke', (req: Request, res: Response) => {
    const session = extractSessionContext(req);
    const result = revokeScopedApiKey(
      session,
      String(req.params.keyId || ''),
      req.headers as Record<string, string | undefined>
    );
    res.status(result.status).json(result);
  });

  // Section 3 & 5: Administrative Key Rotation Endpoint (Admin Only + Rate Limited)
  app.post('/api/v1/admin/rotate-key', (req: Request, res: Response) => {
    const session = extractSessionContext(req);
    const rl = enforceRateLimit(`admin_rotate:${session?.uid || 'anon'}`, 3, 60_000);
    if (!rl.allowed) {
      res.status(rl.status).json(rl);
      return;
    }
    const authCheck = authorizeAction(session, 'admin', {
      requireRecentReauthMs: 15 * 60_000,
      clientSuppliedHeaders: req.headers as Record<string, string | undefined>,
    });
    if (!authCheck.allowed) {
      res.status(authCheck.status).json(authCheck);
      return;
    }
    const rotatedHmac = rotateSessionSigningSecret(false);
    res.status(200).json({
      ok: true,
      code: 'SANDBOX_KEY_ROTATED',
      newHmacKid: rotatedHmac.newKid,
      message: 'Rotated witness and session signing key epoch in durable sandbox ledger.',
    });
  });

  // Members-Only Trading & Sniping Bot Registration Endpoint (POST /api/v1/automation/bots)
  app.post('/api/v1/automation/bots', (req: Request, res: Response) => {
    const session = extractSessionContext(req);
    const rl = enforceRateLimit(`automation_bot:${session?.uid || req.ip || 'anon'}`, 15, 60_000);
    if (!rl.allowed) {
      res.status(rl.status).json(rl);
      return;
    }
    const result = validateAutomationBotConfig(
      session,
      req.body || {},
      req.headers as Record<string, string | undefined>
    );
    if (!result.allowed || !result.data) {
      res.status(result.status).json(result);
      return;
    }
    const canonicalManifest = canonicalizeJsonRfc8785(result.data);
    const serverEd25519Attestation = signServerEd25519Payload(canonicalManifest);
    res.status(200).json({
      ...result,
      canonicalManifest,
      serverEd25519Attestation,
    });
  });

  if (process.env.NODE_ENV !== 'production') {
    const { createServer: createViteServer } = await import('vite');
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: 'spa',
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.join(__dirname, 'dist');
    app.use(express.static(distPath));
    app.get('*', (_req, res) => {
      res.sendFile(path.join(distPath, 'index.html'));
    });
  }

  app.listen(PORT, '0.0.0.0', () => {
    console.log(`MoltAlpha Server listening on http://0.0.0.0:${PORT}`);
  });
}

startServer();
