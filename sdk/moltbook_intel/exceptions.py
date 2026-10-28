"""
Moltbook Alpha Client SDK — Structured Exceptions.
Maps machine-readable error responses into typed Python exceptions with deterministic retry guidance,
operation outcome semantics, state effects, and recovery actions.
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
        outcome: str = "not_committed",
        state_effect: str = "none",
        recovery: Optional[Dict[str, Any]] = None,
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
        self.outcome = outcome
        self.state_effect = state_effect
        self.recovery = recovery or {"action": "inspect_parameters"}
        self.recovery_action = self.recovery.get("action", "inspect_parameters")


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


class EntitlementExhaustedError(CreditsExhaustedError):
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


class InvoiceAlreadyFulfilledError(MoltbookApiError):
    pass


class DuplicatePaymentReuseError(MoltbookApiError):
    pass


class PaymentVerificationFailedError(MoltbookApiError):
    pass


class WrongAnswerError(MoltbookApiError):
    pass


class ChallengeExpiredError(MoltbookApiError):
    pass


class ChallengeConsumedError(MoltbookApiError):
    pass


class ChallengeAlreadyAnsweredError(MoltbookApiError):
    pass


class ChallengeNotFoundError(MoltbookApiError):
    pass


ERROR_CODE_MAP = {
    "AUTHENTICATION_REQUIRED": AuthenticationRequiredError,
    "INVALID_API_KEY": InvalidApiKeyError,
    "API_KEY_REVOKED": ApiKeyRevokedError,
    "PAYMENT_REQUIRED": PaymentRequiredError,
    "CREDITS_EXHAUSTED": CreditsExhaustedError,
    "ENTITLEMENT_EXPIRED": EntitlementExpiredError,
    "ENTITLEMENT_EXHAUSTED": EntitlementExhaustedError,
    "RATE_LIMIT_EXCEEDED": RateLimitExceededError,
    "RATE_LIMITED": RateLimitExceededError,
    "RPC_GATEWAY_ERROR": RpcGatewayError,
    "DATABASE_UNAVAILABLE": DatabaseUnavailableError,
    "VALIDATION_ERROR": ValidationError,
    "UNBOUND_PAYMENT_REJECTED": UnboundPaymentError,
    "INVOICE_EXPIRED": InvoiceExpiredError,
    "INVOICE_ALREADY_FULFILLED": InvoiceAlreadyFulfilledError,
    "DUPLICATE_PAYMENT_REUSE": DuplicatePaymentReuseError,
    "PAYMENT_VERIFICATION_FAILED": PaymentVerificationFailedError,
    "WRONG_ANSWER": WrongAnswerError,
    "CHALLENGE_EXPIRED": ChallengeExpiredError,
    "CHALLENGE_CONSUMED": ChallengeConsumedError,
    "CHALLENGE_ALREADY_ANSWERED": ChallengeAlreadyAnsweredError,
    "CHALLENGE_NOT_FOUND": ChallengeNotFoundError,
}


def raise_for_error_payload(status_code: int, payload: Dict[str, Any], request_id: Optional[str] = None):
    """Instantiates and raises the appropriate MoltbookApiError subclass from payload."""
    nested_err = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    code = payload.get("code") or nested_err.get("code") or f"HTTP_{status_code}"
    message = payload.get("message") or nested_err.get("message") or str(payload.get("detail", "API Error"))
    details = payload.get("details") or nested_err.get("details")
    retryable = payload.get("retryable", nested_err.get("retryable", False))
    retry_after = payload.get("retry_after") or payload.get("retry_after_seconds") or nested_err.get("retry_after_seconds")
    req_id = payload.get("request_id") or request_id
    docs_url = payload.get("docs_url")
    outcome = payload.get("outcome") or nested_err.get("outcome") or "not_committed"
    state_effect = payload.get("state_effect") or nested_err.get("state_effect") or "none"
    recovery = payload.get("recovery") or nested_err.get("recovery") or {"action": "inspect_parameters"}

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
        outcome=outcome,
        state_effect=state_effect,
        recovery=recovery,
    )
