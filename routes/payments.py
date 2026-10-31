"""
Moltbook Alpha — Payment & Challenge Routes.
"""

from datetime import datetime, timezone
import hmac
import os
import re
import secrets
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator, model_validator

from app_state import (
    get_client_ip,
    in_flight_deduplicator,
    nano_adapter,
    rate_limiter,
    refund_dispatcher,
    storage,
    witness_manager,
)
from ops.security.confirm_store import confirm_store
from config import (
    BASE58_PATTERN,
    CANONICAL_USDC_MINT,
    WEBHOOK_SECRET,
    is_demo_keys_enabled,
    load_payment_config,
)
from errors import (
    ApiError,
    ErrorCode,
    OperationOutcome,
    RecoveryAction,
    format_error_payload,
)
from metrics import (
    record_payment,
    record_rate_limit,
    record_webhook,
)
from payment_verifier import (
    RPCError,
    SolanaPaymentVerifier,
    VerificationError,
    VerifyPaymentInput,
)
from storage import StorageError

router = APIRouter(tags=["Payments"])


def create_payments_router() -> APIRouter:
    return router


class CreateInvoiceInput(BaseModel):
    target_tier: Optional[str] = "tier_starter"
    asset: Optional[str] = "USDC"
    rail: Optional[str] = "solana"
    cluster: Optional[str] = "mainnet-beta"
    expected_payer: Optional[str] = None
    target_api_key: Optional[str] = None
    tier: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def resolve_tier_alias(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "tier" in data and ("target_tier" not in data or not data["target_tier"]):
                data["target_tier"] = data["tier"]
            elif "target_tier" in data and ("tier" not in data or not data["tier"]):
                data["tier"] = data["target_tier"]
        return data

    @field_validator("target_tier")
    @classmethod
    def validate_tier(cls, v: Optional[str]) -> str:
        t = (v or "tier_starter").strip()
        cfg = load_payment_config()
        valid = list(cfg["rates"].keys()) + list(cfg.get("topup_packages", {}).keys())
        if t not in valid:
            raise ValueError(f"Unknown target_tier '{t}'. Must be one of: {valid}")
        return t

    @field_validator("rail")
    @classmethod
    def validate_rail(cls, v: Optional[str]) -> str:
        r = (v or "solana").strip().lower()
        if r not in ("solana", "nano"):
            raise ValueError("Rail must be 'solana' or 'nano'.")
        return r

    @field_validator("cluster")
    @classmethod
    def validate_cluster(cls, v: Optional[str]) -> str:
        c = (v or "mainnet-beta").strip().lower()
        if c not in ("mainnet-beta", "devnet", "testnet", "nano-live"):
            raise ValueError("Cluster must be 'mainnet-beta' or 'devnet'.")
        return c

    @field_validator("asset")
    @classmethod
    def validate_asset(cls, v: Optional[str]) -> str:
        a = (v or "USDC").strip().upper()
        if a not in ("USDC", "SOL", "XNO", "NANO"):
            raise ValueError("Asset must be 'USDC', 'SOL', or 'XNO'.")
        return a

    @field_validator("expected_payer")
    @classmethod
    def validate_payer(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return None
        s = v.strip()
        # Accept Solana base58 or Nano address (nano_...)
        if s.startswith("nano_") or ((32 <= len(s) <= 44) and BASE58_PATTERN.match(s)):
            return s
        raise ValueError("expected_payer must be valid base58 or nano_ address.")


class VerifyNanoPaymentInput(BaseModel):
    block_hash: str
    invoice_id: str
    claim_secret: str

    @field_validator("block_hash")
    @classmethod
    def validate_hash(cls, v: str) -> str:
        s = v.strip().lower()
        if not re.match(r"^[0-9a-f]{64}$", s):
            raise ValueError("Nano block_hash must be exactly 64 hexadecimal characters.")
        return s

    @field_validator("claim_secret")
    @classmethod
    def validate_secret(cls, v: str) -> str:
        s = v.strip()
        if not s.startswith("sec_") or len(s) < 20:
            raise ValueError("Invalid claim_secret format. Must start with 'sec_'.")
        return s


class ClaimInvoiceInput(BaseModel):
    claim_secret: str

    @field_validator("claim_secret")
    @classmethod
    def validate_secret(cls, v: str) -> str:
        s = v.strip()
        if not s.startswith("sec_") or len(s) < 20:
            raise ValueError("Invalid claim_secret format. Must start with 'sec_'.")
        return s


class ReconcilePaymentInput(BaseModel):
    transaction_signature: str
    invoice_id: Optional[str] = None
    expected_payer: Optional[str] = None
    auto_refund_unmatched: bool = False

    @field_validator("transaction_signature")
    @classmethod
    def validate_signature(cls, v: str) -> str:
        s = v.strip()
        if not (64 <= len(s) <= 90):
            raise ValueError("Transaction signature must be between 64 and 90 characters.")
        return s


class CreateChallengeInput(BaseModel):
    challenge_type: Optional[str] = "arithmetic"
    expiry_seconds: Optional[int] = 120


class VerifyChallengeInput(BaseModel):
    challenge_id: str
    answer: str


class WebhookPayload(BaseModel):
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


def _authenticate_refund_principal(request: Request) -> tuple[bool, bool, Optional[str]]:
    auth_header = request.headers.get("authorization", "")
    bearer_token = auth_header[7:].strip() if auth_header.lower().startswith("bearer ") else ""
    raw_api_key = request.headers.get("x-api-key") or request.query_params.get("api_key")
    if not raw_api_key and bearer_token and not bearer_token.startswith("adm_sess_"):
        raw_api_key = bearer_token
    metrics_token = os.getenv("METRICS_BEARER_TOKEN", "").strip()

    is_admin = False
    if bearer_token and storage.validate_admin_session(bearer_token):
        is_admin = True
    elif metrics_token and bearer_token and hmac.compare_digest(bearer_token, metrics_token):
        is_admin = True
    elif raw_api_key:
        key_info = storage.get_key_info(raw_api_key)
        if key_info and key_info.get("tier") == "admin":
            is_admin = True

    if is_admin:
        return True, True, f"admin:{getattr(request.client, 'host', 'operator')}"

    if raw_api_key:
        key_info = storage.get_key_info(raw_api_key)
        if key_info and key_info.get("is_active"):
            return True, False, key_info["key_hash"]

    return False, False, None


@router.get("/v1/payments/config")
def get_payment_details():
    cfg = load_payment_config()
    return {
        "success": True,
        "accepted_rails": ["solana", "nano"],
        "solana_treasury_wallet": cfg["solana_treasury_wallet"],
        "usdc_spl_mint_contract": CANONICAL_USDC_MINT,
        "recipient_warning": (
            f"Always send SOL and SPL USDC transfers to solana_treasury_wallet ({cfg['solana_treasury_wallet']}). "
            f"Never send funds directly to the USDC SPL Mint contract address ({CANONICAL_USDC_MINT})."
        ),
        "nano_treasury_address": cfg.get("nano_treasury_address", "nano_3t1sxtuxyjgdabj6miwn6st58p8x553i8ybkikoc9ozn7mra7kk71iysfyn1"),
        "accepted_assets": ["SOL", "USDC (Solana SPL)", "XNO (Nano Zero-Fee)"],
        "supported_clusters": ["mainnet-beta", "devnet"],
        "pricing_tiers": cfg["rates"],
        "topup_packages": cfg.get("topup_packages", {}),
        "create_invoice_endpoint": "POST /v1/payments/invoice",
        "verify_solana_endpoint": "POST /v1/payments/verify-solana",
        "verify_nano_endpoint": "POST /v1/payments/verify-nano",
        "reconcile_endpoint": "POST /v1/payments/reconcile",
        "claim_endpoint": "POST /v1/payments/invoice/:invoice_id/claim",
        "unmatched_payments_endpoint": "GET /v1/payments/unmatched",
        "refund_endpoint": "POST /v1/payments/refund/:unmatched_id",
        "refund_policy": "Automated refund minus network fee for unmatched, expired, or out-of-bounds transfers.",
    }


@router.post("/v1/payments/invoice")
def create_payment_invoice(req: CreateInvoiceInput, request: Request):
    client_ip = get_client_ip(request)

    # Rate limiting: max 20 invoice creation attempts per minute per IP
    allowed, retry_after = rate_limiter.is_allowed(f"create_invoice:{client_ip}", limit=20, window_seconds=60)
    if not allowed:
        record_rate_limit("/v1/payments/invoice")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many invoice creation requests. Please retry in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )

    cfg = load_payment_config()
    if req.target_tier in cfg.get("topup_packages", {}):
        if not req.target_api_key:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A target_api_key is required when creating an invoice for a credit top-up package.",
            )
        pkg_info = cfg["topup_packages"][req.target_tier]
        credits = pkg_info["credits"]
        raw_amount = pkg_info["usdc_units"] if req.asset == "USDC" else pkg_info["sol_lamports"]
    elif req.target_tier in cfg["rates"]:
        tier_info = cfg["rates"][req.target_tier]
        credits = tier_info["credits"]
        if getattr(req, "rail", "solana") == "nano":
            raw_amount = int(tier_info.get("nano_raw", int(tier_info["usd"] * 1e30)))
        elif req.asset == "USDC":
            raw_amount = tier_info["usdc_units"]
        else:
            raw_amount = tier_info["sol_lamports"]
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown target_tier '{req.target_tier}'.",
        )
    ttl = cfg.get("invoice_ttl_seconds", 1800)

    target_key_hash = None
    if req.target_api_key:
        target_info = storage.get_key_info(req.target_api_key)
        if not target_info:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Target API key not found.")
        target_key_hash = storage.hash_key(req.target_api_key)

    target_rail = req.rail or "solana"
    target_cluster = req.cluster or cfg.get("cluster", "mainnet-beta")
    recipient_addr = nano_adapter.merchant_address if target_rail == "nano" else cfg["solana_treasury_wallet"]

    if target_rail == "nano":
        tier_usd = cfg["rates"][req.target_tier]["usd"] if req.target_tier in cfg["rates"] else 1.0
        inv_record, claim_secret, reference = storage.create_invoice(
            tier=req.target_tier,
            credits=credits,
            asset="XNO",
            amount_raw=int(raw_amount),
            recipient=recipient_addr,
            cluster="nano-live",
            expiry_seconds=ttl,
            expected_payer=req.expected_payer,
            target_key_hash=target_key_hash,
            rail="nano",
        )
        nano_spec = nano_adapter.generate_nano_invoice(
            invoice_id=inv_record["invoice_id"],
            tier=req.target_tier,
            amount_usd=tier_usd,
            credits=credits,
        )
        return {
            "success": True,
            "invoice_id": inv_record["invoice_id"],
            "rail": "nano",
            "tier": inv_record["tier"],
            "credits": inv_record["credits"],
            "asset": "XNO",
            "amount_raw": nano_spec["amount_raw"],
            "amount_xno": nano_spec["amount_xno"],
            "recipient": recipient_addr,
            "merchant_address": recipient_addr,
            "claim_secret": claim_secret,
            "instructions": nano_spec["instructions"],
            "expires_at": inv_record["expires_at"],
            "verify_endpoint": "POST /v1/payments/verify-nano",
        }

    inv_record, claim_secret, reference = storage.create_invoice(
        tier=req.target_tier,
        credits=credits,
        asset=req.asset,
        amount_raw=raw_amount,
        recipient=recipient_addr,
        cluster=target_cluster,
        expiry_seconds=ttl,
        expected_payer=req.expected_payer,
        target_key_hash=target_key_hash,
        rail="solana",
    )

    if req.asset == "USDC":
        formatted_amt = f"{raw_amount / 1_000_000:.2f} USDC"
        solana_pay_url = (
            f"solana:{cfg['solana_treasury_wallet']}?amount={raw_amount / 1_000_000:.2f}"
            f"&spl-token={CANONICAL_USDC_MINT}&reference={reference}&label=Moltbook+Alpha&message={req.target_tier}"
        )
    else:
        formatted_amt = f"{raw_amount / 1_000_000_000:.4f} SOL"
        solana_pay_url = (
            f"solana:{cfg['solana_treasury_wallet']}?amount={raw_amount / 1_000_000_000:.4f}"
            f"&reference={reference}&label=Moltbook+Alpha&message={req.target_tier}"
        )

    storage.log_audit_event(
        "invoice_created",
        f"Invoice {inv_record['invoice_id']} created for {req.target_tier} ({formatted_amt}) [ref: {reference[:12]}...]",
        ip_address=client_ip,
    )

    return {
        "success": True,
        "invoice_id": inv_record["invoice_id"],
        "reference": reference,
        "target_tier": req.target_tier,
        "credits": credits,
        "asset": req.asset,
        "amount_raw": raw_amount,
        "amount_formatted": formatted_amt,
        "treasury_wallet": cfg["solana_treasury_wallet"],
        "cluster": inv_record["cluster"],
        "solana_pay_url": solana_pay_url,
        "claim_secret": claim_secret,
        "created_at": inv_record["created_at"],
        "expires_at": inv_record["expires_at"],
        "instructions": (
            f"Send {formatted_amt} to treasury wallet {cfg['solana_treasury_wallet']} including "
            f"reference account '{reference}'. Then submit the signature with invoice_id '{inv_record['invoice_id']}' "
            "to POST /v1/payments/verify-solana. Keep your claim_secret safe for credential recovery."
        ),
    }


@router.get("/v1/payments/invoice/{invoice_id}")
def get_invoice_status(invoice_id: str):
    inv = storage.get_invoice(invoice_id)
    if not inv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Invoice '{invoice_id}' not found.",
        )
    return {
        "success": True,
        "invoice_id": inv["invoice_id"],
        "reference": inv["reference"],
        "status": inv["status"],
        "tier": inv["tier"],
        "credits": inv["credits"],
        "asset": inv["asset"],
        "amount_raw": inv["amount_raw"],
        "recipient": inv["recipient"],
        "cluster": inv["cluster"],
        "tx_signature": inv.get("tx_signature"),
        "created_at": inv["created_at"],
        "expires_at": inv["expires_at"],
        "fulfilled_at": inv.get("fulfilled_at"),
    }


@router.post("/v1/payments/invoice/{invoice_id}/claim")
def claim_invoice_credential(invoice_id: str, req: ClaimInvoiceInput, request: Request):
    client_ip = get_client_ip(request)

    # Rate limiting: max 10 claim attempts per minute per IP
    allowed, retry_after = rate_limiter.is_allowed(f"claim_invoice:{client_ip}", limit=10, window_seconds=60)
    if not allowed:
        record_rate_limit(f"/v1/payments/invoice/{invoice_id}/claim")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many credential claim attempts. Please retry in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )

    try:
        recovered = storage.claim_invoice_credential(invoice_id, req.claim_secret)
    except StorageError as e:
        storage.log_audit_event(
            "claim_credential_failed",
            f"Claim failed for invoice {invoice_id}: {e!s}",
            ip_address=client_ip,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e

    storage.log_audit_event(
        "claim_credential_success",
        f"Claim recovered key {recovered['key_prefix']} for invoice {invoice_id}",
        ip_address=client_ip,
    )

    return {
        "success": True,
        "status": "recovered",
        "api_key": recovered["api_key"],
        "key_prefix": recovered["key_prefix"],
        "tier": recovered["tier"],
        "credits": recovered["credits"],
        "invoice_id": invoice_id,
        "message": recovered["message"],
    }


@router.post("/v1/challenges")
def create_challenge(request: Request, req: Optional[CreateChallengeInput] = None):
    """
    Creates a new verification challenge with a short TTL (default: 120s).
    Returns the challenge question and challenge ID without disclosing the expected answer.
    """
    client_ip = get_client_ip(request)
    allowed, retry_after = rate_limiter.is_allowed(f"create_challenge:{client_ip}", limit=30, window_seconds=60)
    if not allowed:
        raise ApiError(
            code=ErrorCode.RATE_LIMITED,
            status_code=429,
            retryable=True,
            retry_after=retry_after,
            message=f"Rate limit exceeded. Please retry in {retry_after} seconds.",
        )

    ch_type = (req.challenge_type if req and req.challenge_type else "arithmetic")
    expiry = (req.expiry_seconds if req and req.expiry_seconds else 120)
    record = storage.create_verification_challenge(challenge_type=ch_type, expiry_seconds=expiry)
    return {
        "success": True,
        "challenge_id": record["challenge_id"],
        "challenge_type": record["challenge_type"],
        "challenge_text": record["challenge_text"],
        "status": record["status"],
        "expires_at": record["expires_at"],
        "created_at": record["created_at"],
    }


@router.get("/v1/challenges/{challenge_id}")
def get_challenge_status(challenge_id: str, request: Request):
    """
    Inspects the status of an existing verification challenge.
    Never exposes internal secrets or expected answers.
    """
    record = storage.get_verification_challenge(challenge_id)
    if not record:
        raise ApiError(
            code=ErrorCode.CHALLENGE_NOT_FOUND,
            status_code=404,
            retryable=False,
            outcome=OperationOutcome.NOT_COMMITTED,
            state_effect="none",
            recovery_action=RecoveryAction.REQUEST_NEW_CHALLENGE,
            message="Verification challenge was not found.",
        )
    return {
        "success": True,
        "challenge_id": record["challenge_id"],
        "challenge_type": record["challenge_type"],
        "challenge_text": record["challenge_text"],
        "status": record["status"],
        "expires_at": record["expires_at"],
        "created_at": record["created_at"],
        "verified_at": record.get("verified_at"),
        "proof_token": record.get("proof_token"),
    }


@router.post("/v1/challenges/verify")
def verify_challenge(req: VerifyChallengeInput, request: Request):
    """
    Submits an answer for a verification challenge.
    Evaluates against atomic SQLite state machine:
    - If challenge does not exist -> 404 CHALLENGE_NOT_FOUND
    - If challenge is expired -> 410 CHALLENGE_EXPIRED
    - If challenge is already consumed -> 410 CHALLENGE_CONSUMED
    - If challenge was already answered -> 409 CHALLENGE_ALREADY_ANSWERED (returns existing proof)
    - If answer is wrong -> consumes challenge, returns 400 WRONG_ANSWER
    - If answer is correct -> transitions to solved, returns 200 with proof token
    """
    client_ip = get_client_ip(request)
    allowed, retry_after = rate_limiter.is_allowed(f"verify_challenge:{client_ip}", limit=30, window_seconds=60)
    if not allowed:
        raise ApiError(
            code=ErrorCode.RATE_LIMITED,
            status_code=429,
            retryable=True,
            retry_after=retry_after,
            message=f"Rate limit exceeded. Please retry in {retry_after} seconds.",
        )

    res = storage.verify_challenge_answer(req.challenge_id, req.answer)
    state = res.get("state")

    if state == "not_found":
        raise ApiError(
            code=ErrorCode.CHALLENGE_NOT_FOUND,
            status_code=404,
            retryable=False,
            outcome=OperationOutcome.NOT_COMMITTED,
            state_effect="none",
            recovery_action=RecoveryAction.REQUEST_NEW_CHALLENGE,
            message="Verification challenge was not found.",
        )
    elif state == "expired":
        raise ApiError(
            code=ErrorCode.CHALLENGE_EXPIRED,
            status_code=410,
            retryable=False,
            outcome=OperationOutcome.NOT_COMMITTED,
            state_effect="none",
            recovery_action=RecoveryAction.REQUEST_NEW_CHALLENGE,
            message="Verification challenge has expired past its validity window.",
        )
    elif state == "consumed":
        raise ApiError(
            code=ErrorCode.CHALLENGE_CONSUMED,
            status_code=410,
            retryable=False,
            outcome=OperationOutcome.NOT_COMMITTED,
            state_effect="challenge_consumed",
            recovery_action=RecoveryAction.REQUEST_NEW_CHALLENGE,
            message="This challenge has already been consumed by a prior failed attempt and can no longer be used.",
        )
    elif state == "wrong_answer":
        storage.log_audit_event(
            "challenge_wrong_answer",
            f"Challenge {req.challenge_id} failed with incorrect answer and was consumed.",
            ip_address=client_ip,
        )
        raise ApiError(
            code=ErrorCode.WRONG_ANSWER,
            status_code=400,
            retryable=False,
            outcome=OperationOutcome.NOT_COMMITTED,
            state_effect="challenge_consumed",
            recovery_action=RecoveryAction.REQUEST_NEW_CHALLENGE,
            message="Submitted challenge answer is incorrect. The challenge has been consumed and cannot be reused.",
        )
    elif state == "already_answered":
        raise ApiError(
            code=ErrorCode.CHALLENGE_ALREADY_ANSWERED,
            status_code=409,
            retryable=False,
            outcome=OperationOutcome.COMMITTED,
            state_effect="none",
            recovery_action=RecoveryAction.RETRIEVE_EXISTING_RESULT,
            message="This challenge was already successfully solved. The existing verification result can be retrieved.",
            details={
                "challenge_id": res["challenge_id"],
                "proof_token": res.get("proof_token"),
                "verified_at": res.get("verified_at"),
            },
        )

    storage.log_audit_event(
        "challenge_verified",
        f"Challenge {req.challenge_id} verified successfully. Issued proof {res['proof_token']}.",
        ip_address=client_ip,
    )
    return {
        "success": True,
        "challenge_id": res["challenge_id"],
        "status": "solved",
        "verified": True,
        "proof_token": res["proof_token"],
        "verified_at": res["verified_at"],
    }


@router.post("/v1/payments/verify-solana")
def verify_solana_payment(req: VerifyPaymentInput, request: Request, response: Response):
    client_ip = get_client_ip(request)

    # Rate limiting: max 10 payment verification attempts per minute per IP
    allowed, retry_after = rate_limiter.is_allowed(f"verify_solana:{client_ip}", limit=10, window_seconds=60)
    if not allowed:
        record_rate_limit("/v1/payments/verify-solana")
        storage.log_audit_event(
            "rate_limit_exceeded",
            f"Payment verification rate limit exceeded (limit: 10/min) [client_ip: {client_ip}]",
            ip_address=client_ip,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many payment verification requests. Please retry in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )

    sig = req.transaction_signature.strip()
    cfg = load_payment_config()

    # Replay check: if already redeemed, verify invoice and account binding
    existing_redemption = storage.get_payment_redemption(sig)
    if existing_redemption:
        # Cross-invoice replay prevention
        if req.invoice_id and existing_redemption.get("invoice_id") and existing_redemption["invoice_id"] != req.invoice_id:
            storage.log_audit_event(
                "payment_cross_invoice_replay_rejected",
                f"Signature {sig[:16]}... already redeemed for invoice {existing_redemption['invoice_id']}, rejected for invoice {req.invoice_id}",
                ip_address=client_ip,
            )
            raise ApiError(
                code=ErrorCode.DUPLICATE_PAYMENT_REUSE,
                message=f"Transaction signature was already redeemed for a different invoice ({existing_redemption['invoice_id']}).",
                status_code=409,
                outcome=OperationOutcome.NOT_COMMITTED,
                state_effect="none",
                recovery_action=RecoveryAction.CREATE_NEW_INVOICE,
                details={
                    "tx_signature": sig,
                    "existing_invoice_id": existing_redemption["invoice_id"],
                    "requested_invoice_id": req.invoice_id,
                },
            )

        # Cross-account replay prevention
        if req.invoice_id:
            inv = storage.get_invoice(req.invoice_id)
            if inv and inv.get("target_key_hash") and existing_redemption.get("key_hash") and inv["target_key_hash"] != existing_redemption["key_hash"]:
                storage.log_audit_event(
                    "payment_cross_account_replay_rejected",
                    f"Signature {sig[:16]}... already redeemed for different account, rejected for invoice {req.invoice_id}",
                    ip_address=client_ip,
                )
                raise ApiError(
                    code=ErrorCode.DUPLICATE_PAYMENT_REUSE,
                    message="Transaction signature was already redeemed for a different account.",
                    status_code=409,
                    outcome=OperationOutcome.NOT_COMMITTED,
                    state_effect="none",
                    recovery_action=RecoveryAction.CREATE_NEW_INVOICE,
                )

        storage.log_audit_event(
            "payment_replay_attempt",
            f"Replay detected for sig={sig[:16]}..., returning existing key {existing_redemption['key_prefix']}",
            ip_address=client_ip,
        )
        recovered_key = None
        inv_id = existing_redemption.get("invoice_id") or req.invoice_id
        if req.claim_secret and inv_id:
            try:
                claim_res = storage.claim_invoice_credential(inv_id, req.claim_secret)
                recovered_key = claim_res.get("api_key")
            except Exception:
                pass
        return {
            "success": True,
            "message": "Key previously redeemed for this transaction signature.",
            "api_key": recovered_key,
            "key_prefix": existing_redemption["key_prefix"],
            "tier": existing_redemption["tier"],
            "credits": existing_redemption["remaining_credits"],
            "invoice_id": inv_id,
        }

    # Resolve invoice
    invoice = None
    if req.invoice_id:
        invoice = storage.get_invoice(req.invoice_id)
        if not invoice:
            raise ApiError(
                code=ErrorCode.RESOURCE_NOT_FOUND,
                status_code=404,
                message=f"Invoice '{req.invoice_id}' not found.",
                outcome=OperationOutcome.NOT_COMMITTED,
                state_effect="none",
                recovery_action=RecoveryAction.CREATE_NEW_INVOICE,
            )
        if invoice["status"] == "fulfilled":
            redemption = storage.get_payment_redemption(invoice.get("tx_signature") or sig)
            recovered_key = None
            if req.claim_secret:
                try:
                    claim_res = storage.claim_invoice_credential(invoice["invoice_id"], req.claim_secret)
                    recovered_key = claim_res.get("api_key")
                except Exception:
                    pass
            return {
                "success": True,
                "message": "Invoice was already fulfilled.",
                "api_key": recovered_key,
                "key_prefix": redemption["key_prefix"] if redemption else "",
                "tier": invoice["tier"],
                "credits": invoice["credits"],
                "invoice_id": invoice["invoice_id"],
            }
        now_iso = datetime.now(timezone.utc).isoformat()
        is_expired = (invoice["status"] == "expired" or now_iso > invoice["expires_at"])
        if is_expired:
            try:
                exp_verifier = SolanaPaymentVerifier(
                    max_age_seconds=cfg.get("max_age_seconds", 3600),
                    require_consensus=False,
                )
                exp_payment = exp_verifier.verify_payment(
                    sig,
                    requested_tier=invoice["tier"],
                    expected_payer=req.expected_payer,
                    expected_reference=invoice["reference"],
                )
                unm = storage.record_unmatched_payment(
                    rail="solana",
                    tx_signature=exp_payment.tx_signature,
                    payer_wallet=exp_payment.payer,
                    asset=exp_payment.asset,
                    amount_raw=exp_payment.amount_raw,
                    expected_amount_raw=invoice["amount_raw"],
                    reason="EXPIRED_INVOICE_PAID",
                )
                raise ApiError(
                    code=ErrorCode.INVOICE_EXPIRED,
                    status_code=400,
                    message=f"Invoice '{req.invoice_id}' has expired. Valid on-chain transfer detected and held in unmatched ledger ({unm['unmatched_id']}) for refund.",
                    outcome=OperationOutcome.NOT_COMMITTED,
                    state_effect="recorded_unmatched",
                    recovery_action=RecoveryAction.CREATE_NEW_INVOICE,
                    details={
                        "unmatched_id": unm["unmatched_id"],
                        "refund_endpoint": f"POST /v1/payments/refund/{unm['unmatched_id']}",
                    },
                )
            except (VerificationError, RPCError):
                pass

            raise ApiError(
                code=ErrorCode.INVOICE_EXPIRED,
                status_code=400,
                message=f"Invoice '{req.invoice_id}' has expired. Please create a new invoice.",
                outcome=OperationOutcome.NOT_COMMITTED,
                state_effect="none",
                recovery_action=RecoveryAction.CREATE_NEW_INVOICE,
            )
    elif req.expected_reference:
        invoice = storage.get_invoice_by_reference(req.expected_reference)

    if not invoice:
        # Reject unbound payment attempts to prevent front-running
        raise ApiError(
            code=ErrorCode.UNBOUND_PAYMENT_REJECTED,
            status_code=400,
            message=(
                "Payment verification requires an active invoice. Unbound payments without an "
                "invoice ID or invoice reference are rejected to protect against transaction front-running. "
                "Please create an invoice via POST /v1/payments/invoice before submitting payment."
            ),
            outcome=OperationOutcome.NOT_COMMITTED,
            state_effect="none",
            recovery_action=RecoveryAction.CREATE_NEW_INVOICE,
        )

    expected_ref = invoice["reference"]
    target_tier = invoice["tier"]
    expected_payer = req.expected_payer
    verifier = SolanaPaymentVerifier(
        max_age_seconds=cfg.get("max_age_seconds", 1800),
        require_consensus=cfg.get("require_consensus", False),
    )

    try:
        payment = in_flight_deduplicator.execute(
            sig,
            lambda: verifier.verify_payment(
                sig,
                requested_tier=target_tier,
                expected_payer=expected_payer,
                expected_reference=expected_ref,
            ),
        )
    except VerificationError as e:
        record_payment("UNKNOWN", target_tier, "failed")
        storage.log_audit_event(
            "payment_verification_failed",
            f"Verification rejected for sig={sig[:16]}...: {e!s}",
            ip_address=client_ip,
        )
        raise ApiError(
            code=ErrorCode.PAYMENT_VERIFICATION_FAILED,
            status_code=400,
            retryable=False,
            outcome=OperationOutcome.NOT_COMMITTED,
            state_effect="none",
            recovery_action=RecoveryAction.CREATE_NEW_INVOICE,
            message=f"Payment verification failed: {e!s}",
        ) from e
    except RPCError as e:
        record_payment("UNKNOWN", target_tier, "rpc_error")
        storage.log_audit_event(
            "payment_rpc_error",
            f"RPC failure verifying sig={sig[:16]}...: {e!s}",
            ip_address=client_ip,
        )
        raise ApiError(
            code=ErrorCode.RPC_GATEWAY_ERROR,
            status_code=502,
            retryable=True,
            retry_after=5,
            outcome=OperationOutcome.INDETERMINATE,
            state_effect="none",
            recovery_action=RecoveryAction.POLL_PAYMENT_STATUS,
            message=f"Solana RPC communication error: {e!s}",
        ) from e

    # Verify payment matches invoice asset and amount
    if payment.asset != invoice["asset"]:
        unm = storage.record_unmatched_payment(
            rail="solana",
            tx_signature=payment.tx_signature,
            payer_wallet=payment.payer,
            asset=payment.asset,
            amount_raw=payment.amount_raw,
            expected_amount_raw=invoice["amount_raw"],
            reason=f"ASSET_MISMATCH: expected {invoice['asset']}, received {payment.asset}",
        )
        raise ApiError(
            code=ErrorCode.PAYMENT_VERIFICATION_FAILED,
            status_code=400,
            retryable=False,
            outcome=OperationOutcome.NOT_COMMITTED,
            state_effect="recorded_unmatched",
            recovery_action=RecoveryAction.CREATE_NEW_INVOICE,
            message=f"Payment asset '{payment.asset}' does not match invoice expected asset '{invoice['asset']}'. Recorded in unmatched ledger: {unm['unmatched_id']}",
            details={
                "unmatched_id": unm["unmatched_id"],
                "refund_endpoint": f"POST /v1/payments/refund/{unm['unmatched_id']}",
            },
        )
    if payment.amount_raw < invoice["amount_raw"]:
        unm = storage.record_unmatched_payment(
            rail="solana",
            tx_signature=payment.tx_signature,
            payer_wallet=payment.payer,
            asset=payment.asset,
            amount_raw=payment.amount_raw,
            expected_amount_raw=invoice["amount_raw"],
            reason="UNDERPAID_AMOUNT",
        )
        raise ApiError(
            code=ErrorCode.PAYMENT_VERIFICATION_FAILED,
            status_code=400,
            retryable=False,
            outcome=OperationOutcome.NOT_COMMITTED,
            state_effect="recorded_unmatched",
            recovery_action=RecoveryAction.CREATE_NEW_INVOICE,
            message=f"Payment amount ({payment.amount_raw}) is below the minimum required amount ({invoice['amount_raw']}). Recorded in unmatched ledger: {unm['unmatched_id']}",
            details={
                "unmatched_id": unm["unmatched_id"],
                "refund_endpoint": f"POST /v1/payments/refund/{unm['unmatched_id']}",
            },
        )

    # Atomic fulfillment and redemption
    try:
        redemption_result = storage.fulfill_invoice_and_redeem(
            invoice_id=invoice["invoice_id"],
            tx_signature=payment.tx_signature,
            asset=payment.asset,
            amount_raw=payment.amount_raw,
            tier=payment.tier,
            credits_to_grant=payment.credits,
            claim_secret=req.claim_secret,
            payer=payment.payer,
            reference=payment.reference or expected_ref,
            slot=payment.slot,
            block_time=payment.block_time,
        )
    except StorageError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invoice settlement failed: {e!s}",
        ) from e

    record_payment(payment.asset, payment.tier, redemption_result["status"])

    if redemption_result["status"] == "already_redeemed":
        storage.log_audit_event(
            "payment_replay_attempt",
            f"Replay detected for sig={sig[:16]}..., returning existing key {redemption_result['key_prefix']}",
            ip_address=client_ip,
        )
        return {
            "success": True,
            "message": "Key previously redeemed for this transaction signature.",
            "key_prefix": redemption_result["key_prefix"],
            "tier": redemption_result["tier"],
            "credits": redemption_result["credits"],
        }

    storage.log_audit_event(
        "payment_redeemed_success",
        f"Redeemed {payment.asset} (raw: {payment.amount_raw}) for invoice {invoice['invoice_id']} tier {payment.tier} ({payment.credits} credits). Key: {redemption_result['key_prefix']} [rpc: {payment.rpc_endpoint_used}]",
        ip_address=client_ip,
    )

    return {
        "success": True,
        "status": redemption_result["status"],
        "message": redemption_result["message"],
        "api_key": redemption_result.get("api_key"),
        "key_prefix": redemption_result["key_prefix"],
        "credits": redemption_result["credits"],
        "tier": redemption_result["tier"],
        "invoice_id": invoice["invoice_id"],
    }


@router.post("/v1/payments/verify-nano")
def verify_nano_payment(req: VerifyNanoPaymentInput, request: Request):
    """
    Verifies zero-fee settlement on the Nano network.
    Fulfills the invoice, credits the user account, and returns an Ed25519 witness receipt.
    """
    client_ip = get_client_ip(request)
    allowed, retry_after = rate_limiter.is_allowed(f"verify_nano:{client_ip}", limit=30, window_seconds=60)
    if not allowed:
        record_rate_limit("/v1/payments/verify-nano")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many verification requests. Retry in {retry_after} seconds.",
        )

    invoice = storage.get_invoice(req.invoice_id)
    if not invoice:
        unm = storage.record_unmatched_payment(
            rail="nano",
            tx_signature=req.block_hash,
            payer_wallet="unknown_nano_payer",
            asset="XNO",
            amount_raw=0,
            expected_amount_raw=None,
            reason="UNMATCHED_ORDER",
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Invoice '{req.invoice_id}' not found. Recorded unmatched holding: {unm['unmatched_id']}",
        )

    if invoice["status"] == "fulfilled":
        try:
            recovered = storage.claim_invoice_credential(req.invoice_id, req.claim_secret)
            return {
                "success": True,
                "api_key": recovered["api_key"],
                "credits": recovered["credits"],
                "tier": recovered["tier"],
                "message": "Payment already verified. Retrieved existing API key.",
            }
        except Exception:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Invoice already fulfilled.")

    if invoice.get("rail") != "nano":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invoice '{req.invoice_id}' is on rail '{invoice.get('rail')}', not 'nano'.",
        )

    try:
        settlement = nano_adapter.verify_settlement(
            block_hash=req.block_hash,
            expected_raw=int(invoice["amount_raw"]),
        )
    except Exception as e:
        storage.record_unmatched_payment(
            rail="nano",
            tx_signature=req.block_hash,
            payer_wallet="unknown_nano_payer",
            asset="XNO",
            amount_raw=int(invoice["amount_raw"]),
            expected_amount_raw=int(invoice["amount_raw"]),
            reason="SETTLEMENT_VERIFICATION_FAILED",
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    res = storage.fulfill_invoice_and_redeem(
        invoice_id=req.invoice_id,
        tx_signature=req.block_hash,
        asset=invoice["asset"],
        amount_raw=int(invoice["amount_raw"]),
        tier=invoice["tier"],
        credits_to_grant=invoice["credits"],
        claim_secret=req.claim_secret,
        payer=settlement.get("recipient", nano_adapter.merchant_address),
    )

    witness_id = None
    if witness_manager:
        try:
            w = witness_manager.create_witness(
                action="NANO_PAYMENT_VERIFIED",
                actor="payment_system",
                key_hash=storage.hash_key(res["api_key"]) if res.get("api_key") else None,
                credit_delta=invoice["credits"],
                post_balance=res.get("credits", invoice["credits"]),
                request_id=getattr(request.state, "request_id", None) or f"req_{secrets.token_hex(8)}",
                environmental_anchor={
                    "rail": "nano",
                    "block_hash": req.block_hash,
                    "invoice_id": req.invoice_id,
                },
            )
            witness_id = w.get("witness_id")
        except Exception:
            pass

    return {
        "success": True,
        "api_key": res.get("api_key"),
        "credits": res.get("credits", invoice["credits"]),
        "tier": invoice["tier"],
        "rail": "nano",
        "block_hash": req.block_hash,
        "state_witness_id": witness_id,
    }


@router.get("/v1/payments/unmatched")
def get_unmatched_payments(
    status_filter: Optional[str] = "HELD",
    payer_wallet: Optional[str] = None,
    limit: int = 50,
):
    """
    Returns list of unmatched, underpaid, or expired payments currently held
    awaiting automated or manual refund dispatch.
    """
    records = storage.list_unmatched_payments(
        status=status_filter,
        payer_wallet=payer_wallet,
        limit=min(limit, 100),
    )
    now = datetime.now(timezone.utc)
    ages = []
    for r in records:
        ts = r.get("created_at")
        if ts:
            try:
                dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                ages.append(max(0.0, (now - dt).total_seconds()))
            except Exception:
                pass
    if ages:
        oldest_age_sec = max(ages)
        ages.sort()
        p95_idx = int(0.95 * (len(ages) - 1))
        p95_age_sec = ages[p95_idx]
    else:
        oldest_age_sec = 0.0
        p95_age_sec = 0.0

    return {
        "count": len(records),
        "status_filter": status_filter,
        "oldest_unmatched_age_seconds": round(oldest_age_sec, 2),
        "p95_unmatched_age_seconds": round(p95_age_sec, 2),
        "quarantine_alarm": oldest_age_sec > 3600.0,
        "unmatched_payments": records,
    }


@router.post("/v1/payments/refund/{unmatched_id}/challenge")
def request_refund_challenge(unmatched_id: str, request: Request):
    """
    Issues a machine-readable step-up confirmation challenge for an unmatched refund.
    """
    is_authenticated, is_admin, principal_id = _authenticate_refund_principal(request)
    if not is_authenticated:
        req_id = getattr(request.state, "request_id", None) or f"req_{secrets.token_hex(8)}"
        payload = format_error_payload(
            code=ErrorCode.AUTHENTICATION_REQUIRED.value,
            message="Authentication required: Valid API key or administrator session is required to request a refund challenge.",
            request_id=req_id,
            status_code=401,
            details={"unmatched_id": unmatched_id},
            recovery_action=RecoveryAction.REAUTHENTICATE,
        )
        return JSONResponse(status_code=401, content=payload, headers={"WWW-Authenticate": "Bearer"})

    record = storage.get_unmatched_payment(unmatched_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unmatched payment record '{unmatched_id}' not found.",
        )
    if record["status"] != "HELD":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Payment '{unmatched_id}' has already been processed with status '{record['status']}'.",
        )
    params = {
        "unmatched_id": unmatched_id,
        "amount_raw": record.get("amount_raw"),
        "asset": record.get("asset"),
        "payer_wallet": record.get("payer_wallet"),
    }
    challenge = confirm_store.issue(
        action="REFUND_PAYMENT",
        principal_id=principal_id,
        params=params,
        consequence_summary={
            "warning": "Executing this operation will permanently dispatch an on-chain refund from the treasury wallet.",
            "unmatched_id": unmatched_id,
            "payer_wallet": record.get("payer_wallet"),
            "asset": record.get("asset"),
            "amount_raw": record.get("amount_raw"),
        },
    )
    return {
        "challenge_nonce": challenge.nonce,
        "action": challenge.action,
        "expires_at": challenge.expires_at,
        "ttl_seconds": confirm_store.default_ttl_seconds,
        "confirm_header": "X-Confirmation-Nonce",
        "consequence_summary": challenge.consequence_summary,
    }


@router.post("/v1/payments/refund/{unmatched_id}")
def process_unmatched_refund(unmatched_id: str, request: Request):
    """
    Dispatches automated refund for an unmatched payment back to payer_wallet
    minus the minimal network transaction fee. Supports machine-readable step-up
    confirmation nonces via ConfirmStore.
    """
    # Step-Up Confirmation & Authentication Enforcement
    is_authenticated, is_admin, principal_id = _authenticate_refund_principal(request)
    nonce = request.headers.get("X-Confirmation-Nonce") or request.query_params.get("confirmation_nonce")

    if not is_authenticated and not nonce:
        req_id = getattr(request.state, "request_id", None) or f"req_{secrets.token_hex(8)}"
        payload = format_error_payload(
            code=ErrorCode.AUTHENTICATION_REQUIRED.value,
            message="Authentication required: Valid API key or administrator session is required to initiate a refund.",
            request_id=req_id,
            status_code=401,
            details={"unmatched_id": unmatched_id},
            recovery_action=RecoveryAction.REAUTHENTICATE,
        )
        return JSONResponse(status_code=401, content=payload, headers={"WWW-Authenticate": "Bearer"})

    record = storage.get_unmatched_payment(unmatched_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unmatched payment record '{unmatched_id}' not found.",
        )
    if record["status"] != "HELD":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Payment '{unmatched_id}' has already been processed with status '{record['status']}'.",
        )

    is_admin_bypass = is_admin and (request.headers.get("X-Admin-Bypass-Confirmation") == "true")
    require_confirmation = (
        not is_admin_bypass
        and (
            getattr(confirm_store, "strict_mode", True)
            or request.headers.get("X-Require-Confirmation") == "true"
            or request.query_params.get("require_confirmation") == "true"
        )
    )
    effective_principal = principal_id or getattr(request.state, "key_hash", None) or (request.client.host if request.client else "unknown")
    params = {
        "unmatched_id": unmatched_id,
        "amount_raw": record.get("amount_raw"),
        "asset": record.get("asset"),
        "payer_wallet": record.get("payer_wallet"),
    }

    if require_confirmation and not nonce:
        challenge = confirm_store.issue(
            action="REFUND_PAYMENT",
            principal_id=effective_principal,
            params=params,
            consequence_summary={
                "warning": "Executing this operation will permanently dispatch an on-chain refund from the treasury wallet.",
                "unmatched_id": unmatched_id,
                "payer_wallet": record.get("payer_wallet"),
                "asset": record.get("asset"),
                "amount_raw": record.get("amount_raw"),
            },
        )
        req_id = getattr(request.state, "request_id", None) or f"req_{secrets.token_hex(8)}"
        payload = format_error_payload(
            code=ErrorCode.POLICY_CONFIRMATION_REQUIRED.value,
            message="Step-up confirmation required: This action will permanently dispatch an on-chain refund transaction from the treasury.",
            request_id=req_id,
            status_code=428,
            details={
                "challenge_nonce": challenge.nonce,
                "expires_at": challenge.expires_at,
                "consequence_summary": challenge.consequence_summary,
            },
            recovery={
                "action": RecoveryAction.CONFIRM_OPERATION.value,
                "challenge_nonce": challenge.nonce,
                "expires_at": challenge.expires_at,
                "confirm_header": "X-Confirmation-Nonce",
            },
        )
        return JSONResponse(status_code=428, content=payload)

    if nonce:
        ok, reason = confirm_store.verify_and_consume(
            nonce=nonce,
            action="REFUND_PAYMENT",
            principal_id=effective_principal,
            params=params,
        )
        if not ok:
            req_id = getattr(request.state, "request_id", None) or f"req_{secrets.token_hex(8)}"
            payload = format_error_payload(
                code=ErrorCode.CONFIRMATION_NONCE_INVALID.value,
                message=f"Confirmation challenge validation failed: {reason}",
                request_id=req_id,
                status_code=410,
                details={"reason": reason, "nonce": nonce},
                recovery_action=RecoveryAction.INSPECT_PARAMETERS,
            )
            return JSONResponse(status_code=410, content=payload)

    try:
        dispatch_result = refund_dispatcher.dispatch_refund(record)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Refund dispatch failed: {e!s}",
        )

    storage.mark_unmatched_refunded(
        unmatched_id=unmatched_id,
        refund_tx_sig=dispatch_result["refund_tx_sig"],
        refunded_amount_raw=dispatch_result["refund_amount_raw"],
    )
    storage.log_audit_event(
        "payment_refund_dispatched",
        f"Refund {dispatch_result['refund_amount_raw']} {record['asset']} dispatched for {unmatched_id} to {record['payer_wallet']}",
    )

    witness_id = None
    witness_sig = None
    if witness_manager:
        try:
            w = witness_manager.create_witness(
                action="UNMATCHED_PAYMENT_REFUNDED",
                actor="refund_dispatcher",
                key_hash=None,
                credit_delta=0,
                post_balance=0,
                request_id=getattr(request.state, "request_id", None) or f"req_{secrets.token_hex(8)}",
                environmental_anchor={
                    "unmatched_id": unmatched_id,
                    "original_tx_signature": record["tx_signature"],
                    "refund_tx_sig": dispatch_result["refund_tx_sig"],
                    "payer_wallet": record["payer_wallet"],
                    "asset": record["asset"],
                    "refund_amount_raw": dispatch_result["refund_amount_raw"],
                },
            )
            witness_id = w.get("witness_id")
            witness_sig = w.get("signature")
        except Exception:
            pass

    return {
        "success": True,
        "unmatched_id": unmatched_id,
        "status": "REFUNDED",
        "payer_wallet": record["payer_wallet"],
        "asset": record["asset"],
        "refund_amount_raw": dispatch_result["refund_amount_raw"],
        "fee_deducted_raw": dispatch_result["fee_deducted_raw"],
        "refund_tx_sig": dispatch_result["refund_tx_sig"],
        "dispatched_at": dispatch_result["dispatched_at"],
        "state_witness_id": witness_id,
        "witness_signature": witness_sig,
    }


@router.post("/v1/payments/reconcile")
def reconcile_payment_endpoint(req: ReconcilePaymentInput, request: Request):
    """
    Reconciles an on-chain transaction signature against open invoices, redeemed ledgers,
    and unmatched payment quarantines.
    - If already redeemed, returns REDEEMED status and existing key prefix.
    - If matches an open invoice and satisfies asset/amount requirements, fulfills the invoice.
    - If sent without an invoice/reference (orphan deposit) or to an expired/mismatched invoice,
      quarantines the transfer into unmatched_payments and optionally triggers an automated refund
      signed by an Ed25519 state witness receipt.
    """
    client_ip = get_client_ip(request)
    allowed, retry_after = rate_limiter.is_allowed(f"reconcile_pay:{client_ip}", limit=20, window_seconds=60)
    if not allowed:
        record_rate_limit("/v1/payments/reconcile")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many reconciliation requests. Please retry in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )

    sig = req.transaction_signature.strip()
    req_id = getattr(request.state, "request_id", None) or f"req_{secrets.token_hex(8)}"

    # 1. Check if already redeemed
    redemption = storage.get_payment_redemption(sig)
    if redemption:
        w = witness_manager.create_witness(
            action="PAYMENT_RECONCILE_VERIFIED_REDEEMED",
            actor="reconciliation_engine",
            key_hash=redemption.get("key_hash"),
            credit_delta=0,
            post_balance=redemption.get("remaining_credits", 0),
            request_id=req_id,
            environmental_anchor={
                "tx_signature": sig,
                "reconciliation_status": "REDEEMED",
                "invoice_id": redemption.get("invoice_id"),
            },
        )
        return {
            "success": True,
            "reconciliation_status": "REDEEMED",
            "tx_signature": sig,
            "invoice_id": redemption.get("invoice_id"),
            "key_prefix": redemption.get("key_prefix"),
            "tier": redemption.get("tier"),
            "credits_granted": redemption.get("credits_granted"),
            "remaining_credits": redemption.get("remaining_credits"),
            "state_witness_id": w.get("witness_id"),
            "witness_signature": w.get("signature"),
        }

    # 2. Check if already quarantined in unmatched_payments
    existing_unmatched = None
    for item in storage.list_unmatched_payments(status=None, limit=200):
        if item.get("tx_signature") == sig:
            existing_unmatched = item
            break

    if existing_unmatched:
        if req.auto_refund_unmatched and existing_unmatched["status"] == "HELD":
            dispatch_result = refund_dispatcher.dispatch_refund(existing_unmatched)
            storage.mark_unmatched_refunded(
                unmatched_id=existing_unmatched["unmatched_id"],
                refund_tx_sig=dispatch_result["refund_tx_sig"],
                refunded_amount_raw=dispatch_result["refund_amount_raw"],
            )
            w = witness_manager.create_witness(
                action="UNMATCHED_PAYMENT_REFUNDED",
                actor="reconciliation_engine",
                key_hash=None,
                credit_delta=0,
                post_balance=0,
                request_id=req_id,
                environmental_anchor={
                    "unmatched_id": existing_unmatched["unmatched_id"],
                    "tx_signature": sig,
                    "refund_tx_sig": dispatch_result["refund_tx_sig"],
                    "refund_amount_raw": dispatch_result["refund_amount_raw"],
                },
            )
            return {
                "success": True,
                "reconciliation_status": "QUARANTINED_AND_REFUNDED",
                "tx_signature": sig,
                "unmatched_id": existing_unmatched["unmatched_id"],
                "reason": existing_unmatched["reason"],
                "payer_wallet": existing_unmatched["payer_wallet"],
                "asset": existing_unmatched["asset"],
                "refund_amount_raw": dispatch_result["refund_amount_raw"],
                "fee_deducted_raw": dispatch_result["fee_deducted_raw"],
                "refund_tx_sig": dispatch_result["refund_tx_sig"],
                "state_witness_id": w.get("witness_id"),
                "witness_signature": w.get("signature"),
            }

        w = witness_manager.create_witness(
            action="PAYMENT_RECONCILE_QUARANTINED",
            actor="reconciliation_engine",
            key_hash=None,
            credit_delta=0,
            post_balance=0,
            request_id=req_id,
            environmental_anchor={
                "unmatched_id": existing_unmatched["unmatched_id"],
                "tx_signature": sig,
                "status": existing_unmatched["status"],
                "reason": existing_unmatched["reason"],
            },
        )
        return {
            "success": True,
            "reconciliation_status": "QUARANTINED_UNMATCHED",
            "tx_signature": sig,
            "unmatched_id": existing_unmatched["unmatched_id"],
            "status": existing_unmatched["status"],
            "reason": existing_unmatched["reason"],
            "payer_wallet": existing_unmatched["payer_wallet"],
            "asset": existing_unmatched["asset"],
            "amount_raw": existing_unmatched["amount_raw"],
            "refund_endpoint": f"POST /v1/payments/refund/{existing_unmatched['unmatched_id']}",
            "state_witness_id": w.get("witness_id"),
            "witness_signature": w.get("signature"),
        }

    # 3. Inspect on-chain transaction via SolanaPaymentVerifier
    cfg = load_payment_config()
    invoice = storage.get_invoice(req.invoice_id) if req.invoice_id else None
    target_tier = invoice["tier"] if invoice else "tier_starter"
    expected_ref = invoice["reference"] if invoice else None

    verifier = SolanaPaymentVerifier(
        max_age_seconds=cfg.get("max_age_seconds", 86400),
        require_consensus=False,
    )
    try:
        payment = verifier.verify_payment(
            sig,
            requested_tier=target_tier,
            expected_payer=req.expected_payer,
            expected_reference=expected_ref,
        )
    except VerificationError as e:
        raise ApiError(
            code=ErrorCode.PAYMENT_VERIFICATION_FAILED,
            status_code=400,
            retryable=False,
            outcome=OperationOutcome.NOT_COMMITTED,
            state_effect="none",
            recovery_action=RecoveryAction.CREATE_NEW_INVOICE,
            message=f"On-chain reconciliation failed: {e!s}",
        ) from e
    except RPCError as e:
        raise ApiError(
            code=ErrorCode.RPC_GATEWAY_ERROR,
            status_code=502,
            retryable=True,
            retry_after=5,
            outcome=OperationOutcome.INDETERMINATE,
            state_effect="none",
            recovery_action=RecoveryAction.POLL_PAYMENT_STATUS,
            message=f"Solana RPC communication error during reconciliation: {e!s}",
        ) from e

    # Try resolving invoice by on-chain reference if invoice_id was not explicitly passed
    if not invoice and getattr(payment, "reference", None):
        invoice = storage.get_invoice_by_reference(payment.reference)

    # 4. Determine if orphan deposit or mismatched/expired invoice
    quarantine_reason = None
    expected_amt = None
    if not invoice:
        quarantine_reason = "UNLINKED_ORPHAN_DEPOSIT"
    else:
        expected_amt = invoice["amount_raw"]
        now_iso = datetime.now(timezone.utc).isoformat()
        is_expired = (invoice["status"] == "expired" or now_iso > invoice["expires_at"])
        if is_expired:
            quarantine_reason = "EXPIRED_INVOICE_PAID"
        elif payment.asset != invoice["asset"]:
            quarantine_reason = f"ASSET_MISMATCH: expected {invoice['asset']}, received {payment.asset}"
        elif payment.amount_raw < invoice["amount_raw"]:
            quarantine_reason = "UNDERPAID_AMOUNT"

    if quarantine_reason:
        unm = storage.record_unmatched_payment(
            rail="solana",
            tx_signature=payment.tx_signature,
            payer_wallet=payment.payer,
            asset=payment.asset,
            amount_raw=payment.amount_raw,
            expected_amount_raw=expected_amt,
            reason=quarantine_reason,
        )
        if req.auto_refund_unmatched:
            dispatch_result = refund_dispatcher.dispatch_refund(unm)
            storage.mark_unmatched_refunded(
                unmatched_id=unm["unmatched_id"],
                refund_tx_sig=dispatch_result["refund_tx_sig"],
                refunded_amount_raw=dispatch_result["refund_amount_raw"],
            )
            w = witness_manager.create_witness(
                action="UNMATCHED_PAYMENT_REFUNDED",
                actor="reconciliation_engine",
                key_hash=None,
                credit_delta=0,
                post_balance=0,
                request_id=req_id,
                environmental_anchor={
                    "unmatched_id": unm["unmatched_id"],
                    "tx_signature": payment.tx_signature,
                    "reason": quarantine_reason,
                    "refund_tx_sig": dispatch_result["refund_tx_sig"],
                    "refund_amount_raw": dispatch_result["refund_amount_raw"],
                },
            )
            return {
                "success": True,
                "reconciliation_status": "QUARANTINED_AND_REFUNDED",
                "tx_signature": payment.tx_signature,
                "unmatched_id": unm["unmatched_id"],
                "reason": quarantine_reason,
                "payer_wallet": payment.payer,
                "asset": payment.asset,
                "amount_raw": payment.amount_raw,
                "refund_amount_raw": dispatch_result["refund_amount_raw"],
                "fee_deducted_raw": dispatch_result["fee_deducted_raw"],
                "refund_tx_sig": dispatch_result["refund_tx_sig"],
                "state_witness_id": w.get("witness_id"),
                "witness_signature": w.get("signature"),
            }

        w = witness_manager.create_witness(
            action="PAYMENT_RECONCILE_QUARANTINED",
            actor="reconciliation_engine",
            key_hash=None,
            credit_delta=0,
            post_balance=0,
            request_id=req_id,
            environmental_anchor={
                "unmatched_id": unm["unmatched_id"],
                "tx_signature": payment.tx_signature,
                "reason": quarantine_reason,
                "payer_wallet": payment.payer,
                "amount_raw": payment.amount_raw,
            },
        )
        return {
            "success": True,
            "reconciliation_status": "QUARANTINED_UNMATCHED",
            "tx_signature": payment.tx_signature,
            "unmatched_id": unm["unmatched_id"],
            "status": "HELD",
            "reason": quarantine_reason,
            "payer_wallet": payment.payer,
            "asset": payment.asset,
            "amount_raw": payment.amount_raw,
            "refund_endpoint": f"POST /v1/payments/refund/{unm['unmatched_id']}",
            "state_witness_id": w.get("witness_id"),
            "witness_signature": w.get("signature"),
        }

    # 5. Valid open invoice match -> fulfill atomically
    redemption_result = storage.fulfill_invoice_and_redeem(
        invoice_id=invoice["invoice_id"],
        tx_signature=payment.tx_signature,
        asset=payment.asset,
        amount_raw=payment.amount_raw,
        tier=invoice["tier"],
        credits_to_grant=invoice["credits"],
        payer=payment.payer,
        reference=payment.reference or invoice["reference"],
        slot=payment.slot,
        block_time=payment.block_time,
    )
    w = witness_manager.create_witness(
        action="PAYMENT_RECONCILED_AND_REDEEMED",
        actor="reconciliation_engine",
        key_hash=storage.hash_key(redemption_result["api_key"]) if redemption_result.get("api_key") else None,
        credit_delta=invoice["credits"],
        post_balance=redemption_result.get("credits", invoice["credits"]),
        request_id=req_id,
        environmental_anchor={
            "invoice_id": invoice["invoice_id"],
            "tx_signature": payment.tx_signature,
            "tier": invoice["tier"],
            "credits": invoice["credits"],
        },
    )
    return {
        "success": True,
        "reconciliation_status": "RECONCILED_AND_FULFILLED",
        "tx_signature": payment.tx_signature,
        "invoice_id": invoice["invoice_id"],
        "api_key": redemption_result.get("api_key"),
        "key_prefix": redemption_result.get("key_prefix"),
        "tier": redemption_result.get("tier"),
        "credits": redemption_result.get("credits"),
        "state_witness_id": w.get("witness_id"),
        "witness_signature": w.get("signature"),
    }


@router.post("/v1/payments/webhook")
def handle_payment_webhook(
    req: WebhookPayload,
    request: Request,
    x_webhook_secret: Optional[str] = Header(None, alias="X-Webhook-Secret"),
):
    client_ip = get_client_ip(request)
    if not x_webhook_secret or x_webhook_secret != WEBHOOK_SECRET:
        record_webhook("auth_failed")
        storage.log_audit_event(
            "webhook_auth_failed",
            f"Unauthorized webhook attempt with secret prefix={str(x_webhook_secret)[:4]}... [client_ip: {client_ip}]",
            ip_address=client_ip,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-Webhook-Secret header.",
        )

    sig = req.transaction_signature.strip()
    cfg = load_payment_config()
    verifier = SolanaPaymentVerifier(
        max_age_seconds=cfg.get("max_age_seconds", 1800),
        require_consensus=cfg.get("require_consensus", False),
    )

    try:
        payment = in_flight_deduplicator.execute(
            sig,
            lambda: verifier.verify_payment(sig, req.target_tier),
        )
    except VerificationError as e:
        record_webhook("verification_failed")
        record_payment("UNKNOWN", req.target_tier or "tier_starter", "failed")
        storage.log_audit_event(
            "webhook_verification_failed",
            f"Webhook payment rejected for sig={sig[:16]}...: {e!s}",
            ip_address="webhook",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Webhook payment verification failed: {e!s}",
        ) from e
    except RPCError as e:
        record_webhook("rpc_error")
        record_payment("UNKNOWN", req.target_tier or "tier_starter", "rpc_error")
        storage.log_audit_event(
            "webhook_rpc_error",
            f"RPC failure in webhook for sig={sig[:16]}...: {e!s}",
            ip_address="webhook",
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Solana RPC communication error: {e!s}",
        ) from e

    redemption_result = storage.redeem_payment(
        tx_signature=payment.tx_signature,
        asset=payment.asset,
        amount_raw=payment.amount_raw,
        tier=payment.tier,
        credits_to_grant=payment.credits,
    )

    record_webhook(redemption_result["status"])
    record_payment(payment.asset, payment.tier, redemption_result["status"])

    event_type = "webhook_payment_redeemed" if redemption_result["status"] == "newly_minted" else "webhook_replay_detected"
    storage.log_audit_event(
        event_type,
        f"Webhook redemption {redemption_result['status']} for sig={sig[:16]}... [tier: {payment.tier}, credits: {payment.credits}]",
        ip_address="webhook",
    )

    return {
        "success": True,
        "status": redemption_result["status"],
        "tier": redemption_result["tier"],
        "credits": redemption_result["credits"],
        "key_prefix": redemption_result["key_prefix"],
        "api_key": redemption_result.get("api_key"),
        "message": redemption_result["message"],
    }


@router.get("/v1/payments/status/{signature}")
def get_payment_status(signature: str):
    sig = signature.strip()
    if not (80 <= len(sig) <= 90) or not BASE58_PATTERN.match(sig):
        raise HTTPException(
            status_code=getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422),
            detail="Solana transaction signature must be valid Base58 between 80 and 90 characters.",
        )

    redemption = storage.get_payment_redemption(sig)
    if not redemption:
        return {
            "success": True,
            "status": "pending_or_unredeemed",
            "tx_signature": sig,
            "message": "Transaction has not been redeemed yet.",
        }

    return {
        "success": True,
        "status": "redeemed",
        "tx_signature": redemption["tx_signature"],
        "asset": redemption["asset"],
        "tier": redemption["tier"],
        "credits_granted": redemption["credits_granted"],
        "remaining_credits": redemption["remaining_credits"],
        "key_prefix": redemption["key_prefix"],
        "is_active": redemption["is_active"],
        "redeemed_at": redemption["redeemed_at"],
    }


@router.post("/v1/keys/generate-demo")
def generate_demo_key(request: Request):
    client_ip = get_client_ip(request)

    if not is_demo_keys_enabled():
        storage.log_audit_event(
            "demo_key_denied",
            "Attempted demo key generation while feature is disabled in production",
            ip_address=client_ip,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Demo key issuance is disabled. Provide payment or contact administrator.",
        )

    allowed, retry_after = rate_limiter.is_allowed(f"demo_key:{client_ip}", limit=5, window_seconds=60)
    if not allowed:
        record_rate_limit("/v1/keys/generate-demo")
        storage.log_audit_event(
            "rate_limit_exceeded",
            f"Demo key generation rate limit exceeded for IP: {client_ip}",
            ip_address=client_ip,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many demo key requests. Please retry in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )

    raw_token, record = storage.create_api_key(tier="trial", credits=5, prefix_tag="molt_demo")
    storage.log_audit_event(
        "demo_key_issued",
        f"Issued demo key {record['key_prefix']} with 5 trial credits",
        ip_address=client_ip,
    )

    return {
        "success": True,
        "api_key": raw_token,
        "key_prefix": record["key_prefix"],
        "credits": 5,
        "message": "Demo token created with 5 free credits.",
    }
