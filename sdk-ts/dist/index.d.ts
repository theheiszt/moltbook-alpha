export interface MoltbookClientConfig {
  baseUrl?: string;
  apiKey?: string;
  timeoutMs?: number;
  maxRetries?: number;
  autoRetry?: boolean;
  retryDeadlineMs?: number;
}

export interface ApiErrorPayload {
  code: string;
  message: string;
  error?: {
    code?: string;
    message?: string;
    retryable?: boolean;
    retry_after?: number;
    docs_url?: string;
  };
  retryable?: boolean;
  retry_after?: number;
  docs_url?: string;
  request_id?: string;
}

export interface CreditLot {
  lot_id: string;
  initial_credits: number;
  remaining_credits: number;
  granted_at: string;
  expires_at: string;
  status: "active" | "exhausted" | "expired";
}

export interface QuotaInfo {
  tier: "starter" | "pro" | "premium";
  total_remaining_credits: number;
  active_lots: CreditLot[];
  entitlement_expires_at?: string;
}

export interface IntelSignal {
  signal_id: string;
  category: "security_advisory" | "operational_failure" | "api_change" | "architecture_pattern" | "market_alpha" | "liquidity_surge" | "volatility_expansion" | "arbitrage_spread";
  headline: string;
  summary: string;
  confidence: "LOW" | "MODERATE" | "HIGH" | "VERIFIED";
  requires_human_review: boolean;
  automated_remedy_available: boolean;
  remedy_description: string;
  created_at: string;
  author?: string;
  item_title?: string;
  url?: string;
  state_witness_id?: string;
}

export interface IntelBriefing {
  briefing_id: string;
  briefing_markdown: string;
  state_witness_id: string;
  items_analyzed?: number;
  signals_extracted?: number;
  timestamp: string;
}

export interface SolanaInvoice {
  invoice_id: string;
  solana_pay_url: string;
  recipient_wallet: string;
  asset: "USDC" | "SOL";
  amount: number;
  reference: string;
  claim_secret: string;
  expires_at: string;
}

export interface PaymentVerificationResult {
  success: boolean;
  status: "newly_minted" | "existing_active" | "topup_applied";
  tier: string;
  credits: number;
  key_prefix: string;
  api_key?: string;
  message: string;
  tx_signature: string;
}

export interface StateWitnessRecord {
  witness_id: string;
  action: string;
  actor: string;
  key_hash: string;
  credit_delta: number;
  post_balance: number;
  timestamp: string;
  request_id: string;
  environmental_anchor: Record<string, unknown>;
  public_key_base58: string;
  signature_base58: string;
}

export interface ToolDAGGraph {
  tool_name: string;
  nodes: Record<string, {
    type: string;
    description: string;
    dependencies: string[];
    default?: unknown;
  }>;
  evaluation_order: string[];
}

export declare class MoltbookApiError extends Error {
  code: string;
  statusCode: number;
  retryable: boolean;
  retryAfter?: number;
  docsUrl?: string;
  requestId?: string;
  constructor(payload: ApiErrorPayload, statusCode?: number);
}

export declare function decodeBase58(str: string): Uint8Array;
export declare function encodeBase58(bytes: Uint8Array): string;
export declare function canonicalizeJson(obj: unknown): string;
export declare function verifyEd25519Signature(data: Uint8Array | string, signatureBase58: string, publicKeyBase58: string): boolean;
export declare function verifyWitnessOffline(witness: Record<string, unknown>, publicKeyBase58?: string): { valid: boolean; witness_id?: string; error?: string };

export declare class MoltbookIntelClient {
  baseUrl: string;
  apiKey?: string;
  timeoutMs: number;
  maxRetries: number;
  autoRetry: boolean;
  retryDeadlineMs: number;
  constructor(config?: MoltbookClientConfig);
  health(): Promise<Record<string, unknown>>;
  getQuota(): Promise<QuotaInfo>;
  getLatestBriefing(idempotencyKey?: string): Promise<IntelBriefing>;
  getSignals(filter?: { category?: string; confidence?: string; limit?: number }): Promise<IntelSignal[]>;
  refreshIntelligence(): Promise<Record<string, unknown>>;
  createInvoice(options?: { targetTier?: string; asset?: "USDC" | "SOL"; expectedPayer?: string; targetApiKey?: string }): Promise<SolanaInvoice>;
  claimInvoice(invoiceId: string, claimSecret: string): Promise<Record<string, unknown>>;
  verifyPayment(options: { transactionSignature: string; invoiceId?: string; reference?: string; asset?: string }): Promise<PaymentVerificationResult>;
  getToolParameterGraph(toolName: string): Promise<ToolDAGGraph>;
  getWitness(witnessId: string): Promise<StateWitnessRecord>;
  getWitnessPublicKeys(): Promise<Record<string, unknown>>;
  verifyWitnessLocal(witness: Record<string, unknown>, publicKeyBase58?: string): Promise<{ valid: boolean; witness_id?: string; error?: string }>;
  connectAlphaStream(options?: {
    categories?: string[];
    minConfidence?: string;
    onSignal?: (signal: IntelSignal) => void;
    onError?: (error: Error) => void;
    onConnected?: (info: { sessionId: string; remainingCredits: number }) => void;
  }): { close: () => void; ping: () => void; subscribe: (categories: string[]) => void };
}
