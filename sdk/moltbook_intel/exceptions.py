"""
Moltbook Alpha Client SDK — Structured Exceptions.
Maps machine-readable error responses into typed Python exceptions with retry semantics.
"""

from typing import Optional, Dict, Any


class MoltbookApiError(Exception):
    """Base exception for all Moltbook Alpha API errors."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        details: Optional[Dict[str, Any]] = None,
        retryable: bool = False,
        retry_after: Optional[int] = None,
        request_id: Optional[str] = None,
        docs_url: Optional[str] = None,
    ):
        super().__init__(f"[{code}] {message} (status: {status_code}, req_id: {request_id})")
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        self.retryable = retryable
        self.retry_after = retry_after
        self.request_id = request_id
        self.docs_url = docs_url


class AuthenticationRequiredError(MoltbookApiError):
    pass


class InvalidApiKeyError(MoltbookApiError):
    pass


class ApiKeyRevokedError(MoltbookApiError):
    pass


class PaymentRequiredError(MoltbookApiError):
    pass


class CreditsExhaustedError(MoltbookApiError):
    pass


class EntitlementExpiredError(MoltbookApiError):
    pass


class RateLimitExceededError(MoltbookApiError):
    pass


class RpcGatewayError(MoltbookApiError):
    pass


class DatabaseUnavailableError(MoltbookApiError):
    pass


class ValidationError(MoltbookApiError):
    pass


class UnboundPaymentError(MoltbookApiError):
    pass


class InvoiceExpiredError(MoltbookApiError):
    pass


ERROR_CODE_MAP = {
    "AUTHENTICATION_REQUIRED": AuthenticationRequiredError,
    "INVALID_API_KEY": InvalidApiKeyError,
    "API_KEY_REVOKED": ApiKeyRevokedError,
    "PAYMENT_REQUIRED": PaymentRequiredError,
    "CREDITS_EXHAUSTED": CreditsExhaustedError,
    "ENTITLEMENT_EXPIRED": EntitlementExpiredError,
    "RATE_LIMIT_EXCEEDED": RateLimitExceededError,
    "RPC_GATEWAY_ERROR": RpcGatewayError,
    "DATABASE_UNAVAILABLE": DatabaseUnavailableError,
    "VALIDATION_ERROR": ValidationError,
    "UNBOUND_PAYMENT_REJECTED": UnboundPaymentError,
    "INVOICE_EXPIRED": InvoiceExpiredError,
}


def raise_for_error_payload(status_code: int, payload: Dict[str, Any], request_id: Optional[str] = None):
    """Instantiates and raises the appropriate MoltbookApiError subclass from payload."""
    code = payload.get("code") or f"HTTP_{status_code}"
    message = payload.get("message") or str(payload.get("detail", "API Error"))
    details = payload.get("details")
    retryable = payload.get("retryable", False)
    retry_after = payload.get("retry_after")
    req_id = payload.get("request_id") or request_id
    docs_url = payload.get("docs_url")

    exc_class = ERROR_CODE_MAP.get(code, MoltbookApiError)
    raise exc_class(
        code=code,
        message=message,
        status_code=status_code,
        details=details,
        retryable=retryable,
        retry_after=retry_after,
        request_id=req_id,
        docs_url=docs_url,
    )
