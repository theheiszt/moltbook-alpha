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

export interface WebhookSubscription {
  subscription_id: string;
  target_url: string;
  secret_token: string;
  subscribed_events: string[];
  min_severity: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  created_at: string;
  active: boolean;
}

export interface SubscribeWebhookInput {
  targetUrl: string;
  secretToken: string;
  subscribedEvents?: string[];
  minSeverity?: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
}


// ----------------------------------------------------------------------------
// Core and Metered API Response Models
// ----------------------------------------------------------------------------

export interface IntelSignalsResponse {
  count: number;
  signals: Record<string, unknown>[];
  /** Pass back as `cursor` to fetch the next page; null on the last page. */
  next_cursor?: string | null;
  [key: string]: unknown;
}

export interface IntelOpportunitiesResponse {
  count: number;
  min_profit_pct: number;
  opportunities: Record<string, unknown>[];
  timestamp_utc: number | string;
  /** Pass back as `cursor` to fetch the next page; null on the last page. */
  next_cursor?: string | null;
  [key: string]: unknown;
}

export interface IntelTradingSignalsResponse {
  count: number;
  min_confidence: number | string;
  trading_signals: Record<string, unknown>[];
  timestamp_utc: number | string;
  [key: string]: unknown;
}

export interface IntelMicrostructureOverviewResponse {
  status: string;
  tracked_pool_count: number;
  active_anomaly_count: number;
  depth_bps: number;
  pools: Record<string, unknown>[];
  recent_anomalies: Record<string, unknown>[];
  state_witness_id?: string;
  timestamp_utc: number | string;
  [key: string]: unknown;
}

export interface IntelPoolMicrostructureResponse {
  pool_id: string;
  protocol: string;
  pair: string;
  current_tick?: number;
  current_price: number;
  bid_depth_usd: number;
  ask_depth_usd: number;
  imbalance_ratio: number;
  active_bin_count: number;
  timestamp_utc: number | string;
  raw_bins: Record<string, unknown>[];
  anomalies: Record<string, unknown>[];
  state_witness?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface BriefingLatestResponse {
  success: boolean;
  user_tier: string;
  credits_remaining: number;
  briefing_markdown: string;
  trading_signals: Record<string, unknown>[];
  opportunities: Record<string, unknown>[];
  state_witness_id?: string;
  [key: string]: unknown;
}

export interface DataProductLatestResponse {
  product_id: string;
  snapshot_id: string;
  generated_at: string;
  retrieval_outcome?: string;
  freshness_seconds?: number;
  source_attribution?: Record<string, unknown>;
  state_witness_id?: string;
  usage_receipt?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface AccountQuotaUsageResponse {
  success: boolean;
  key_prefix: string;
  tier: string;
  credits_remaining: number;
  is_active: boolean;
  created_at: string;
  low_credit_warning: boolean;
  entitlement?: Record<string, unknown>;
  credit_lots?: Record<string, unknown>[];
  usage?: Record<string, unknown>;
  rate_limit_state?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface QuantFirstPassageResponse {
  pair: string;
  target_net_pct: number;
  roundtrip_spread_bps: number;
  required_gross_move_pct: number;
  volatility_metrics: Record<string, unknown>;
  two_barrier_analysis: Record<string, unknown>;
  horizon_probabilities: Record<string, unknown>[];
  optimal_target_ladder: Record<string, unknown>[];
  recommended_target_net_pct: number;
  state_witness_id?: string;
  witness_signature?: string;
  generated_at: string;
  cache_status?: string;
  cache_age_seconds?: number;
  [key: string]: unknown;
}

export interface QuantTradeViabilityResponse {
  pair: string;
  target_net_pct: number;
  roundtrip_spread_bps: number;
  required_gross_move_pct: number;
  volatility_metrics: Record<string, unknown>;
  two_barrier_analysis: Record<string, unknown>;
  horizon_probabilities: Record<string, unknown>[];
  optimal_target_ladder: Record<string, unknown>[];
  recommended_target_net_pct: number;
  state_witness_id?: string;
  witness_signature?: string;
  generated_at: string;
  [key: string]: unknown;
}
