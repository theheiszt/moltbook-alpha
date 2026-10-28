"""
Moltbook Alpha Client SDK — Main Client Interface.
High-level client with automatic retries, machine-readable error mapping,
DAG tool parameter planning, and cryptographic state witness verification.
"""

import json
import time
import random
import urllib.request
import urllib.error
from typing import Dict, Any, Optional, List

from .exceptions import raise_for_error_payload, MoltbookApiError
from .crypto import verify_witness_payload_offline
from .dag_resolver import ToolDAGResolver


class MoltbookIntelClient:
    """
    Official Python Client for the Moltbook Alpha Market Intelligence & Payment API.
    Zero mandatory external dependencies; uses standard library with optional acceleration.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8080",
        api_key: Optional[str] = None,
        timeout: float = 15.0,
        max_retries: int = 3,
        auto_retry: bool = True,
        retry_deadline: float = 30.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self.auto_retry = auto_retry
        self.retry_deadline = retry_deadline
        self._cached_server_pub_key: Optional[str] = None

    def _request(
        self,
        endpoint: str,
        method: str = "GET",
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        auth_required: bool = False,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}{endpoint}"
        req_headers = {
            "User-Agent": "MoltbookIntelSDK/1.0",
            "Accept": "application/json",
        }
        if payload is not None:
            req_headers["Content-Type"] = "application/json"
        if self.api_key:
            req_headers["Authorization"] = f"Bearer {self.api_key}"
        elif auth_required:
            raise MoltbookApiError(
                code="AUTHENTICATION_REQUIRED",
                message="Client initialized without an API key for authenticated endpoint.",
                status_code=401,
            )

        if idempotency_key:
            req_headers["Idempotency-Key"] = idempotency_key

        if headers:
            req_headers.update(headers)

        data_bytes = json.dumps(payload).encode("utf-8") if payload is not None else None
        retries = 0
        start_time = time.time()

        while True:
            try:
                req = urllib.request.Request(url, data=data_bytes, headers=req_headers, method=method)
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    resp_bytes = resp.read()
                    if not resp_bytes:
                        return {}
                    return json.loads(resp_bytes.decode("utf-8"))
            except urllib.error.HTTPError as e:
                err_body = e.read().decode("utf-8")
                req_id = e.headers.get("X-Request-ID")
                try:
                    err_json = json.loads(err_body)
                except Exception:
                    err_json = {"code": f"HTTP_{e.code}", "message": err_body}

                # On HTTP 402 (payment required / entitlement exhausted), stop retrying immediately
                if e.code == 402:
                    raise_for_error_payload(e.code, err_json, request_id=req_id)

                # Evaluate auto-retry for transient errors and rate limiting
                nested_err = err_json.get("error") if isinstance(err_json.get("error"), dict) else {}
                retryable = err_json.get("retryable", nested_err.get("retryable", False))
                header_retry_after = e.headers.get("Retry-After")
                retry_after = (
                    header_retry_after
                    or err_json.get("retry_after")
                    or err_json.get("retry_after_seconds")
                    or nested_err.get("retry_after_seconds")
                )

                elapsed = time.time() - start_time
                if self.auto_retry and retryable and retries < self.max_retries and elapsed < self.retry_deadline:
                    retries += 1
                    if retry_after is not None:
                        try:
                            base_sleep = float(retry_after)
                        except (ValueError, TypeError):
                            base_sleep = 1.0
                        sleep_time = base_sleep + random.uniform(0.05, 0.25)
                    else:
                        base_backoff = min(15.0, 1.5 ** retries)
                        sleep_time = random.uniform(0.5 * base_backoff, 1.5 * base_backoff)

                    # Ensure we don't exceed the total retry deadline
                    remaining_deadline = max(0.0, self.retry_deadline - (time.time() - start_time))
                    if sleep_time > remaining_deadline:
                        sleep_time = remaining_deadline

                    if sleep_time > 0:
                        time.sleep(sleep_time)
                    continue

                raise_for_error_payload(e.code, err_json, request_id=req_id)
            except urllib.error.URLError as e:
                elapsed = time.time() - start_time
                if self.auto_retry and retries < self.max_retries and elapsed < self.retry_deadline:
                    retries += 1
                    base_backoff = min(15.0, 1.5 ** retries)
                    sleep_time = random.uniform(0.5 * base_backoff, 1.5 * base_backoff)
                    time.sleep(sleep_time)
                    continue
                raise MoltbookApiError(
                    code="NETWORK_ERROR",
                    message=f"Failed to connect to {url}: {e.reason}",
                    status_code=503,
                    retryable=True,
                ) from e

    # System Diagnostics & Quota
    def health(self) -> Dict[str, Any]:
        """Returns API health status, subsystem connectivity, and RPC health."""
        return self._request("/v1/health")

    def get_quota(self) -> Dict[str, Any]:
        """Inspects account tier, remaining credits, and discrete credit lots without spending credits."""
        return self._request("/v1/account/quota", auth_required=True)

    def get_error_registry(self) -> Dict[str, Any]:
        """Returns machine-readable error taxonomy specification and retryability rules."""
        return self._request("/v1/errors")

    # DAG Tool Parameters
    def get_tools(self) -> List[Dict[str, Any]]:
        """Lists registered agent tools and endpoints for parameter graphs."""
        res = self._request("/v1/tools")
        return res.get("tools", [])

    def get_tool_parameter_graph(self, tool_name: str) -> Dict[str, Any]:
        """Fetches the compiled Directed Acyclic Graph (DAG) for a tool."""
        return self._request(f"/v1/tools/{tool_name}/parameter-graph")

    def get_dag_resolver(self, tool_name: str) -> ToolDAGResolver:
        """Fetches parameter graph and returns a client-side ToolDAGResolver."""
        graph = self.get_tool_parameter_graph(tool_name)
        return ToolDAGResolver(graph)

    # Market Intelligence
    def get_latest_briefing(self, idempotency_key: Optional[str] = None) -> Dict[str, Any]:
        """
        Retrieves the latest synthesized market intelligence briefing and state witness.
        Deducts 1 credit from account unless an idempotent retry is recognized.
        """
        return self._request("/v1/intel/latest", auth_required=True, idempotency_key=idempotency_key)

    def get_signals(
        self,
        category: Optional[str] = None,
        confidence: Optional[str] = None,
        limit: int = 25,
    ) -> List[Dict[str, Any]]:
        """Queries granular intelligence signals across security, API changes, failures, and alpha."""
        params = [f"limit={limit}"]
        if category:
            params.append(f"category={category}")
        if confidence:
            params.append(f"confidence={confidence}")
        qs = "&".join(params)
        res = self._request(f"/v1/intel/signals?{qs}")
        return res.get("signals", [])

    def get_opportunities(
        self,
        min_profit_pct: float = 0.05,
        pair: Optional[str] = None,
        opp_type: Optional[str] = None,
        limit: int = 25,
    ) -> List[Dict[str, Any]]:
        """Scans real-time cross-DEX arbitrage opportunities, liquidity gaps, and tick vacuum squeezes."""
        params = [f"limit={limit}", f"min_profit_pct={min_profit_pct}"]
        if pair:
            params.append(f"pair={urllib.parse.quote(pair)}")
        if opp_type:
            params.append(f"opp_type={urllib.parse.quote(opp_type)}")
        qs = "&".join(params)
        res = self._request(f"/v1/intel/opportunities?{qs}")
        return res.get("opportunities", [])

    def get_trading_signals(
        self,
        asset: Optional[str] = None,
        action: Optional[str] = None,
        min_confidence: float = 0.5,
        limit: int = 25,
    ) -> List[Dict[str, Any]]:
        """Synthesizes structured machine-readable trading directives with entry, targets, stop-loss, and execution routing."""
        params = [f"limit={limit}", f"min_confidence={min_confidence}"]
        if asset:
            params.append(f"asset={urllib.parse.quote(asset)}")
        if action:
            params.append(f"action={urllib.parse.quote(action)}")
        qs = "&".join(params)
        res = self._request(f"/v1/intel/signals/trading?{qs}")
        return res.get("trading_signals", [])

    def refresh_intelligence(self) -> Dict[str, Any]:
        """Triggers an immediate collection and synthesis cycle across approved sources."""
        return self._request("/v1/intel/refresh", method="POST")

    # Solana Payment Settlement & Key Recovery
    def create_invoice(
        self,
        target_tier: str = "tier_starter",
        asset: str = "USDC",
        expected_payer: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Creates a Solana Pay invoice with a client-held zero-knowledge claim secret."""
        payload = {
            "target_tier": target_tier,
            "asset": asset,
            "expected_payer": expected_payer,
        }
        return self._request("/v1/payments/invoice", method="POST", payload=payload)

    def claim_invoice(self, invoice_id: str, claim_secret: str) -> Dict[str, Any]:
        """Recovers an API key using the zero-knowledge claim secret if connection dropped."""
        payload = {"claim_secret": claim_secret}
        return self._request(f"/v1/payments/invoice/{invoice_id}/claim", method="POST", payload=payload)

    def verify_payment(
        self,
        transaction_signature: str,
        invoice_id: Optional[str] = None,
        reference: Optional[str] = None,
        asset: str = "USDC",
    ) -> Dict[str, Any]:
        """Submits finalized on-chain signature for server-authoritative settlement and key issuance."""
        payload = {
            "transaction_signature": transaction_signature,
            "invoice_id": invoice_id,
            "reference": reference,
            "asset": asset,
        }
        return self._request("/v1/payments/verify-solana", method="POST", payload=payload)

    # Cryptographic State Witnesses
    def get_witness_public_keys(self) -> Dict[str, Any]:
        """Fetches active Ed25519 public keys used for signing cryptographic state witnesses."""
        res = self._request("/v1/witnesses/public-keys")
        active_id = res.get("active_key_id")
        if active_id and "public_keys" in res:
            self._cached_server_pub_key = res["public_keys"].get(active_id, {}).get("public_key_base58")
        return res

    def get_witness(self, witness_id: str) -> Dict[str, Any]:
        """Retrieves an immutable state witness receipt by ID."""
        return self._request(f"/v1/witnesses/{witness_id}")

    def verify_witness_remote(self, witness: Dict[str, Any], public_key_base58: Optional[str] = None) -> Dict[str, Any]:
        """Verifies state witness via the server's verification endpoint."""
        payload = {
            "witness": witness,
            "public_key_base58": public_key_base58,
        }
        return self._request("/v1/witnesses/verify", method="POST", payload=payload)

    def verify_witness_local(self, witness: Dict[str, Any], public_key_base58: Optional[str] = None) -> Dict[str, Any]:
        """
        Performs 100% offline mathematical verification of the state witness.
        Validates RFC 8785 canonical hash and Ed25519 signature locally without trusting server claims.
        """
        target_pub = public_key_base58 or witness.get("public_key_base58") or self._cached_server_pub_key
        if not target_pub:
            # Fetch public key once from server
            self.get_witness_public_keys()
            target_pub = self._cached_server_pub_key

        return verify_witness_payload_offline(witness, target_pub)
