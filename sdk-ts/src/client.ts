/**
 * Moltbook Alpha TypeScript SDK — Main Client.
 * Implements resilient HTTP client with exponential backoff & jitter,
 * WebSocket streaming, offline state witness verification, and Solana settlement.
 */

import {
  MoltbookClientConfig,
  ApiErrorPayload,
  ErrorRecovery,
  QuotaInfo,
  IntelSignal,
  IntelBriefing,
  SolanaInvoice,
  PaymentVerificationResult,
  StateWitnessRecord,
  ToolDAGGraph,
  ChallengeInfo,
  ChallengeVerificationResult,
} from "./types.js";
import { verifyWitnessOffline } from "./crypto.js";

export class MoltbookApiError extends Error {
  public code: string;
  public statusCode: number;
  public retryable: boolean;
  public retryAfter?: number;
  public docsUrl?: string;
  public requestId?: string;
  public outcome: "committed" | "not_committed" | "indeterminate";
  public stateEffect: string;
  public recoveryAction: string;
  public recovery?: ErrorRecovery;

  constructor(payload: ApiErrorPayload, statusCode: number = 500) {
    const msg = payload.message || payload.error?.message || payload.code || "Unknown Moltbook API error";
    super(msg);
    this.name = "MoltbookApiError";
    this.code = payload.code || payload.error?.code || "INTERNAL_ERROR";
    this.statusCode = statusCode;
    this.retryable = Boolean(payload.retryable ?? payload.error?.retryable ?? false);
    this.retryAfter = payload.retry_after ?? payload.error?.retry_after_seconds;
    this.docsUrl = payload.docs_url;
    this.requestId = payload.request_id || payload.error?.request_id;
    this.outcome = payload.outcome ?? payload.error?.outcome ?? "not_committed";
    this.stateEffect = payload.state_effect ?? payload.error?.state_effect ?? "none";
    this.recovery = payload.recovery ?? payload.error?.recovery;
    this.recoveryAction = this.recovery?.action || "inspect_parameters";
  }
}

export class MoltbookIntelClient {
  public baseUrl: string;
  public apiKey?: string;
  public timeoutMs: number;
  public maxRetries: number;
  public autoRetry: boolean;
  public retryDeadlineMs: number;
  private _cachedServerPubKey?: string;

  constructor(config: MoltbookClientConfig = {}) {
    this.baseUrl = (config.baseUrl || "http://127.0.0.1:8080").replace(/\/+$/, "");
    this.apiKey = config.apiKey;
    this.timeoutMs = config.timeoutMs || 15000;
    this.maxRetries = config.maxRetries ?? 3;
    this.autoRetry = config.autoRetry ?? true;
    this.retryDeadlineMs = config.retryDeadlineMs || 30000;
  }

  private async _request<T = unknown>(
    endpoint: string,
    options: {
      method?: string;
      body?: unknown;
      headers?: Record<string, string>;
      authRequired?: boolean;
      idempotencyKey?: string;
    } = {}
  ): Promise<T> {
    const url = `${this.baseUrl}${endpoint}`;
    const method = options.method || "GET";
    const reqHeaders: Record<string, string> = {
      "User-Agent": "@moltbook/intel-sdk/2.0.0",
      Accept: "application/json",
      ...options.headers,
    };

    if (options.body !== undefined) {
      reqHeaders["Content-Type"] = "application/json";
    }

    if (this.apiKey) {
      reqHeaders["Authorization"] = `Bearer ${this.apiKey}`;
      reqHeaders["X-API-KEY"] = this.apiKey;
    } else if (options.authRequired) {
      throw new MoltbookApiError(
        {
          code: "AUTHENTICATION_REQUIRED",
          message: "Endpoint requires an active API key, but client was initialized without one.",
        },
        401
      );
    }

    if (options.idempotencyKey) {
      reqHeaders["Idempotency-Key"] = options.idempotencyKey;
    }

    const startTime = Date.now();
    let retries = 0;

    while (true) {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), this.timeoutMs);

      try {
        const resp = await fetch(url, {
          method,
          headers: reqHeaders,
          body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
          signal: controller.signal,
        });
        clearTimeout(timer);

        if (resp.ok) {
          const text = await resp.text();
          return text ? (JSON.parse(text) as T) : ({} as T);
        }

        const errText = await resp.text();
        let errJson: ApiErrorPayload;
        try {
          errJson = JSON.parse(errText);
        } catch {
          errJson = { code: `HTTP_${resp.status}`, message: errText };
        }

        const reqId = resp.headers.get("x-request-id") || undefined;
        if (reqId && !errJson.request_id) {
          errJson.request_id = reqId;
        }

        // Never retry 402 (Payment Required) or 403 (Forbidden)
        if (resp.status === 402 || resp.status === 403) {
          throw new MoltbookApiError(errJson, resp.status);
        }

        const retryAfterSec = Number(resp.headers.get("retry-after") || errJson.retry_after || 0);
        const isRetryable = errJson.retryable || errJson.error?.retryable || resp.status === 429 || resp.status >= 500;

        const elapsed = Date.now() - startTime;
        if (this.autoRetry && isRetryable && retries < this.maxRetries && elapsed < this.retryDeadlineMs) {
          retries++;
          const baseBackoff = Math.min(10000, 1000 * 1.5 ** retries);
          const jitter = Math.random() * 0.5 + 0.75;
          const waitTime = retryAfterSec > 0 ? retryAfterSec * 1000 : baseBackoff * jitter;
          await new Promise((resolve) => setTimeout(resolve, waitTime));
          continue;
        }

        throw new MoltbookApiError(errJson, resp.status);
      } catch (err: unknown) {
        clearTimeout(timer);
        if (err instanceof MoltbookApiError) {
          throw err;
        }

        const elapsed = Date.now() - startTime;
        if (this.autoRetry && retries < this.maxRetries && elapsed < this.retryDeadlineMs) {
          retries++;
          const waitTime = Math.min(10000, 1000 * 1.5 ** retries) * (Math.random() * 0.5 + 0.75);
          await new Promise((resolve) => setTimeout(resolve, waitTime));
          continue;
        }

        const errMsg = err instanceof Error ? err.message : String(err);
        throw new MoltbookApiError(
          {
            code: "NETWORK_ERROR",
            message: `Connection failed to ${url}: ${errMsg}`,
            retryable: true,
          },
          503
        );
      }
    }
  }

  // --- Diagnostics & Quota ---
  public async health(): Promise<Record<string, unknown>> {
    return this._request<Record<string, unknown>>("/v1/health");
  }

  public async getQuota(): Promise<QuotaInfo> {
    return this._request<QuotaInfo>("/v1/account/quota", { authRequired: true });
  }

  // --- Market Intelligence & Briefings ---
  public async getLatestBriefing(idempotencyKey?: string): Promise<IntelBriefing> {
    return this._request<IntelBriefing>("/v1/intel/latest", {
      authRequired: true,
      idempotencyKey,
    });
  }

  public async getSignals(filter: {
    category?: string;
    confidence?: string;
    limit?: number;
  } = {}): Promise<IntelSignal[]> {
    const params = new URLSearchParams();
    if (filter.limit) params.set("limit", String(filter.limit));
    if (filter.category) params.set("category", filter.category);
    if (filter.confidence) params.set("confidence", filter.confidence);

    const qs = params.toString() ? `?${params.toString()}` : "";
    const res = await this._request<{ count: number; signals: IntelSignal[] }>(`/v1/intel/signals${qs}`);
    return res.signals || [];
  }

  public async refreshIntelligence(): Promise<Record<string, unknown>> {
    return this._request<Record<string, unknown>>("/v1/intel/refresh", { method: "POST" });
  }

  // --- Solana Payment Settlement ---
  public async createInvoice(options: {
    targetTier?: string;
    asset?: "USDC" | "SOL";
    expectedPayer?: string;
    targetApiKey?: string;
  } = {}): Promise<SolanaInvoice> {
    const payload = {
      target_tier: options.targetTier || "tier_starter",
      asset: options.asset || "USDC",
      expected_payer: options.expectedPayer,
      target_api_key: options.targetApiKey,
    };
    return this._request<SolanaInvoice>("/v1/payments/invoice", {
      method: "POST",
      body: payload,
    });
  }

  public async claimInvoice(invoiceId: string, claimSecret: string): Promise<Record<string, unknown>> {
    return this._request<Record<string, unknown>>(`/v1/payments/invoice/${invoiceId}/claim`, {
      method: "POST",
      body: { claim_secret: claimSecret },
    });
  }

  public async verifyPayment(options: {
    transactionSignature: string;
    invoiceId?: string;
    reference?: string;
    asset?: string;
  }): Promise<PaymentVerificationResult> {
    const payload = {
      transaction_signature: options.transactionSignature,
      invoice_id: options.invoiceId,
      reference: options.reference,
      asset: options.asset || "USDC",
    };
    return this._request<PaymentVerificationResult>("/v1/payments/verify-solana", {
      method: "POST",
      body: payload,
    });
  }

  // --- Verification Challenges ---
  public async createChallenge(options: { challengeType?: string; expirySeconds?: number } = {}): Promise<ChallengeInfo> {
    return this._request<ChallengeInfo>("/v1/challenges", {
      method: "POST",
      body: {
        challenge_type: options.challengeType || "arithmetic",
        expiry_seconds: options.expirySeconds || 120,
      },
    });
  }

  public async getChallenge(challengeId: string): Promise<ChallengeInfo> {
    return this._request<ChallengeInfo>(`/v1/challenges/${encodeURIComponent(challengeId)}`);
  }

  public async verifyChallenge(challengeId: string, answer: string): Promise<ChallengeVerificationResult> {
    return this._request<ChallengeVerificationResult>("/v1/challenges/verify", {
      method: "POST",
      body: {
        challenge_id: challengeId,
        answer,
      },
    });
  }

  // --- DAG Tool Graph ---
  public async getToolParameterGraph(toolName: string): Promise<ToolDAGGraph> {
    return this._request<ToolDAGGraph>(`/v1/tools/${toolName}/parameter-graph`);
  }

  // --- Cryptographic State Witnesses ---
  public async getWitness(witnessId: string): Promise<StateWitnessRecord> {
    return this._request<StateWitnessRecord>(`/v1/witnesses/${witnessId}`);
  }

  public async getWitnessPublicKeys(): Promise<Record<string, unknown>> {
    const res = await this._request<Record<string, unknown>>("/v1/witnesses/public-keys");
    const activeId = res.active_key_id as string;
    if (activeId && typeof res.public_keys === "object" && res.public_keys !== null) {
      const keys = res.public_keys as Record<string, { public_key_base58?: string }>;
      this._cachedServerPubKey = keys[activeId]?.public_key_base58;
    }
    return res;
  }

  public async verifyWitnessLocal(
    witness: Record<string, unknown>,
    publicKeyBase58?: string
  ): Promise<{ valid: boolean; witness_id?: string; error?: string }> {
    let pubKey = publicKeyBase58 || (witness.public_key_base58 as string) || this._cachedServerPubKey;
    if (!pubKey) {
      await this.getWitnessPublicKeys();
      pubKey = this._cachedServerPubKey;
    }
    return verifyWitnessOffline(witness, pubKey);
  }

  // --- Real-time WebSocket Streaming ---
  public connectAlphaStream(options: {
    categories?: string[];
    minConfidence?: string;
    onSignal: (signal: IntelSignal) => void;
    onError?: (error: Error) => void;
    onConnected?: (info: { sessionId: string; remainingCredits: number }) => void;
  }): { close: () => void; ping: () => void; subscribe: (cats: string[]) => void } {
    const wsProto = this.baseUrl.startsWith("https") ? "wss" : "ws";
    const host = this.baseUrl.replace(/^https?:\/\//, "");
    const tokenParam = this.apiKey ? `?token=${encodeURIComponent(this.apiKey)}` : "";
    const wsUrl = `${wsProto}://${host}/v1/ws/alpha${tokenParam}`;

    // Use global WebSocket available in Node 21+ and modern browsers
    const ws = new (globalThis as unknown as { WebSocket: new (url: string) => WebSocket }).WebSocket(wsUrl);

    ws.onopen = () => {
      if (options.categories || options.minConfidence) {
        ws.send(JSON.stringify({
          type: "subscribe",
          categories: options.categories,
          min_confidence: options.minConfidence,
        }));
      }
    };

    ws.onmessage = (event: MessageEvent) => {
      try {
        const data = JSON.parse(String(event.data));
        if (data.type === "authenticated" && options.onConnected) {
          options.onConnected({
            sessionId: data.session_id,
            remainingCredits: data.remaining_credits,
          });
        } else if (data.type === "signal" && data.signal) {
          options.onSignal(data.signal as IntelSignal);
        } else if (data.type === "error" && options.onError) {
          options.onError(new Error(`WebSocket error [${data.code}]: ${data.message}`));
        }
      } catch (err: unknown) {
        if (options.onError) {
          options.onError(err instanceof Error ? err : new Error(String(err)));
        }
      }
    };

    ws.onerror = (event: Event) => {
      if (options.onError) {
        options.onError(new Error("WebSocket connection error"));
      }
    };

    return {
      close: () => ws.close(),
      ping: () => ws.send(JSON.stringify({ type: "ping" })),
      subscribe: (categories: string[]) => {
        ws.send(JSON.stringify({ type: "subscribe", categories }));
      },
    };
  }
}
