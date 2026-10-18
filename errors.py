"""
Moltbook Alpha Agent-Native Error Taxonomy, Exception Hierarchy, and Registry.
Provides machine-readable error codes, deterministic retry guidance, structured diagnostics,
and zero-breakage backwards compatibility with legacy API consumers.
"""

from enum import Enum
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field

DOCS_BASE_URL = "https://theheiszt.github.io/moltbook-alpha/docs/errors"


class ErrorCode(str, Enum):
    AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
    INVALID_API_KEY = "INVALID_API_KEY"
    API_KEY_REVOKED = "API_KEY_REVOKED"
    PAYMENT_REQUIRED = "PAYMENT_REQUIRED"
    CREDITS_EXHAUSTED = "CREDITS_EXHAUSTED"
    ENTITLEMENT_EXPIRED = "ENTITLEMENT_EXPIRED"
    ENTITLEMENT_EXHAUSTED = "ENTITLEMENT_EXHAUSTED"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    RATE_LIMITED = "RATE_LIMITED"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    UNBOUND_PAYMENT_REJECTED = "UNBOUND_PAYMENT_REJECTED"
    INVOICE_EXPIRED = "INVOICE_EXPIRED"
    INVOICE_ALREADY_FULFILLED = "INVOICE_ALREADY_FULFILLED"
    INVALID_CLAIM_SECRET = "INVALID_CLAIM_SECRET"
    PAYMENT_VERIFICATION_FAILED = "PAYMENT_VERIFICATION_FAILED"
    RPC_GATEWAY_ERROR = "RPC_GATEWAY_ERROR"
    DATABASE_UNAVAILABLE = "DATABASE_UNAVAILABLE"
    FEATURE_DISABLED = "FEATURE_DISABLED"
    UNAUTHORIZED_METRICS = "UNAUTHORIZED_METRICS"
    UNAUTHORIZED_WEBHOOK = "UNAUTHORIZED_WEBHOOK"
    INTERNAL_SERVER_ERROR = "INTERNAL_SERVER_ERROR"


class ErrorDefinition(BaseModel):
    code: ErrorCode
    status_code: int
    retryable: bool
    default_message: str
    description: str
    docs_url: str
    default_retry_after: Optional[int] = None


ERROR_REGISTRY: Dict[str, ErrorDefinition] = {
    ErrorCode.AUTHENTICATION_REQUIRED.value: ErrorDefinition(
        code=ErrorCode.AUTHENTICATION_REQUIRED,
        status_code=401,
        retryable=False,
        default_message="Authentication credentials are required to access this resource.",
        description="Returned when a request lacks valid API key or Bearer token credentials.",
        docs_url=f"{DOCS_BASE_URL}#AUTHENTICATION_REQUIRED",
    ),
    ErrorCode.INVALID_API_KEY.value: ErrorDefinition(
        code=ErrorCode.INVALID_API_KEY,
        status_code=403,
        retryable=False,
        default_message="Provided API key was not found or has an invalid format.",
        description="Returned when the API key signature or prefix is unrecognized.",
        docs_url=f"{DOCS_BASE_URL}#INVALID_API_KEY",
    ),
    ErrorCode.API_KEY_REVOKED.value: ErrorDefinition(
        code=ErrorCode.API_KEY_REVOKED,
        status_code=403,
        retryable=False,
        default_message="API key has been permanently deactivated by an administrator.",
        description="Returned when attempting to authenticate with a revoked API key.",
        docs_url=f"{DOCS_BASE_URL}#API_KEY_REVOKED",
    ),
    ErrorCode.PAYMENT_REQUIRED.value: ErrorDefinition(
        code=ErrorCode.PAYMENT_REQUIRED,
        status_code=402,
        retryable=False,
        default_message="Access requires an active API key or payment.",
        description="Returned when an unauthenticated client requests monetized endpoints.",
        docs_url=f"{DOCS_BASE_URL}#PAYMENT_REQUIRED",
    ),
    ErrorCode.CREDITS_EXHAUSTED.value: ErrorDefinition(
        code=ErrorCode.CREDITS_EXHAUSTED,
        status_code=402,
        retryable=False,
        default_message="Key credits exhausted. Top up your balance via Solana USDC.",
        description="Returned when an API key has depleted all available query credits.",
        docs_url=f"{DOCS_BASE_URL}#CREDITS_EXHAUSTED",
    ),
    ErrorCode.ENTITLEMENT_EXPIRED.value: ErrorDefinition(
        code=ErrorCode.ENTITLEMENT_EXPIRED,
        status_code=402,
        retryable=False,
        default_message="Premium entitlement has expired. Renew your subscription to continue spending credits.",
        description="Returned when a 30-day Premium access window has elapsed.",
        docs_url=f"{DOCS_BASE_URL}#ENTITLEMENT_EXPIRED",
    ),
    ErrorCode.ENTITLEMENT_EXHAUSTED.value: ErrorDefinition(
        code=ErrorCode.ENTITLEMENT_EXHAUSTED,
        status_code=402,
        retryable=False,
        default_message="Paid entitlement or credit quota has been exhausted.",
        description="Returned when an API key has depleted all available query credits or 30-day allowance.",
        docs_url=f"{DOCS_BASE_URL}#ENTITLEMENT_EXHAUSTED",
    ),
    ErrorCode.RATE_LIMIT_EXCEEDED.value: ErrorDefinition(
        code=ErrorCode.RATE_LIMIT_EXCEEDED,
        status_code=429,
        retryable=True,
        default_message="Request rate limit exceeded. Please back off and retry.",
        description="Returned when client requests exceed sliding-window volume thresholds.",
        docs_url=f"{DOCS_BASE_URL}#RATE_LIMIT_EXCEEDED",
        default_retry_after=60,
    ),
    ErrorCode.RATE_LIMITED.value: ErrorDefinition(
        code=ErrorCode.RATE_LIMITED,
        status_code=429,
        retryable=True,
        default_message="Request rate exceeded.",
        description="Returned when client requests exceed token-bucket rate limits or concurrency limits.",
        docs_url=f"{DOCS_BASE_URL}#RATE_LIMITED",
        default_retry_after=5,
    ),
    ErrorCode.VALIDATION_ERROR.value: ErrorDefinition(
        code=ErrorCode.VALIDATION_ERROR,
        status_code=422,
        retryable=False,
        default_message="Request validation failed. Check parameters and payload schema.",
        description="Returned when request payloads, types, or field formats fail validation.",
        docs_url=f"{DOCS_BASE_URL}#VALIDATION_ERROR",
    ),
    ErrorCode.RESOURCE_NOT_FOUND.value: ErrorDefinition(
        code=ErrorCode.RESOURCE_NOT_FOUND,
        status_code=404,
        retryable=False,
        default_message="Requested resource was not found.",
        description="Returned when a specific invoice, briefing, or entity does not exist.",
        docs_url=f"{DOCS_BASE_URL}#RESOURCE_NOT_FOUND",
    ),
    ErrorCode.UNBOUND_PAYMENT_REJECTED.value: ErrorDefinition(
        code=ErrorCode.UNBOUND_PAYMENT_REJECTED,
        status_code=400,
        retryable=False,
        default_message="Payment verification requires an active invoice or reference.",
        description="Returned when payments are submitted without invoice binding to prevent front-running.",
        docs_url=f"{DOCS_BASE_URL}#UNBOUND_PAYMENT_REJECTED",
    ),
    ErrorCode.INVOICE_EXPIRED.value: ErrorDefinition(
        code=ErrorCode.INVOICE_EXPIRED,
        status_code=400,
        retryable=False,
        default_message="Target payment invoice has expired. Please generate a fresh invoice.",
        description="Returned when a settlement is submitted against an invoice past its TTL.",
        docs_url=f"{DOCS_BASE_URL}#INVOICE_EXPIRED",
    ),
    ErrorCode.INVOICE_ALREADY_FULFILLED.value: ErrorDefinition(
        code=ErrorCode.INVOICE_ALREADY_FULFILLED,
        status_code=400,
        retryable=False,
        default_message="Invoice was already fulfilled.",
        description="Returned when attempting to fulfill an invoice that is already completed.",
        docs_url=f"{DOCS_BASE_URL}#INVOICE_ALREADY_FULFILLED",
    ),
    ErrorCode.INVALID_CLAIM_SECRET.value: ErrorDefinition(
        code=ErrorCode.INVALID_CLAIM_SECRET,
        status_code=400,
        retryable=False,
        default_message="Invalid claim secret presented for credential recovery.",
        description="Returned when a credential claim fails cryptographic secret verification.",
        docs_url=f"{DOCS_BASE_URL}#INVALID_CLAIM_SECRET",
    ),
    ErrorCode.PAYMENT_VERIFICATION_FAILED.value: ErrorDefinition(
        code=ErrorCode.PAYMENT_VERIFICATION_FAILED,
        status_code=400,
        retryable=False,
        default_message="On-chain payment verification failed against configured requirements.",
        description="Returned when an on-chain transfer fails amount, asset, recipient, or slot checks.",
        docs_url=f"{DOCS_BASE_URL}#PAYMENT_VERIFICATION_FAILED",
    ),
    ErrorCode.RPC_GATEWAY_ERROR.value: ErrorDefinition(
        code=ErrorCode.RPC_GATEWAY_ERROR,
        status_code=502,
        retryable=True,
        default_message="Upstream Solana RPC communication error.",
        description="Returned when external Solana RPC nodes time out, rate limit, or fail.",
        docs_url=f"{DOCS_BASE_URL}#RPC_GATEWAY_ERROR",
        default_retry_after=5,
    ),
    ErrorCode.DATABASE_UNAVAILABLE.value: ErrorDefinition(
        code=ErrorCode.DATABASE_UNAVAILABLE,
        status_code=503,
        retryable=True,
        default_message="Database service is temporarily unavailable or degraded.",
        description="Returned when SQLite connection or health check fails.",
        docs_url=f"{DOCS_BASE_URL}#DATABASE_UNAVAILABLE",
        default_retry_after=10,
    ),
    ErrorCode.FEATURE_DISABLED.value: ErrorDefinition(
        code=ErrorCode.FEATURE_DISABLED,
        status_code=403,
        retryable=False,
        default_message="Requested feature is disabled in this environment.",
        description="Returned when attempting to access a disabled administrative or demo route.",
        docs_url=f"{DOCS_BASE_URL}#FEATURE_DISABLED",
    ),
    ErrorCode.UNAUTHORIZED_METRICS.value: ErrorDefinition(
        code=ErrorCode.UNAUTHORIZED_METRICS,
        status_code=401,
        retryable=False,
        default_message="Unauthorized access to metrics exposition endpoint.",
        description="Returned when `/metrics` access lacks a valid bearer token.",
        docs_url=f"{DOCS_BASE_URL}#UNAUTHORIZED_METRICS",
    ),
    ErrorCode.UNAUTHORIZED_WEBHOOK.value: ErrorDefinition(
        code=ErrorCode.UNAUTHORIZED_WEBHOOK,
        status_code=401,
        retryable=False,
        default_message="Invalid or missing X-Webhook-Secret header.",
        description="Returned when a webhook request fails secret header authentication.",
        docs_url=f"{DOCS_BASE_URL}#UNAUTHORIZED_WEBHOOK",
    ),
    ErrorCode.INTERNAL_SERVER_ERROR.value: ErrorDefinition(
        code=ErrorCode.INTERNAL_SERVER_ERROR,
        status_code=500,
        retryable=False,
        default_message="Internal server error. Incident has been recorded.",
        description="Returned when an unhandled server exception occurs. Details are redacted.",
        docs_url=f"{DOCS_BASE_URL}#INTERNAL_SERVER_ERROR",
    ),
}


class ApiError(Exception):
    """
    Structured application error carrying taxonomy metadata, retry semantics,
    and backwards-compatibility payloads.
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

        super().__init__(self.message)


class ErrorSubModel(BaseModel):
    code: str
    message: str
    retryable: bool
    retry_after_seconds: Optional[int] = None
    details: Optional[Dict[str, Any]] = None


class ErrorResponseModel(BaseModel):
    error: Optional[ErrorSubModel] = None
    code: str
    message: str
    details: Optional[Dict[str, Any]] = None
    retryable: bool
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
) -> Dict[str, Any]:
    """
    Constructs the standard machine-readable JSON error payload, ensuring complete
    backwards-compatibility via the `detail` bridge field while providing
    the standardized `error` subobject structure.
    """
    defn = ERROR_REGISTRY.get(code)
    is_retryable = retryable if retryable is not None else (defn.retryable if defn else False)
    eff_retry_after = retry_after if retry_after is not None else (defn.default_retry_after if defn else None)
    eff_docs_url = docs_url or (defn.docs_url if defn else f"{DOCS_BASE_URL}#{code}")

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
        "retry_after_seconds": eff_retry_after,
    }
    if details:
        error_obj["details"] = details

    payload = {
        "error": error_obj,
        "code": code,
        "message": message,
        "details": details,
        "retryable": is_retryable,
        "retry_after": eff_retry_after,
        "retry_after_seconds": eff_retry_after,
        "request_id": request_id,
        "docs_url": eff_docs_url,
        "detail": eff_detail,
    }
    return payload
