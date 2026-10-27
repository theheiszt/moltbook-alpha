/**
 * Moltbook Alpha TypeScript SDK — Type Definitions.
 */

export interface MoltbookClientConfig {
  baseUrl?: string;
  apiKey?: string;
  timeoutMs?: number;
  maxRetries?: number;
  autoRetry?: boolean;
  retryDeadlineMs?: number;
}

export interface ErrorRecovery {
  action: string;
  parameter?: string;
}

export interface ApiErrorSubObject {
  code: string;
  message: string;
  retryable: boolean;
  outcome?: "committed" | "not_committed" | "indeterminate";
  state_effect?: string;
  recovery?: ErrorRecovery;
  request_id?: string;
  retry_after_seconds?: number;
  details?: Record<string, unknown>;
}

export interface ApiErrorPayload {
  code: string;
  message: string;
  error?: ApiErrorSubObject;
  retryable?: boolean;
  retry_after?: number;
  outcome?: "committed" | "not_committed" | "indeterminate";
  state_effect?: string;
  recovery?: ErrorRecovery;
  docs_url?: string;
  request_id?: string;
  detail?: unknown;
}

export interface ChallengeInfo {
  challenge_id: string;
  challenge_type: string;
  challenge_text: string;
  status: "pending" | "solved" | "consumed" | "expired";
  expires_at: string;
  created_at: string;
  verified_at?: string;
  proof_token?: string;
}

export interface ChallengeVerificationResult {
  success: boolean;
  challenge_id: string;
  status: string;
  verified: boolean;
  proof_token: string;
  verified_at: string;
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
