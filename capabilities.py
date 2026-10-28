"""
Moltbook Alpha — Machine-Readable Agent Capability Discovery Engine.
Provides autonomous orchestrators and LLM agents with runtime introspection of
available endpoints, input parameters, permission requirements, credit costs,
rate limits, and version compatibility.
"""

from typing import Dict, Any, List
from data_products import DEFAULT_DATA_PRODUCTS
from rate_limiter import (
    DEFAULT_RATE_LIMIT_CAPACITY,
    DEFAULT_RATE_LIMIT_SUSTAINED_PER_MIN,
    DEFAULT_MAX_CONCURRENT_IN_FLIGHT,
)


def get_api_capabilities() -> Dict[str, Any]:
    """
    Returns the comprehensive machine-readable capability manifest for Moltbook Alpha API.
    """
    return {
        "service": "moltbook-alpha-api",
        "api_version": "1.2.0",
        "protocol_version": "2026-10-27",
        "documentation_url": "https://theheiszt.github.io/moltbook-alpha",
        "compatibility": {
            "min_python_sdk_version": "2.0.0",
            "mcp_protocol_version": "2024-11-05",
            "supported_auth_methods": [
                "X-API-KEY header",
                "Authorization: Bearer <key>",
                "Admin Session Token (adm_sess_*)",
            ],
            "supported_payment_rails": ["Solana Mainnet (USDC / SOL)", "Nano (XNO)"],
        },
        "rate_limits": {
            "unauthenticated_per_minute": int(DEFAULT_RATE_LIMIT_SUSTAINED_PER_MIN),
            "authenticated_sustained_per_minute": int(DEFAULT_RATE_LIMIT_SUSTAINED_PER_MIN),
            "burst_capacity": int(DEFAULT_RATE_LIMIT_CAPACITY),
            "max_concurrent_in_flight": int(DEFAULT_MAX_CONCURRENT_IN_FLIGHT),
        },
        "pricing_and_quotas": {
            "default_snapshot_credit_cost": 1,
            "idempotency_ttl_seconds": 60,
            "unmetered_endpoints": [
                "/v1/health",
                "/v1/capabilities",
                "/v1/tools",
                "/v1/tools/{tool_name}/parameter-graph",
                "/v1/errors",
                "/v1/errors/{code}",
                "/v1/data-products",
                "/v1/data-products/{product_id}",
                "/v1/intel/sample",
                "/v1/account/quota",
                "/v1/account/usage",
                "/v1/payments/config",
                "/v1/payments/invoice",
                "/v1/witnesses/public-keys",
                "/v1/witnesses/verify",
                "/v1/webhooks",
                "/v1/webhooks/subscribe",
                "/v1/webhooks/{subscription_id}",
                "/v1/webhooks/test/{subscription_id}",
            ],
        },
        "capabilities": {
            "agent_data_exchange": {
                "status": "GA",
                "description": "Autonomous data product catalog, schema inspection, and structured snapshot retrieval.",
                "data_products": [
                    p.to_summary_dict()
                    for p in DEFAULT_DATA_PRODUCTS.values()
                ],
                "endpoints": [
                    {
                        "path": "/v1/data-products",
                        "method": "GET",
                        "auth_required": False,
                        "cost_credits": 0,
                        "description": "List all active data products, update frequencies, freshness, and pricing metadata.",
                    },
                    {
                        "path": "/v1/data-products/{product_id}",
                        "method": "GET",
                        "auth_required": False,
                        "cost_credits": 0,
                        "description": "Inspect full contract, input/output JSON schemas, and freshness guarantees for a specific product.",
                    },
                    {
                        "path": "/v1/data-products/{product_id}/latest",
                        "method": "GET",
                        "auth_required": True,
                        "cost_credits": 1,
                        "idempotency_supported": True,
                        "description": "Retrieve the latest validated snapshot of a data product with atomic credit reservation and cryptographic receipt.",
                    },
                ],
            },
            "market_intelligence": {
                "status": "GA",
                "description": "Distilled social and security intelligence across Moltbook autonomous agent submolts.",
                "endpoints": [
                    {
                        "path": "/v1/intel/sample",
                        "method": "GET",
                        "auth_required": False,
                        "cost_credits": 0,
                        "description": "Unmetered evaluation briefing payload with representative signals and opportunities.",
                    },
                    {
                        "path": "/v1/intel/latest",
                        "method": "GET",
                        "auth_required": True,
                        "cost_credits": 1,
                        "idempotency_supported": True,
                        "description": "Authenticated market intelligence briefing signed with an Ed25519 state witness.",
                    },
                    {
                        "path": "/v1/intel/signals",
                        "method": "GET",
                        "auth_required": False,
                        "cost_credits": 0,
                        "description": "Search indexed signals by category, confidence, and limit.",
                    },
                    {
                        "path": "/v1/intel/refresh",
                        "method": "POST",
                        "auth_required": False,
                        "cost_credits": 0,
                        "description": "Trigger an immediate ingestion cycle across approved Moltbook submolts and Solana DEX feeds.",
                    },
                ],
            },
            "trading_alpha_and_arbitrage": {
                "status": "GA",
                "description": "Live cross-DEX arbitrage scanner and quantitative machine-readable trading directives.",
                "endpoints": [
                    {
                        "path": "/v1/intel/opportunities",
                        "method": "GET",
                        "auth_required": False,
                        "cost_credits": 0,
                        "description": "Scan live cross-DEX arbitrage opportunities with pool-fee net profit calculations.",
                    },
                    {
                        "path": "/v1/intel/signals/trading",
                        "method": "GET",
                        "auth_required": False,
                        "cost_credits": 0,
                        "description": "Retrieve machine-readable trading directives with entry, stop-loss, targets, and execution routing.",
                    },
                    {
                        "path": "/v1/intel/microstructure",
                        "method": "GET",
                        "auth_required": False,
                        "cost_credits": 0,
                        "description": "Inspect fleet-wide CLMM orderbook depths and manipulation anomalies (tick vacuums, spoofed walls).",
                    },
                    {
                        "path": "/v1/intel/microstructure/{pool_id}",
                        "method": "GET",
                        "auth_required": False,
                        "cost_credits": 0,
                        "description": "Deep tick-level liquidity distribution and anomaly details for a specific CLMM pool.",
                    },
                ],
            },
            "account_and_usage": {
                "status": "GA",
                "description": "Key status, remaining credits, active credit lots, and rate limit inspection.",
                "endpoints": [
                    {
                        "path": "/v1/account/quota",
                        "method": "GET",
                        "auth_required": True,
                        "cost_credits": 0,
                        "description": "Inspect remaining credits, tier, and 90-day top-up credit lots without consuming credits.",
                    },
                    {
                        "path": "/v1/account/usage",
                        "method": "GET",
                        "auth_required": True,
                        "cost_credits": 0,
                        "description": "Comprehensive report of usage consumption, remaining entitlement, active lots, and thresholds.",
                    },
                ],
            },
            "dag_tool_parameters": {
                "status": "GA",
                "description": "Directed Acyclic Graph tool parameter prerequisite modeling and topological resolution.",
                "endpoints": [
                    {
                        "path": "/v1/tools",
                        "method": "GET",
                        "auth_required": False,
                        "cost_credits": 0,
                        "description": "List registered agent tools with links to compiled parameter graphs.",
                    },
                    {
                        "path": "/v1/tools/{tool_name}/parameter-graph",
                        "method": "GET",
                        "auth_required": False,
                        "cost_credits": 0,
                        "description": "Get compiled parameter dependency DAG with topological execution stages.",
                    },
                ],
            },
            "cryptographic_witnesses": {
                "status": "GA",
                "description": "RFC 8785 deterministic JSON canonicalization and Ed25519 digital signature receipts.",
                "endpoints": [
                    {
                        "path": "/v1/witnesses/public-keys",
                        "method": "GET",
                        "auth_required": False,
                        "cost_credits": 0,
                        "description": "Retrieve active and historical Ed25519 verification public keys.",
                    },
                    {
                        "path": "/v1/witnesses/verify",
                        "method": "POST",
                        "auth_required": False,
                        "cost_credits": 0,
                        "description": "Cryptographically verify a state witness receipt and signature.",
                    },
                ],
            },
            "webhooks_and_push_alerts": {
                "status": "GA",
                "description": "Outbound HTTPS push webhooks for real-time cross-DEX arbitrage alerts and security anomalies with HMAC-SHA256 signatures.",
                "supported_events": [
                    "CROSS_DEX_ARBITRAGE",
                    "SECURITY_ANOMALY",
                    "TICK_VACUUM",
                    "SPOOFED_WALL",
                    "BRIEFING_PUBLISHED",
                    "ALL",
                ],
                "endpoints": [
                    {
                        "path": "/v1/webhooks/subscribe",
                        "method": "POST",
                        "auth_required": False,
                        "cost_credits": 0,
                        "description": "Register an automated outbound HTTPS webhook subscription with HMAC-SHA256 signature.",
                    },
                    {
                        "path": "/v1/webhooks",
                        "method": "GET",
                        "auth_required": False,
                        "cost_credits": 0,
                        "description": "List active webhook subscriptions with masked secret tokens.",
                    },
                    {
                        "path": "/v1/webhooks/{subscription_id}",
                        "method": "DELETE",
                        "auth_required": False,
                        "cost_credits": 0,
                        "description": "Deregister an outbound webhook callback subscription.",
                    },
                    {
                        "path": "/v1/webhooks/test/{subscription_id}",
                        "method": "POST",
                        "auth_required": False,
                        "cost_credits": 0,
                        "description": "Dispatch an HMAC-SHA256 signed test verification ping payload to confirm receiver connectivity.",
                    },
                ],
            },
            "payments_and_settlement": {
                "status": "GA",
                "description": "Solana Mainnet and Nano settlement with instant automated API key minting.",
                "endpoints": [
                    {
                        "path": "/v1/payments/config",
                        "method": "GET",
                        "auth_required": False,
                        "cost_credits": 0,
                        "description": "Inspect treasury addresses, pricing tiers, and accepted assets.",
                    },
                    {
                        "path": "/v1/payments/invoice",
                        "method": "POST",
                        "auth_required": False,
                        "cost_credits": 0,
                        "description": "Generate an on-chain payment invoice with recovery claim secret.",
                    },
                    {
                        "path": "/v1/payments/verify-solana",
                        "method": "POST",
                        "auth_required": False,
                        "cost_credits": 0,
                        "description": "Verify finalized Solana transaction and mint authenticated API key.",
                    },
                ],
            },
        },
    }
