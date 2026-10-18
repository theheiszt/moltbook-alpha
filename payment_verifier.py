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
    CLUSTER_GENESIS_HASHES,
    load_payment_config,
)
from metrics import record_rpc_hop, record_verification_latency, sanitize_provider_host



class VerificationError(Exception):
    """Raised when payment verification fails."""
    pass


class RPCError(Exception):
    """Raised when RPC communication fails or times out."""
    pass


class VerifyPaymentInput(BaseModel):
    transaction_signature: str
    invoice_id: Optional[str] = None
    target_tier: Optional[str] = None
    expected_payer: Optional[str] = None
    expected_reference: Optional[str] = None
    claim_secret: Optional[str] = None

    @field_validator("transaction_signature")
    @classmethod
    def validate_signature(cls, v: str) -> str:
        s = v.strip()
        if not (80 <= len(s) <= 90):
            raise ValueError("Solana transaction signature must be between 80 and 90 characters.")
        if not BASE58_PATTERN.match(s):
            raise ValueError("Solana transaction signature must be valid base58.")
        return s

    @field_validator("expected_payer", "expected_reference")
    @classmethod
    def validate_base58_optional(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = v.strip()
        if not s:
            return None
        if not (32 <= len(s) <= 44) or not BASE58_PATTERN.match(s):
            raise ValueError("Solana address or reference must be valid base58 between 32 and 44 characters.")
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
        slot: Optional[int] = None,
        block_time: Optional[int] = None,
        confirmation_status: Optional[str] = "finalized",
        provider_identity: Optional[str] = None,
        payer: Optional[str] = None,
        reference: Optional[str] = None,
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
        self.slot = slot
        self.block_time = block_time
        self.confirmation_status = confirmation_status
        self.provider_identity = provider_identity
        self.payer = payer
        self.reference = reference


class SolanaPaymentVerifier:
    def __init__(
        self,
        treasury_wallet: Optional[str] = None,
        rpc_url: Optional[str] = None,
        rpc_endpoints: Optional[list[str]] = None,
        rates: Optional[Dict[str, Dict[str, Any]]] = None,
        rpc_caller: Optional[Callable[..., Dict[str, Any]]] = None,
        cluster: str = "mainnet-beta",
        min_slot: int = 1,
        max_age_seconds: Optional[int] = None,
        require_consensus: Optional[bool] = None,
    ):
        cfg = load_payment_config()
        self.treasury_wallet = (treasury_wallet or cfg["solana_treasury_wallet"]).strip()
        self.rates = rates or cfg["rates"]
        self.topup_packages = cfg.get("topup_packages", {})
        self._custom_rpc_caller = rpc_caller
        self.cluster = cluster
        self.min_slot = min_slot
        self.max_age_seconds = max_age_seconds
        self.require_consensus = require_consensus if require_consensus is not None else cfg.get("require_consensus", False)

        # Build ordered list of failover RPC endpoints
        if rpc_endpoints:
            self.rpc_endpoints = [e.strip() for e in rpc_endpoints if e and e.strip()]
        elif rpc_url:
            self.rpc_endpoints = [rpc_url.strip()]
        else:
            self.rpc_endpoints = list(cfg.get("rpc_endpoints", [cfg.get("rpc_url")]))

        self.rpc_url = self.rpc_endpoints[0] if self.rpc_endpoints else "https://api.mainnet-beta.solana.com"
        self.active_rpc_endpoint: Optional[str] = None

    def _validate_endpoint_cluster(self, endpoint: str):
        ep_lower = endpoint.lower()
        if self.cluster == "mainnet-beta":
            if "devnet" in ep_lower or "testnet" in ep_lower:
                raise VerificationError(
                    f"Cluster mismatch: RPC endpoint '{endpoint}' is configured for devnet/testnet, but settlement requires mainnet-beta."
                )

    def validate_cluster_genesis(self, endpoint: Optional[str] = None) -> bool:
        """
        Cryptographically validates cluster identity by querying getGenesisHash.
        Fails closed if the returned hash mismatches the expected cluster genesis.
        """
        expected = CLUSTER_GENESIS_HASHES.get(self.cluster)
        if not expected:
            return True
        targets = [endpoint] if endpoint else self.rpc_endpoints
        for ep in targets:
            try:
                res = self._call_endpoint(ep, "getGenesisHash", [])
                actual = res.get("result") if isinstance(res, dict) else None
                if actual and actual != expected:
                    raise VerificationError(
                        f"Cluster genesis hash mismatch: endpoint '{ep}' returned genesis hash '{actual}', "
                        f"but cluster '{self.cluster}' requires '{expected}'."
                    )
            except RPCError:
                raise
        return True

    def _call_endpoint(self, endpoint: str, method: str, params: list) -> Dict[str, Any]:
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
        except RPCError:
            raise
        except Exception as e:
            raise RPCError(f"RPC query error from {endpoint}: {e!s}") from e

        if not isinstance(res, dict):
            raise RPCError(f"RPC returned non-dict response: {type(res)}")

        if "error" in res:
            err_msg = res["error"].get("message", str(res["error"]))
            raise RPCError(f"RPC error from {endpoint}: {err_msg}")

        return res

    def _call_rpc(self, method: str, params: list) -> Dict[str, Any]:
        """
        Executes RPC call with automatic failover across configured endpoints.
        Tries primary RPC first; on timeout, rate limit (429), or error, seamlessly
        fails over to secondary/tertiary endpoints in the pool.
        """
        errors: list[str] = []

        for endpoint in self.rpc_endpoints:
            try:
                res = self._call_endpoint(endpoint, method, params)
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
        Fails closed if transaction is not finalized or not found across failover pool.
        Accurately distinguishes transport failures (RPCError) from missing transactions (VerificationError).
        """
        errors = []
        all_rpc_errors = True

        for endpoint in self.rpc_endpoints:
            try:
                self._validate_endpoint_cluster(endpoint)
                res = self._call_endpoint(
                    endpoint,
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
                all_rpc_errors = False
                tx = res.get("result")
                if not tx:
                    errors.append(f"[{endpoint}] Transaction not found or not yet finalized")
                    record_rpc_hop(endpoint, "error")
                    continue

                self.active_rpc_endpoint = endpoint
                record_rpc_hop(endpoint, "success")
                return tx
            except RPCError as e:
                errors.append(f"[{endpoint}] {e!s}")
                err_str = str(e).lower()
                outcome = "rate_limited_429" if "429" in err_str else ("timeout" if "timeout" in err_str else "error")
                record_rpc_hop(endpoint, outcome)
                continue
            except VerificationError:
                raise

        if all_rpc_errors and errors:
            raise RPCError(f"All {len(self.rpc_endpoints)} Solana RPC endpoint(s) failed: {'; '.join(errors)}")
        raise VerificationError("Transaction not found or not yet finalized on Solana mainnet.")

    def cross_check_provider_agreement(self, signature: str, primary_tx: Dict[str, Any]) -> bool:
        """
        Cross-checks transaction status across all secondary providers in pool.
        Fails closed if any secondary provider returns a conflicting state
        (e.g. execution error, unconfirmed status, or transaction mismatch).
        """
        if len(self.rpc_endpoints) <= 1:
            return True

        primary_slot = primary_tx.get("slot")
        for endpoint in self.rpc_endpoints[1:]:
            try:
                res = self._call_endpoint(
                    endpoint,
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
                sec_tx = res.get("result")
                if not sec_tx:
                    continue

                sec_meta = sec_tx.get("meta") or {}
                if sec_meta.get("err") is not None:
                    raise VerificationError(
                        f"Provider disagreement: endpoint '{endpoint}' reports execution error: {sec_meta.get('err')}"
                    )

                sec_conf = sec_tx.get("confirmationStatus") or sec_meta.get("confirmationStatus")
                if sec_conf and str(sec_conf).lower() != "finalized":
                    raise VerificationError(
                        f"Provider disagreement: endpoint '{endpoint}' reports confirmationStatus='{sec_conf}' (not finalized)"
                    )

                sec_slot = sec_tx.get("slot")
                if sec_slot and primary_slot and sec_slot != primary_slot:
                    raise VerificationError(
                        f"Provider disagreement: slot mismatch between providers ({primary_slot} vs {sec_slot})"
                    )
            except RPCError:
                continue

        return True

    def verify_payment(
        self,
        signature: str,
        requested_tier: Optional[str] = None,
        expected_payer: Optional[str] = None,
        expected_reference: Optional[str] = None,
    ) -> VerifiedPayment:
        """
        Server-authoritative verification:
        1. Confirms transaction succeeded without error.
        2. Proves transfer to configured treasury wallet.
        3. Validates native SOL or canonical SPL USDC mint and decimals.
        4. Validates integer transfer amount against pricing tiers.
        5. Validates optional expected_payer and expected_reference (Solana Pay spec).
        6. Awards server-determined tier and credits.
        """
        t0 = time.perf_counter()
        asset_label = "UNKNOWN"
        try:
            tx = self.fetch_transaction(signature)

            # 1. Structural & Metadata Validation
            meta = tx.get("meta")
            if not meta:
                raise VerificationError("Transaction metadata is missing.")

            # 2. Execution Success Validation
            if meta.get("err") is not None:
                raise VerificationError(f"Transaction failed on-chain: {meta.get('err')}")

            if isinstance(meta.get("status"), dict) and meta["status"].get("Err") is not None:
                raise VerificationError(f"Transaction failed on-chain: {meta['status'].get('Err')}")

            # 3. Transaction Identity & Signature Matching
            transaction_payload = tx.get("transaction")
            if not isinstance(transaction_payload, dict):
                raise VerificationError("Transaction payload is malformed or missing.")

            sigs = transaction_payload.get("signatures", [])
            if sigs:
                if signature not in sigs:
                    raise VerificationError(
                        f"Transaction signature mismatch: expected '{signature}', found {sigs}"
                    )

            # 4. Cluster Verification
            tx_cluster = tx.get("cluster")
            if tx_cluster and tx_cluster != self.cluster:
                raise VerificationError(
                    f"Cluster mismatch: transaction cluster '{tx_cluster}' does not match expected '{self.cluster}'."
                )

            # 5. Commitment & Finality Evidence Verification
            conf_status = tx.get("confirmationStatus") or meta.get("confirmationStatus")
            if conf_status and str(conf_status).lower() != "finalized":
                raise VerificationError(
                    f"Transaction commitment insufficient: confirmationStatus is '{conf_status}', expected 'finalized'."
                )

            tx_commitment = tx.get("commitment") or meta.get("commitment")
            if tx_commitment and str(tx_commitment).lower() != "finalized":
                raise VerificationError(
                    f"Transaction commitment insufficient: commitment is '{tx_commitment}', expected 'finalized'."
                )

            slot = tx.get("slot")
            if not isinstance(slot, int) or slot < self.min_slot:
                raise VerificationError(
                    f"Transaction finality evidence missing: invalid slot '{slot}' (must be >= {self.min_slot})."
                )

            block_time = tx.get("blockTime")
            if not isinstance(block_time, int) or block_time <= 0:
                raise VerificationError(
                    f"Transaction finality evidence missing: invalid blockTime timestamp '{block_time}'."
                )

            now_ts = int(time.time())
            if block_time > now_ts + 60:
                raise VerificationError(
                    f"Transaction timestamp is in the future ({block_time} > {now_ts} + 60s allowed clock skew)."
                )

            if self.max_age_seconds:
                age = now_ts - block_time
                if age > self.max_age_seconds:
                    raise VerificationError(
                        f"Transaction expired: transaction is {age}s old (max allowed: {self.max_age_seconds}s)."
                    )

            # 6. Provider Disagreement Check (if consensus required)
            if self.require_consensus:
                self.cross_check_provider_agreement(signature, tx)

            # 7. Extract Transfers & Validate Accounts
            message = transaction_payload.get("message", {})
            account_keys = message.get("accountKeys", [])

            # Normalize account keys and identify authorized signers
            account_pubkeys = []
            signers = set()
            for idx, ak in enumerate(account_keys):
                if isinstance(ak, dict):
                    pub = ak.get("pubkey", "").strip()
                    if pub:
                        account_pubkeys.append(pub)
                        if ak.get("signer") is True:
                            signers.add(pub)
                else:
                    pub = str(ak).strip()
                    if pub:
                        account_pubkeys.append(pub)
                        if idx < len(sigs):
                            signers.add(pub)

            # Payer validation (if expected_payer requested)
            payer_pubkey = account_pubkeys[0] if account_pubkeys else None
            if expected_payer is not None:
                clean_payer = expected_payer.strip()
                if not clean_payer:
                    raise VerificationError("Expected payer address cannot be empty or whitespace.")
                if clean_payer not in account_pubkeys:
                    raise VerificationError(
                        f"Payer mismatch: expected payer '{clean_payer}' not found in transaction accounts."
                    )
                if clean_payer not in signers:
                    raise VerificationError(
                        f"Payer mismatch: expected payer '{clean_payer}' is not a signer of the transaction."
                    )

            # Reference validation (if expected_reference requested, Solana Pay 2.0 spec)
            if expected_reference is not None:
                clean_ref = expected_reference.strip()
                if not clean_ref:
                    raise VerificationError("Expected reference address cannot be empty or whitespace.")
                if clean_ref not in account_pubkeys:
                    raise VerificationError(
                        f"Reference mismatch: expected Solana Pay reference '{clean_ref}' not found in transaction accounts."
                    )


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
            # 8. Determine tier strictly from verified amount
            earned_tier, credits_to_grant = self._determine_tier(asset, amount_raw, requested_tier)

            record_verification_latency(asset_label, time.perf_counter() - t0)

            provider_host = sanitize_provider_host(self.active_rpc_endpoint or self.rpc_url)

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
                cluster=self.cluster,
                slot=slot,
                block_time=block_time,
                confirmation_status="finalized",
                provider_identity=provider_host,
                payer=payer_pubkey,
                reference=expected_reference,
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
        # 1. Resolve dynamic top-up packages if requested
        if requested_tier and requested_tier in self.topup_packages:
            pkg = self.topup_packages[requested_tier]
            required = pkg["usdc_units"] if asset == "USDC" else pkg["sol_lamports"]
            if amount_raw < required:
                raise VerificationError(
                    f"Received {amount_raw} {asset} units, which is below the required ({required}) for top-up package {requested_tier}."
                )
            return requested_tier, pkg["credits"]

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
