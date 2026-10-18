import { verifyWitnessOffline } from "./crypto.js";

export class MoltbookApiError extends Error {
  constructor(payload, statusCode = 500) {
    const msg = payload.message || payload.error?.message || payload.code || "Unknown Moltbook API error";
    super(msg);
    this.name = "MoltbookApiError";
    this.code = payload.code || payload.error?.code || "INTERNAL_ERROR";
    this.statusCode = statusCode;
    this.retryable = Boolean(payload.retryable ?? payload.error?.retryable ?? false);
    this.retryAfter = payload.retry_after ?? payload.error?.retry_after;
    this.docsUrl = payload.docs_url ?? payload.error?.docs_url;
    this.requestId = payload.request_id;
  }
}

export class MoltbookIntelClient {
  constructor(config = {}) {
    this.baseUrl = (config.baseUrl || "http://127.0.0.1:8080").replace(/\/+$/, "");
    this.apiKey = config.apiKey;
    this.timeoutMs = config.timeoutMs || 15000;
    this.maxRetries = config.maxRetries ?? 3;
    this.autoRetry = config.autoRetry ?? true;
    this.retryDeadlineMs = config.retryDeadlineMs || 30000;
  }

  async _request(endpoint, options = {}) {
    const url = `${this.baseUrl}${endpoint}`;
    const method = options.method || "GET";
    const reqHeaders = {
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
          return text ? JSON.parse(text) : {};
        }

        const errText = await resp.text();
        let errJson;
        try {
          errJson = JSON.parse(errText);
        } catch {
          errJson = { code: `HTTP_${resp.status}`, message: errText };
        }

        const reqId = resp.headers.get("x-request-id") || undefined;
        if (reqId && !errJson.request_id) {
          errJson.request_id = reqId;
        }

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
      } catch (err) {
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

  async health() {
    return this._request("/v1/health");
  }

  async getQuota() {
    return this._request("/v1/account/quota", { authRequired: true });
  }

  async getLatestBriefing(idempotencyKey) {
    return this._request("/v1/intel/latest", {
      authRequired: true,
      idempotencyKey,
    });
  }

  async getSignals(filter = {}) {
    const params = new URLSearchParams();
    if (filter.limit) params.set("limit", String(filter.limit));
    if (filter.category) params.set("category", filter.category);
    if (filter.confidence) params.set("confidence", filter.confidence);

    const qs = params.toString() ? `?${params.toString()}` : "";
    const res = await this._request(`/v1/intel/signals${qs}`);
    return res.signals || [];
  }

  async refreshIntelligence() {
    return this._request("/v1/intel/refresh", { method: "POST" });
  }

  async createInvoice(options = {}) {
    const payload = {
      target_tier: options.targetTier || "tier_starter",
      asset: options.asset || "USDC",
      expected_payer: options.expectedPayer,
      target_api_key: options.targetApiKey,
    };
    return this._request("/v1/payments/invoice", {
      method: "POST",
      body: payload,
    });
  }

  async claimInvoice(invoiceId, claimSecret) {
    return this._request(`/v1/payments/invoice/${invoiceId}/claim`, {
      method: "POST",
      body: { claim_secret: claimSecret },
    });
  }

  async verifyPayment(options) {
    const payload = {
      transaction_signature: options.transactionSignature,
      invoice_id: options.invoiceId,
      reference: options.reference,
      asset: options.asset || "USDC",
    };
    return this._request("/v1/payments/verify-solana", {
      method: "POST",
      body: payload,
    });
  }

  async getToolParameterGraph(toolName) {
    return this._request(`/v1/tools/${toolName}/parameter-graph`);
  }

  async getWitness(witnessId) {
    return this._request(`/v1/witnesses/${witnessId}`);
  }

  async getWitnessPublicKeys() {
    const res = await this._request("/v1/witnesses/public-keys");
    const activeId = res.active_key_id;
    if (activeId && typeof res.public_keys === "object" && res.public_keys !== null) {
      this._cachedServerPubKey = res.public_keys[activeId]?.public_key_base58;
    }
    return res;
  }

  async verifyWitnessLocal(witness, publicKeyBase58) {
    let pubKey = publicKeyBase58 || witness.public_key_base58 || this._cachedServerPubKey;
    if (!pubKey) {
      await this.getWitnessPublicKeys();
      pubKey = this._cachedServerPubKey;
    }
    return verifyWitnessOffline(witness, pubKey);
  }

  connectAlphaStream(options = {}) {
    const wsProto = this.baseUrl.startsWith("https") ? "wss" : "ws";
    const host = this.baseUrl.replace(/^https?:\/\//, "");
    const tokenParam = this.apiKey ? `?token=${encodeURIComponent(this.apiKey)}` : "";
    const wsUrl = `${wsProto}://${host}/v1/ws/alpha${tokenParam}`;

    const ws = new globalThis.WebSocket(wsUrl);

    ws.onopen = () => {
      if (options.categories || options.minConfidence) {
        ws.send(JSON.stringify({
          type: "subscribe",
          categories: options.categories,
          min_confidence: options.minConfidence,
        }));
      }
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(String(event.data));
        if (data.type === "authenticated" && options.onConnected) {
          options.onConnected({
            sessionId: data.session_id,
            remainingCredits: data.remaining_credits,
          });
        } else if (data.type === "signal" && data.signal && options.onSignal) {
          options.onSignal(data.signal);
        } else if (data.type === "error" && options.onError) {
          options.onError(new Error(`WebSocket error [${data.code}]: ${data.message}`));
        }
      } catch (err) {
        if (options.onError) {
          options.onError(err instanceof Error ? err : new Error(String(err)));
        }
      }
    };

    ws.onerror = () => {
      if (options.onError) {
        options.onError(new Error("WebSocket connection error"));
      }
    };

    return {
      close: () => ws.close(),
      ping: () => ws.send(JSON.stringify({ type: "ping" })),
      subscribe: (categories) => {
        ws.send(JSON.stringify({ type: "subscribe", categories }));
      },
    };
  }
}
