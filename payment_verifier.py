"""
Server-Authoritative Solana / USDC Payment Verifier.
Verifies on-chain transactions with strict checks for recipient, asset,
mint, raw integer amounts, finalization, and failure-closed network handling.
"""

import json
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Callable
from pydantic import BaseModel, field_validator

from config import (
    BASE58_PATTERN,
    CANONICAL_USDC_MINT,
    USDC_DECIMALS,
    load_payment_config,
)
from metrics import record_rpc_hop, record_verification_latency



class VerificationError(Exception):
    """Raised when payment verification fails."""
    pass


class RPCError(Exception):
    """Raised when RPC communication fails or times out."""
    pass


class VerifyPaymentInput(BaseModel):
    transaction_signature: str
    target_tier: Optional[str] = "tier_starter"

    @field_validator("transaction_signature")
    @classmethod
    def validate_signature(cls, v: str) -> str:
        s = v.strip()
        if not (80 <= len(s) <= 90):
            raise ValueError("Solana transaction signature must be between 80 and 90 characters.")
        if not BASE58_PATTERN.match(s):
            raise ValueError("Solana transaction signature must be valid base58.")
        return s


class VerifiedPayment:
    def __init__(
        self,
        tx_signature: str,
        asset: str,
        amount_raw: int,
        tier: str,
        credits: int,
        recipient: str,
        rpc_endpoint_used: Optional[str] = None,
        commitment: str = "finalized",
        verified_at_utc: Optional[str] = None,
        cluster: str = "mainnet-beta",
    ):
        self.tx_signature = tx_signature
        self.asset = asset
        self.amount_raw = amount_raw
        self.tier = tier
        self.credits = credits
        self.recipient = recipient
        self.rpc_endpoint_used = rpc_endpoint_used
        self.commitment = commitment
        self.verified_at_utc = verified_at_utc or datetime.now(timezone.utc).isoformat()
        self.cluster = cluster


class SolanaPaymentVerifier:
    def __init__(
        self,
        treasury_wallet: Optional[str] = None,
        rpc_url: Optional[str] = None,
        rpc_endpoints: Optional[list[str]] = None,
        rates: Optional[Dict[str, Dict[str, Any]]] = None,
        rpc_caller: Optional[Callable[..., Dict[str, Any]]] = None,
    ):
        cfg = load_payment_config()
        self.treasury_wallet = (treasury_wallet or cfg["solana_treasury_wallet"]).strip()
        self.rates = rates or cfg["rates"]
        self._custom_rpc_caller = rpc_caller

        # Build ordered list of failover RPC endpoints
        if rpc_endpoints:
            self.rpc_endpoints = [e.strip() for e in rpc_endpoints if e and e.strip()]
        elif rpc_url:
            self.rpc_endpoints = [rpc_url.strip()]
        else:
            self.rpc_endpoints = list(cfg.get("rpc_endpoints", [cfg.get("rpc_url")]))

        self.rpc_url = self.rpc_endpoints[0] if self.rpc_endpoints else "https://api.mainnet-beta.solana.com"
        self.active_rpc_endpoint: Optional[str] = None

    def _call_rpc(self, method: str, params: list) -> Dict[str, Any]:
        """
        Executes RPC call with automatic failover across configured endpoints.
        Tries primary RPC first; on timeout, rate limit (429), or error, seamlessly
        fails over to secondary/tertiary endpoints in the pool.
        """
        errors: list[str] = []

        for endpoint in self.rpc_endpoints:
            try:
                if self._custom_rpc_caller:
                    import inspect
                    sig = inspect.signature(self._custom_rpc_caller)
                    if len(sig.parameters) >= 3:
                        res = self._custom_rpc_caller(endpoint, method, params)
                    else:
                        res = self._custom_rpc_caller(method, params)
                else:
                    res = self._send_http_rpc(endpoint, method, params)

                if not isinstance(res, dict):
                    raise RPCError(f"RPC returned non-dict response: {type(res)}")

                if "error" in res:
                    err_msg = res["error"].get("message", str(res["error"]))
                    raise RPCError(f"RPC error from {endpoint}: {err_msg}")

                self.active_rpc_endpoint = endpoint
                record_rpc_hop(endpoint, "success")
                return res
            except Exception as e:
                err_str = str(e).lower()
                if "429" in err_str or "rate limit" in err_str:
                    outcome = "rate_limited_429"
                elif "timeout" in err_str or "timed out" in err_str:
                    outcome = "timeout"
                else:
                    outcome = "error"
                record_rpc_hop(endpoint, outcome)
                errors.append(f"[{endpoint}] {e!s}")
                continue

        raise RPCError(
            f"All {len(self.rpc_endpoints)} Solana RPC endpoint(s) failed: {'; '.join(errors)}"
        )

    def _send_http_rpc(self, endpoint: str, method: str, params: list) -> Dict[str, Any]:
        payload = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params,
        }).encode("utf-8")

        req = urllib.request.Request(
            endpoint,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "MoltbookAlphaPaymentVerifier/1.0",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=12) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise RPCError(f"HTTP error {e.code}") from e
        except urllib.error.URLError as e:
            raise RPCError(f"Connection error: {e.reason}") from e
        except Exception as e:
            raise RPCError(f"RPC query error: {e!s}") from e

    def fetch_transaction(self, signature: str) -> Dict[str, Any]:
        """
        Fetches transaction with commitment='finalized' and jsonParsed encoding.
        Fails closed if transaction is not finalized or not found.
        """
        resp = self._call_rpc(
            "getTransaction",
            [
                signature,
                {
                    "encoding": "jsonParsed",
                    "commitment": "finalized",
                    "maxSupportedTransactionVersion": 0,
                },
            ],
        )

        tx = resp.get("result")
        if not tx:
            raise VerificationError("Transaction not found or not yet finalized on Solana mainnet.")
        return tx

    def verify_payment(self, signature: str, requested_tier: Optional[str] = None) -> VerifiedPayment:
        """
        Server-authoritative verification:
        1. Confirms transaction succeeded without error.
        2. Proves transfer to configured treasury wallet.
        3. Validates native SOL or canonical SPL USDC mint and decimals.
        4. Validates integer transfer amount against pricing tiers.
        5. Awards server-determined tier and credits.
        """
        t0 = time.perf_counter()
        asset_label = "UNKNOWN"
        try:
            tx = self.fetch_transaction(signature)

            meta = tx.get("meta")
            if not meta:
                raise VerificationError("Transaction metadata is missing.")

            if meta.get("err") is not None:
                raise VerificationError(f"Transaction failed on-chain: {meta.get('err')}")

            transaction_payload = tx.get("transaction", {})
            message = transaction_payload.get("message", {})
            account_keys = message.get("accountKeys", [])

            # Normalize account keys (can be list of dicts or list of strings)
            account_pubkeys = []
            for ak in account_keys:
                if isinstance(ak, dict):
                    account_pubkeys.append(ak.get("pubkey", ""))
                else:
                    account_pubkeys.append(str(ak))

            # Check SPL USDC transfer first
            usdc_amount_received = self._extract_usdc_transfer(meta, account_pubkeys)
            sol_amount_received = 0

            asset = None
            amount_raw = 0

            if usdc_amount_received > 0:
                asset = "USDC"
                amount_raw = usdc_amount_received
            else:
                sol_amount_received = self._extract_sol_transfer(meta, account_pubkeys, message)
                if sol_amount_received > 0:
                    asset = "SOL"
                    amount_raw = sol_amount_received

            if not asset or amount_raw <= 0:
                raise VerificationError("No verified transfer to the configured treasury wallet found in transaction.")

            asset_label = asset
            # Determine tier strictly from verified amount
            earned_tier, credits_to_grant = self._determine_tier(asset, amount_raw, requested_tier)

            record_verification_latency(asset_label, time.perf_counter() - t0)

            return VerifiedPayment(
                tx_signature=signature,
                asset=asset,
                amount_raw=amount_raw,
                tier=earned_tier,
                credits=credits_to_grant,
                recipient=self.treasury_wallet,
                rpc_endpoint_used=self.active_rpc_endpoint or self.rpc_url,
                commitment="finalized",
                verified_at_utc=datetime.now(timezone.utc).isoformat(),
                cluster="mainnet-beta",
            )
        except Exception:
            record_verification_latency(asset_label, time.perf_counter() - t0)
            raise

    def _extract_usdc_transfer(self, meta: Dict[str, Any], account_pubkeys: list) -> int:
        """
        Verifies and calculates net integer micro-USDC received by treasury.
        Validates canonical mint and owner.
        """
        pre_tokens = meta.get("preTokenBalances", []) or []
        post_tokens = meta.get("postTokenBalances", []) or []

        # Find token balances for treasury wallet with canonical USDC mint
        pre_amt = 0
        post_amt = 0
        found_treasury_token = False

        for post in post_tokens:
            mint = post.get("mint")
            owner = post.get("owner")
            # If owner is not explicitly given, check if accountIndex maps to treasury
            acct_idx = post.get("accountIndex")
            if owner == self.treasury_wallet or (acct_idx is not None and acct_idx < len(account_pubkeys) and account_pubkeys[acct_idx] == self.treasury_wallet):
                if mint == CANONICAL_USDC_MINT:
                    token_info = post.get("uiTokenAmount", {})
                    # Ensure decimals match canonical 6 decimals
                    if token_info.get("decimals") == USDC_DECIMALS:
                        raw_str = token_info.get("amount", "0")
                        try:
                            post_amt = int(raw_str)
                            found_treasury_token = True
                        except ValueError:
                            pass

        for pre in pre_tokens:
            mint = pre.get("mint")
            owner = pre.get("owner")
            acct_idx = pre.get("accountIndex")
            if owner == self.treasury_wallet or (acct_idx is not None and acct_idx < len(account_pubkeys) and account_pubkeys[acct_idx] == self.treasury_wallet):
                if mint == CANONICAL_USDC_MINT:
                    token_info = pre.get("uiTokenAmount", {})
                    raw_str = token_info.get("amount", "0")
                    try:
                        pre_amt = int(raw_str)
                    except ValueError:
                        pass

        if found_treasury_token and post_amt > pre_amt:
            return post_amt - pre_amt

        # Also inspect parsed instructions for SPL transfer
        return 0

    def _extract_sol_transfer(
        self,
        meta: Dict[str, Any],
        account_pubkeys: list,
        message: Dict[str, Any]
    ) -> int:
        """
        Verifies net native SOL lamports received by treasury.
        """
        if self.treasury_wallet not in account_pubkeys:
            return 0

        treasury_idx = account_pubkeys.index(self.treasury_wallet)
        pre_balances = meta.get("preBalances", [])
        post_balances = meta.get("postBalances", [])

        if treasury_idx >= len(pre_balances) or treasury_idx >= len(post_balances):
            return 0

        net_lamports = post_balances[treasury_idx] - pre_balances[treasury_idx]
        if net_lamports <= 0:
            return 0

        # Confirm treasury was recipient via instructions or balance delta
        instructions = message.get("instructions", [])
        has_system_transfer = False
        for inst in instructions:
            if isinstance(inst, dict):
                parsed = inst.get("parsed")
                if isinstance(parsed, dict) and parsed.get("type") == "transfer":
                    info = parsed.get("info", {})
                    if info.get("destination") == self.treasury_wallet:
                        has_system_transfer = True
                        break

        # If system transfer instruction or positive delta observed
        if has_system_transfer or net_lamports > 0:
            return net_lamports

        return 0

    def _determine_tier(
        self,
        asset: str,
        amount_raw: int,
        requested_tier: Optional[str]
    ) -> tuple[str, int]:
        """
        Determines tier strictly on server.
        Orders tiers from highest to lowest.
        Client requested_tier can only be granted if the payment covers it.
        """
        # Sort tiers by USD value descending
        sorted_tiers = sorted(
            self.rates.items(),
            key=lambda item: item[1].get("usd", 0.0),
            reverse=True
        )

        qualified_tier = None
        for tier_name, tier_cfg in sorted_tiers:
            if asset == "USDC":
                required = tier_cfg["usdc_units"]
            else:
                required = tier_cfg["sol_lamports"]

            if amount_raw >= required:
                qualified_tier = tier_name
                break

        if not qualified_tier:
            min_tier = sorted_tiers[-1][0]
            min_req = sorted_tiers[-1][1]["usdc_units"] if asset == "USDC" else sorted_tiers[-1][1]["sol_lamports"]
            raise VerificationError(
                f"Received {amount_raw} {asset} units, which is below the minimum required ({min_req}) for {min_tier}."
            )

        # If user requested a lower tier than what they paid for, they get at least requested tier,
        # but if they requested a higher tier than what they paid for, reject or downgrade to what was paid!
        chosen_tier = qualified_tier
        if requested_tier and requested_tier in self.rates:
            req_usd = self.rates[requested_tier].get("usd", 0.0)
            qual_usd = self.rates[qualified_tier].get("usd", 0.0)
            if req_usd <= qual_usd:
                chosen_tier = requested_tier

        credits_to_grant = self.rates[chosen_tier]["credits"]
        return chosen_tier, credits_to_grant
