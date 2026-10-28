"""
Moltbook Alpha Client SDK.
Agent-native client for market intelligence, DAG tool compilation,
Solana Pay settlement, and cryptographic state witness verification.
"""

from .client import MoltbookIntelClient
from .dag_resolver import ToolDAGResolver
from .crypto import (
    canonical_json,
    b58decode,
    verify_witness_payload_offline,
    verify_witness_signature_local,
)
from .exceptions import (
    MoltbookApiError,
    AuthenticationRequiredError,
    InvalidApiKeyError,
    ApiKeyRevokedError,
    PaymentRequiredError,
    CreditsExhaustedError,
    EntitlementExpiredError,
    EntitlementExhaustedError,
    RateLimitExceededError,
    RpcGatewayError,
    DatabaseUnavailableError,
    ValidationError,
    UnboundPaymentError,
    InvoiceExpiredError,
)

__version__ = "1.0.0"

__all__ = [
    "MoltbookIntelClient",
    "ToolDAGResolver",
    "canonical_json",
    "b58decode",
    "verify_witness_payload_offline",
    "verify_witness_signature_local",
    "MoltbookApiError",
    "AuthenticationRequiredError",
    "InvalidApiKeyError",
    "ApiKeyRevokedError",
    "PaymentRequiredError",
    "CreditsExhaustedError",
    "EntitlementExpiredError",
    "EntitlementExhaustedError",
    "RateLimitExceededError",
    "RpcGatewayError",
    "DatabaseUnavailableError",
    "ValidationError",
    "UnboundPaymentError",
    "InvoiceExpiredError",
]
