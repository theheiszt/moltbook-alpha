"""
Moltbook Alpha Agent-Native Error Taxonomy, Exception Hierarchy, and Registry.
Provides machine-readable error codes, deterministic retry guidance, structured diagnostics,
operation outcomes, state effects, recovery actions, and zero-breakage backwards compatibility
with legacy API consumers.
"""

from enum import Enum
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field

DOCS_BASE_URL = "https://theheiszt.github.io/moltbook-alpha/docs/errors"


class OperationOutcome(str, Enum):
    """
    Substantiated state transition outcome of the attempted API operation.
    """
    COMMITTED = "committed"
    NOT_COMMITTED = "not_committed"
    INDETERMINATE = "indeterminate"


class RecoveryAction(str, Enum):
    """
    Closed enumeration of safe next actions an autonomous agent client can take.
    """
    REQUEST_NEW_CHALLENGE = "request_new_challenge"
    RETRIEVE_EXISTING_RESULT = "retrieve_existing_result"
    POLL_PAYMENT_STATUS = "poll_payment_status"
    CREATE_NEW_INVOICE = "create_new_invoice"
    TOPUP_CREDITS = "topup_credits"
    RENEW_ENTITLEMENT = "renew_entitlement"
    REAUTHENTICATE = "reauthenticate"
    BACKOFF_AND_RETRY = "backoff_and_retry"
    INSPECT_PARAMETERS = "inspect_parameters"
    CONTACT_SUPPORT = "contact_support"
    CONFIRM_OPERATION = "confirm_operation"


class ErrorCode(str, Enum):
    # Authentication & Authorization
    AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
    INVALID_API_KEY = "INVALID_API_KEY"
    API_KEY_REVOKED = "API_KEY_REVOKED"
    UNAUTHORIZED_METRICS = "UNAUTHORIZED_METRICS"
    UNAUTHORIZED_WEBHOOK = "UNAUTHORIZED_WEBHOOK"

    # Payment, Credits & Entitlements
    PAYMENT_REQUIRED = "PAYMENT_REQUIRED"
    CREDITS_EXHAUSTED = "CREDITS_EXHAUSTED"
    ENTITLEMENT_EXPIRED = "ENTITLEMENT_EXPIRED"
    ENTITLEMENT_EXHAUSTED = "ENTITLEMENT_EXHAUSTED"
    UNBOUND_PAYMENT_REJECTED = "UNBOUND_PAYMENT_REJECTED"
    INVOICE_EXPIRED = "INVOICE_EXPIRED"
    INVOICE_ALREADY_FULFILLED = "INVOICE_ALREADY_FULFILLED"
    INVALID_CLAIM_SECRET = "INVALID_CLAIM_SECRET"
    PAYMENT_VERIFICATION_FAILED = "PAYMENT_VERIFICATION_FAILED"
    DUPLICATE_PAYMENT_REUSE = "DUPLICATE_PAYMENT_REUSE"

    # Verification Challenges (Stage 3)
    WRONG_ANSWER = "WRONG_ANSWER"
    CHALLENGE_EXPIRED = "CHALLENGE_EXPIRED"
    CHALLENGE_CONSUMED = "CHALLENGE_CONSUMED"
    CHALLENGE_ALREADY_ANSWERED = "CHALLENGE_ALREADY_ANSWERED"
    CHALLENGE_NOT_FOUND = "CHALLENGE_NOT_FOUND"

    # Rate Limiting & Validation
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    RATE_LIMITED = "RATE_LIMITED"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"

    # Infrastructure & Gateway
    RPC_GATEWAY_ERROR = "RPC_GATEWAY_ERROR"
    DATABASE_UNAVAILABLE = "DATABASE_UNAVAILABLE"
    FEATURE_DISABLED = "FEATURE_DISABLED"
    INTERNAL_SERVER_ERROR = "INTERNAL_SERVER_ERROR"
    # Step-Up Policy & Confirmation Nonces
    POLICY_CONFIRMATION_REQUIRED = "POLICY_CONFIRMATION_REQUIRED"
    CONFIRMATION_NONCE_INVALID = "CONFIRMATION_NONCE_INVALID"


class ErrorDefinition(BaseModel):
    code: ErrorCode
    status_code: int
    retryable: bool
    outcome: OperationOutcome = OperationOutcome.NOT_COMMITTED
    state_effect: str = "none"
    recovery_action: RecoveryAction = RecoveryAction.INSPECT_PARAMETERS
    default_message: str
    description: str
    docs_url: str
    default_retry_after: Optional[int] = None


ERROR_REGISTRY: Dict[str, ErrorDefinition] = {
    ErrorCode.AUTHENTICATION_REQUIRED.value: ErrorDefinition(
        code=ErrorCode.AUTHENTICATION_REQUIRED,
        status_code=401,
        retryable=False,
        outcome=OperationOutcome.NOT_COMMITTED,
        state_effect="none",
        recovery_action=RecoveryAction.REAUTHENTICATE,
        default_message="Authentication credentials are required to access this resource.",
        description="Returned when a request lacks valid API key or Bearer token credentials.",
        docs_url=f"{DOCS_BASE_URL}#AUTHENTICATION_REQUIRED",
    ),
    ErrorCode.INVALID_API_KEY.value: ErrorDefinition(
        code=ErrorCode.INVALID_API_KEY,
        status_code=403,
        retryable=False,
        outcome=OperationOutcome.NOT_COMMITTED,
        state_effect="none",
        recovery_action=RecoveryAction.REAUTHENTICATE,
        default_message="Provided API key was not found or has an invalid format.",
        description="Returned when the API key signature or prefix is unrecognized.",
        docs_url=f"{DOCS_BASE_URL}#INVALID_API_KEY",
    ),
    ErrorCode.API_KEY_REVOKED.value: ErrorDefinition(
        code=ErrorCode.API_KEY_REVOKED,
        status_code=403,
        retryable=False,
        outcome=OperationOutcome.NOT_COMMITTED,
        state_effect="none",
        recovery_action=RecoveryAction.REAUTHENTICATE,
        default_message="API key has been permanently deactivated by an administrator.",
        description="Returned when attempting to authenticate with a revoked API key.",
        docs_url=f"{DOCS_BASE_URL}#API_KEY_REVOKED",
    ),
    ErrorCode.PAYMENT_REQUIRED.value: ErrorDefinition(
        code=ErrorCode.PAYMENT_REQUIRED,
        status_code=402,
        retryable=False,
        outcome=OperationOutcome.NOT_COMMITTED,
        state_effect="none",
        recovery_action=RecoveryAction.CREATE_NEW_INVOICE,
        default_message="Access requires an active API key or payment.",
        description="Returned when an unauthenticated client requests monetized endpoints.",
        docs_url=f"{DOCS_BASE_URL}#PAYMENT_REQUIRED",
    ),
    ErrorCode.CREDITS_EXHAUSTED.value: ErrorDefinition(
        code=ErrorCode.CREDITS_EXHAUSTED,
        status_code=402,
        retryable=False,
        outcome=OperationOutcome.NOT_COMMITTED,
        state_effect="none",
        recovery_action=RecoveryAction.TOPUP_CREDITS,
        default_message="Key credits exhausted. Top up your balance via Solana USDC.",
        description="Returned when an API key has depleted all available query credits.",
        docs_url=f"{DOCS_BASE_URL}#CREDITS_EXHAUSTED",
    ),
    ErrorCode.ENTITLEMENT_EXPIRED.value: ErrorDefinition(
        code=ErrorCode.ENTITLEMENT_EXPIRED,
        status_code=402,
        retryable=False,
        outcome=OperationOutcome.NOT_COMMITTED,
        state_effect="none",
        recovery_action=RecoveryAction.RENEW_ENTITLEMENT,
        default_message="Premium entitlement has expired. Renew your subscription to continue spending credits.",
        description="Returned when a 30-day Premium access window has elapsed.",
        docs_url=f"{DOCS_BASE_URL}#ENTITLEMENT_EXPIRED",
    ),
    ErrorCode.ENTITLEMENT_EXHAUSTED.value: ErrorDefinition(
        code=ErrorCode.ENTITLEMENT_EXHAUSTED,
        status_code=402,
        retryable=False,
        outcome=OperationOutcome.NOT_COMMITTED,
        state_effect="none",
        recovery_action=RecoveryAction.TOPUP_CREDITS,
        default_message="Paid entitlement or credit quota has been exhausted.",
        description="Returned when an API key has depleted all available query credits or 30-day allowance.",
        docs_url=f"{DOCS_BASE_URL}#ENTITLEMENT_EXHAUSTED",
    ),
    ErrorCode.RATE_LIMIT_EXCEEDED.value: ErrorDefinition(
        code=ErrorCode.RATE_LIMIT_EXCEEDED,
        status_code=429,
        retryable=True,
        outcome=OperationOutcome.NOT_COMMITTED,
        state_effect="rate_limit_incremented",
        recovery_action=RecoveryAction.BACKOFF_AND_RETRY,
        default_message="Request rate limit exceeded. Please back off and retry.",
        description="Returned when client requests exceed sliding-window volume thresholds.",
        docs_url=f"{DOCS_BASE_URL}#RATE_LIMIT_EXCEEDED",
        default_retry_after=60,
    ),
    ErrorCode.RATE_LIMITED.value: ErrorDefinition(
        code=ErrorCode.RATE_LIMITED,
        status_code=429,
        retryable=True,
        outcome=OperationOutcome.NOT_COMMITTED,
        state_effect="rate_limit_incremented",
        recovery_action=RecoveryAction.BACKOFF_AND_RETRY,
        default_message="Request rate exceeded.",
        description="Returned when client requests exceed token-bucket rate limits or concurrency limits.",
        docs_url=f"{DOCS_BASE_URL}#RATE_LIMITED",
        default_retry_after=5,
    ),
    ErrorCode.VALIDATION_ERROR.value: ErrorDefinition(
        code=ErrorCode.VALIDATION_ERROR,
        status_code=422,
        retryable=False,
        outcome=OperationOutcome.NOT_COMMITTED,
        state_effect="none",
        recovery_action=RecoveryAction.INSPECT_PARAMETERS,
        default_message="Request validation failed. Check parameters and payload schema.",
        description="Returned when request payloads, types, or field formats fail validation.",
        docs_url=f"{DOCS_BASE_URL}#VALIDATION_ERROR",
    ),
    ErrorCode.RESOURCE_NOT_FOUND.value: ErrorDefinition(
        code=ErrorCode.RESOURCE_NOT_FOUND,
        status_code=404,
        retryable=False,
        outcome=OperationOutcome.NOT_COMMITTED,
        state_effect="none",
        recovery_action=RecoveryAction.INSPECT_PARAMETERS,
        default_message="Requested resource was not found.",
        description="Returned when a specific invoice, briefing, or entity does not exist.",
        docs_url=f"{DOCS_BASE_URL}#RESOURCE_NOT_FOUND",
    ),
    ErrorCode.UNBOUND_PAYMENT_REJECTED.value: ErrorDefinition(
        code=ErrorCode.UNBOUND_PAYMENT_REJECTED,
        status_code=400,
        retryable=False,
        outcome=OperationOutcome.NOT_COMMITTED,
        state_effect="none",
        recovery_action=RecoveryAction.CREATE_NEW_INVOICE,
        default_message="Payment verification requires an active invoice or reference.",
        description="Returned when payments are submitted without invoice binding to prevent front-running.",
        docs_url=f"{DOCS_BASE_URL}#UNBOUND_PAYMENT_REJECTED",
    ),
    ErrorCode.INVOICE_EXPIRED.value: ErrorDefinition(
        code=ErrorCode.INVOICE_EXPIRED,
        status_code=400,
        retryable=False,
        outcome=OperationOutcome.NOT_COMMITTED,
        state_effect="none",
        recovery_action=RecoveryAction.CREATE_NEW_INVOICE,
        default_message="Target payment invoice has expired. Please generate a fresh invoice.",
        description="Returned when a settlement is submitted against an invoice past its TTL.",
        docs_url=f"{DOCS_BASE_URL}#INVOICE_EXPIRED",
    ),
    ErrorCode.INVOICE_ALREADY_FULFILLED.value: ErrorDefinition(
        code=ErrorCode.INVOICE_ALREADY_FULFILLED,
        status_code=400,
        retryable=False,
        outcome=OperationOutcome.COMMITTED,
        state_effect="none",
        recovery_action=RecoveryAction.RETRIEVE_EXISTING_RESULT,
        default_message="Invoice was already fulfilled.",
        description="Returned when attempting to fulfill an invoice that is already completed.",
        docs_url=f"{DOCS_BASE_URL}#INVOICE_ALREADY_FULFILLED",
    ),
    ErrorCode.INVALID_CLAIM_SECRET.value: ErrorDefinition(
        code=ErrorCode.INVALID_CLAIM_SECRET,
        status_code=400,
        retryable=False,
        outcome=OperationOutcome.NOT_COMMITTED,
        state_effect="none",
        recovery_action=RecoveryAction.INSPECT_PARAMETERS,
        default_message="Invalid claim secret presented for credential recovery.",
        description="Returned when a credential claim fails cryptographic secret verification.",
        docs_url=f"{DOCS_BASE_URL}#INVALID_CLAIM_SECRET",
    ),
    ErrorCode.PAYMENT_VERIFICATION_FAILED.value: ErrorDefinition(
        code=ErrorCode.PAYMENT_VERIFICATION_FAILED,
        status_code=400,
        retryable=False,
        outcome=OperationOutcome.NOT_COMMITTED,
        state_effect="none",
        recovery_action=RecoveryAction.CREATE_NEW_INVOICE,
        default_message="On-chain payment verification failed against configured requirements.",
        description="Returned when an on-chain transfer fails amount, asset, recipient, or slot checks.",
        docs_url=f"{DOCS_BASE_URL}#PAYMENT_VERIFICATION_FAILED",
    ),
    ErrorCode.DUPLICATE_PAYMENT_REUSE.value: ErrorDefinition(
        code=ErrorCode.DUPLICATE_PAYMENT_REUSE,
        status_code=409,
        retryable=False,
        outcome=OperationOutcome.NOT_COMMITTED,
        state_effect="none",
        recovery_action=RecoveryAction.CREATE_NEW_INVOICE,
        default_message="Transaction signature has already been redeemed for a different invoice or account.",
        description="Returned when attempting cross-invoice or cross-account reuse of a payment signature.",
        docs_url=f"{DOCS_BASE_URL}#DUPLICATE_PAYMENT_REUSE",
    ),
    ErrorCode.WRONG_ANSWER.value: ErrorDefinition(
        code=ErrorCode.WRONG_ANSWER,
        status_code=400,
        retryable=False,
        outcome=OperationOutcome.NOT_COMMITTED,
        state_effect="challenge_consumed",
        recovery_action=RecoveryAction.REQUEST_NEW_CHALLENGE,
        default_message="Submitted challenge answer is incorrect. The challenge has been consumed and cannot be reused.",
        description="Returned when verification challenge answer does not match the expected solution.",
        docs_url=f"{DOCS_BASE_URL}#WRONG_ANSWER",
    ),
    ErrorCode.CHALLENGE_EXPIRED.value: ErrorDefinition(
        code=ErrorCode.CHALLENGE_EXPIRED,
        status_code=410,
        retryable=False,
        outcome=OperationOutcome.NOT_COMMITTED,
        state_effect="none",
        recovery_action=RecoveryAction.REQUEST_NEW_CHALLENGE,
        default_message="Verification challenge has expired past its validity window.",
        description="Returned when submitting an answer to a challenge that has exceeded its TTL.",
        docs_url=f"{DOCS_BASE_URL}#CHALLENGE_EXPIRED",
    ),
    ErrorCode.CHALLENGE_CONSUMED.value: ErrorDefinition(
        code=ErrorCode.CHALLENGE_CONSUMED,
        status_code=410,
        retryable=False,
        outcome=OperationOutcome.NOT_COMMITTED,
        state_effect="challenge_consumed",
        recovery_action=RecoveryAction.REQUEST_NEW_CHALLENGE,
        default_message="This challenge has already been consumed by a prior failed attempt and can no longer be used.",
        description="Returned when attempting to answer a challenge that was already consumed by an incorrect attempt.",
        docs_url=f"{DOCS_BASE_URL}#CHALLENGE_CONSUMED",
    ),
    ErrorCode.CHALLENGE_ALREADY_ANSWERED.value: ErrorDefinition(
        code=ErrorCode.CHALLENGE_ALREADY_ANSWERED,
        status_code=409,
        retryable=False,
        outcome=OperationOutcome.COMMITTED,
        state_effect="none",
        recovery_action=RecoveryAction.RETRIEVE_EXISTING_RESULT,
        default_message="This challenge was already successfully solved. The existing verification result can be retrieved.",
        description="Returned when resubmitting a solution to an already solved challenge.",
        docs_url=f"{DOCS_BASE_URL}#CHALLENGE_ALREADY_ANSWERED",
    ),
    ErrorCode.CHALLENGE_NOT_FOUND.value: ErrorDefinition(
        code=ErrorCode.CHALLENGE_NOT_FOUND,
        status_code=404,
        retryable=False,
        outcome=OperationOutcome.NOT_COMMITTED,
        state_effect="none",
        recovery_action=RecoveryAction.REQUEST_NEW_CHALLENGE,
        default_message="Requested verification challenge was not found.",
        description="Returned when the challenge ID does not correspond to an existing record.",
        docs_url=f"{DOCS_BASE_URL}#CHALLENGE_NOT_FOUND",
    ),
    ErrorCode.RPC_GATEWAY_ERROR.value: ErrorDefinition(
        code=ErrorCode.RPC_GATEWAY_ERROR,
        status_code=502,
        retryable=True,
        outcome=OperationOutcome.INDETERMINATE,
        state_effect="none",
        recovery_action=RecoveryAction.POLL_PAYMENT_STATUS,
        default_message="Upstream Solana RPC communication error.",
        description="Returned when external Solana RPC nodes time out, rate limit, or fail.",
        docs_url=f"{DOCS_BASE_URL}#RPC_GATEWAY_ERROR",
        default_retry_after=5,
    ),
    ErrorCode.DATABASE_UNAVAILABLE.value: ErrorDefinition(
        code=ErrorCode.DATABASE_UNAVAILABLE,
        status_code=503,
        retryable=True,
        outcome=OperationOutcome.INDETERMINATE,
        state_effect="none",
        recovery_action=RecoveryAction.BACKOFF_AND_RETRY,
        default_message="Database service is temporarily unavailable or degraded.",
        description="Returned when SQLite connection or health check fails.",
        docs_url=f"{DOCS_BASE_URL}#DATABASE_UNAVAILABLE",
        default_retry_after=10,
    ),
    ErrorCode.FEATURE_DISABLED.value: ErrorDefinition(
        code=ErrorCode.FEATURE_DISABLED,
        status_code=403,
        retryable=False,
        outcome=OperationOutcome.NOT_COMMITTED,
        state_effect="none",
        recovery_action=RecoveryAction.INSPECT_PARAMETERS,
        default_message="Requested feature is disabled in this environment.",
        description="Returned when attempting to access a disabled administrative or demo route.",
        docs_url=f"{DOCS_BASE_URL}#FEATURE_DISABLED",
    ),
    ErrorCode.UNAUTHORIZED_METRICS.value: ErrorDefinition(
        code=ErrorCode.UNAUTHORIZED_METRICS,
        status_code=401,
        retryable=False,
        outcome=OperationOutcome.NOT_COMMITTED,
        state_effect="none",
        recovery_action=RecoveryAction.REAUTHENTICATE,
        default_message="Unauthorized access to metrics exposition endpoint.",
        description="Returned when `/metrics` access lacks a valid bearer token.",
        docs_url=f"{DOCS_BASE_URL}#UNAUTHORIZED_METRICS",
    ),
    ErrorCode.UNAUTHORIZED_WEBHOOK.value: ErrorDefinition(
        code=ErrorCode.UNAUTHORIZED_WEBHOOK,
        status_code=401,
        retryable=False,
        outcome=OperationOutcome.NOT_COMMITTED,
        state_effect="none",
        recovery_action=RecoveryAction.REAUTHENTICATE,
        default_message="Invalid or missing X-Webhook-Secret header.",
        description="Returned when a webhook request fails secret header authentication.",
        docs_url=f"{DOCS_BASE_URL}#UNAUTHORIZED_WEBHOOK",
    ),
    ErrorCode.POLICY_CONFIRMATION_REQUIRED.value: ErrorDefinition(
        code=ErrorCode.POLICY_CONFIRMATION_REQUIRED,
        status_code=428,
        retryable=False,
        outcome=OperationOutcome.NOT_COMMITTED,
        state_effect="none",
        recovery_action=RecoveryAction.CONFIRM_OPERATION,
        default_message="Step-up confirmation required: This action will permanently dispatch an on-chain refund transaction from the treasury.",
        description="Returned when high-consequence operations require explicit confirmation with a single-use nonce.",
        docs_url=f"{DOCS_BASE_URL}#POLICY_CONFIRMATION_REQUIRED",
    ),
    ErrorCode.CONFIRMATION_NONCE_INVALID.value: ErrorDefinition(
        code=ErrorCode.CONFIRMATION_NONCE_INVALID,
        status_code=410,
        retryable=False,
        outcome=OperationOutcome.NOT_COMMITTED,
        state_effect="none",
        recovery_action=RecoveryAction.INSPECT_PARAMETERS,
        default_message="Confirmation nonce is missing, expired, invalid, or was already consumed.",
        description="Returned when an invalid, expired, or previously burned confirmation nonce is presented.",
        docs_url=f"{DOCS_BASE_URL}#CONFIRMATION_NONCE_INVALID",
    ),
    ErrorCode.INTERNAL_SERVER_ERROR.value: ErrorDefinition(
        code=ErrorCode.INTERNAL_SERVER_ERROR,
        status_code=500,
        retryable=False,
        outcome=OperationOutcome.INDETERMINATE,
        state_effect="none",
        recovery_action=RecoveryAction.CONTACT_SUPPORT,
        default_message="Internal server error. Incident has been recorded.",
        description="Returned when an unhandled server exception occurs. Details are redacted.",
        docs_url=f"{DOCS_BASE_URL}#INTERNAL_SERVER_ERROR",
    ),
}


class ApiError(Exception):
    """
    Structured application error carrying taxonomy metadata, outcome, state effects,
    recovery guidance, retry semantics, and backwards-compatibility payloads.
    """

    def __init__(
        self,
        code: ErrorCode | str,
        message: Optional[str] = None,
        status_code: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
        retryable: Optional[bool] = None,
        retry_after: Optional[int] = None,
        headers: Optional[Dict[str, str]] = None,
        legacy_detail: Optional[Any] = None,
        outcome: Optional[OperationOutcome | str] = None,
        state_effect: Optional[str] = None,
        recovery_action: Optional[RecoveryAction | str] = None,
        recovery: Optional[Dict[str, Any]] = None,
    ):
        raw_code = code.value if isinstance(code, ErrorCode) else str(code)
        defn = ERROR_REGISTRY.get(raw_code)

        self.code = raw_code
        self.status_code = status_code or (defn.status_code if defn else 400)
        self.message = message or (defn.default_message if defn else "An error occurred.")
        self.details = details
        self.retryable = retryable if retryable is not None else (defn.retryable if defn else False)
        self.retry_after = retry_after if retry_after is not None else (defn.default_retry_after if defn else None)
        self.headers = headers or {}
        self.docs_url = defn.docs_url if defn else f"{DOCS_BASE_URL}#{self.code}"
        self.legacy_detail = legacy_detail

        # Machine-readable error contract fields
        self.outcome = outcome if outcome is not None else (defn.outcome if defn else OperationOutcome.NOT_COMMITTED)
        self.state_effect = state_effect if state_effect is not None else (defn.state_effect if defn else "none")
        self.recovery_action = recovery_action if recovery_action is not None else (defn.recovery_action if defn else RecoveryAction.INSPECT_PARAMETERS)
        self.recovery = recovery

        super().__init__(self.message)


class ErrorRecoveryModel(BaseModel):
    action: str = Field(description="Deterministic machine-readable recovery action for autonomous clients")
    parameter: Optional[str] = Field(default=None, description="Optional parameter or context for recovery")


class ErrorSubModel(BaseModel):
    code: str
    message: str
    retryable: bool
    outcome: str = "not_committed"
    state_effect: str = "none"
    recovery: ErrorRecoveryModel
    request_id: Optional[str] = None
    retry_after_seconds: Optional[int] = None
    details: Optional[Dict[str, Any]] = None


class ErrorResponseModel(BaseModel):
    error: ErrorSubModel
    code: str
    message: str
    details: Optional[Dict[str, Any]] = None
    retryable: bool
    outcome: str = "not_committed"
    state_effect: str = "none"
    recovery: ErrorRecoveryModel
    retry_after: Optional[int] = None
    retry_after_seconds: Optional[int] = None
    request_id: str
    docs_url: str
    detail: Any = Field(description="Legacy compatibility bridge field")


def format_error_payload(
    code: str,
    message: str,
    request_id: str,
    status_code: int = 400,
    details: Optional[Dict[str, Any]] = None,
    retryable: Optional[bool] = None,
    retry_after: Optional[int] = None,
    docs_url: Optional[str] = None,
    legacy_detail: Optional[Any] = None,
    outcome: Optional[OperationOutcome | str] = None,
    state_effect: Optional[str] = None,
    recovery_action: Optional[RecoveryAction | str] = None,
    recovery: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Constructs the standard machine-readable JSON error payload matching the error contract:
    - nested `error` subobject with stable `code`, `message`, `retryable`, `outcome`,
      `state_effect`, `recovery.action`, and `request_id`.
    - root-level convenience fields for seamless backwards-compatibility.
    - legacy `detail` bridge field.
    """
    defn = ERROR_REGISTRY.get(code)
    is_retryable = retryable if retryable is not None else (defn.retryable if defn else False)
    eff_retry_after = retry_after if retry_after is not None else (defn.default_retry_after if defn else None)
    eff_docs_url = docs_url or (defn.docs_url if defn else f"{DOCS_BASE_URL}#{code}")

    # Determine outcome
    if outcome is not None:
        eff_outcome = outcome.value if isinstance(outcome, OperationOutcome) else str(outcome)
    elif defn:
        eff_outcome = defn.outcome.value if isinstance(defn.outcome, OperationOutcome) else str(defn.outcome)
    else:
        eff_outcome = OperationOutcome.NOT_COMMITTED.value

    # Determine state effect
    eff_state_effect = state_effect if state_effect is not None else (defn.state_effect if defn else "none")

    # Determine recovery action
    if recovery:
        recovery_dict = recovery
    else:
        if recovery_action is not None:
            act = recovery_action.value if isinstance(recovery_action, RecoveryAction) else str(recovery_action)
        elif defn:
            act = defn.recovery_action.value if isinstance(defn.recovery_action, RecoveryAction) else str(defn.recovery_action)
        else:
            act = RecoveryAction.INSPECT_PARAMETERS.value
        recovery_dict = {"action": act}

    # Determine legacy detail content
    if legacy_detail is not None:
        eff_detail = legacy_detail
    elif details and isinstance(details, dict) and "error" in details:
        eff_detail = details
    else:
        eff_detail = message

    # Map legacy codes to normalized codes in the standardized error subobject
    standard_code = code
    if code == ErrorCode.RATE_LIMIT_EXCEEDED.value:
        standard_code = ErrorCode.RATE_LIMITED.value
    elif code == ErrorCode.CREDITS_EXHAUSTED.value:
        standard_code = ErrorCode.ENTITLEMENT_EXHAUSTED.value

    # Build standardized machine-readable error subobject
    error_obj: Dict[str, Any] = {
        "code": standard_code,
        "message": message,
        "retryable": is_retryable,
        "outcome": eff_outcome,
        "state_effect": eff_state_effect,
        "recovery": recovery_dict,
        "request_id": request_id,
    }
    if eff_retry_after is not None:
        error_obj["retry_after_seconds"] = eff_retry_after
    if details:
        error_obj["details"] = details

    payload = {
        "error": error_obj,
        "code": code,
        "message": message,
        "details": details,
        "retryable": is_retryable,
        "outcome": eff_outcome,
        "state_effect": eff_state_effect,
        "recovery": recovery_dict,
        "retry_after": eff_retry_after,
        "retry_after_seconds": eff_retry_after,
        "request_id": request_id,
        "docs_url": eff_docs_url,
        "detail": eff_detail,
    }
    return payload
