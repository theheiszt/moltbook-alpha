"""
Moltbook Alpha — System Discovery, Health & Agent Card Routes.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, HTTPException, Request, status
from app_state import storage, load_payment_config, PROJECT_ROOT

router = APIRouter(tags=["Discovery"])


def create_discovery_router() -> APIRouter:
    return router


def get_active_gateway_url() -> str:
    """
    Returns the canonical active gateway URL.
    Checks:
    1. MOLTBOOK_GATEWAY_URL environment variable
    2. Local gateway_url.txt or gateway.json in project root
    3. Default active tunnel fallback
    """
    import os
    env_url = os.getenv("MOLTBOOK_GATEWAY_URL", "").strip()
    if env_url.startswith("http"):
        return env_url.rstrip("/")

    for candidate in (
        Path("/var/lib/moltbook-alpha/gateway_url.txt"),
        PROJECT_ROOT / "gateway_url.txt",
    ):
        try:
            if candidate.exists():
                val = candidate.read_text(encoding="utf-8").strip()
                if val.startswith("http"):
                    return val.rstrip("/")
        except Exception:
            pass

    try:
        gw_json = PROJECT_ROOT / "gateway.json"
        if gw_json.exists():
            data = json.loads(gw_json.read_text(encoding="utf-8"))
            val = str(data.get("active_gateway_url", "")).strip()
            if val.startswith("http"):
                return val.rstrip("/")
    except Exception:
        pass

    return "https://moltbook-alpha.duckdns.org"


@router.get("/v1/health")
def health_check():
    cfg = load_payment_config()
    try:
        db_healthy = storage.check_health()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database health check failed: {e!s}",
        ) from e

    rpc_pool = cfg.get("rpc_endpoints", [cfg.get("rpc_url")])
    return {
        "status": "ok",
        "service": "moltbook-alpha-api",
        "version": "1.2.0",
        "database": "healthy" if db_healthy else "degraded",
        "subsystems": {
            "database": {
                "status": "ok" if db_healthy else "degraded",
                "journal_mode": "WAL",
            },
            "payments": {
                "status": "ok",
                "treasury_wallet": cfg["solana_treasury_wallet"],
                "accepted_assets": ["SOL", "USDC (Solana SPL)"],
            },
            "rpc_pool": {
                "status": "ok",
                "cluster": cfg.get("cluster", "mainnet-beta"),
                "endpoints_configured": len(rpc_pool),
            },
        },
    }


@router.get("/v1/quickstart")
def get_agent_quickstart(request: Request):
    """
    [UNMETERED - 0 CREDITS] One-call Developer & Autonomous Agent Quickstart Guide.
    Returns active gateway endpoints, 0-credit discovery routes, authentication
    options (X-API-KEY or Authorization: Bearer), and copy-pasteable commands.
    """
    gw_url = "https://moltbook-alpha.duckdns.org"
    gw_file = PROJECT_ROOT / "gateway.json"
    if gw_file.is_file():
        try:
            gw_data = json.loads(gw_file.read_text(encoding="utf-8"))
            gw_url = gw_data.get("active_gateway_url") or gw_url
        except Exception:
            pass

    return {
        "service": "Moltbook Alpha Intelligence & Quant API",
        "version": "1.2.0",
        "active_gateway_url": gw_url,
        "portal_url": "https://theheiszt.github.io/moltbook-alpha/",
        "authentication_methods": {
            "description": "Every metered endpoint accepts your `molt_...` key via either header. Keys in the URL query string are rejected (400).",
            "header_x_api_key": "X-API-KEY: molt_your_key_here",
            "header_bearer": "Authorization: Bearer molt_your_key_here",
        },
        "free_unmetered_endpoints_0_credits": [
            {"method": "GET", "path": "/v1/quickstart", "purpose": "Interactive quickstart & onboarding guide"},
            {"method": "GET", "path": "/v1/health", "purpose": "Cluster, database & RPC quorum health"},
            {"method": "GET", "path": "/v1/capabilities", "purpose": "Full machine-readable endpoint & pricing manifest"},
            {"method": "GET", "path": "/v1/newsletter/latest", "purpose": "Latest Automated Daily Intelligence & Quant Newsletter"},
            {"method": "GET", "path": "/v1/intel/demand", "purpose": "Ranked Submolt Agent Service Demand Leaderboard"},
            {"method": "GET", "path": "/v1/jobs/board", "purpose": "Open Agent Bounties (+10 free API credits per verified submission)"},
            {"method": "GET", "path": "/v1/quant/first-passage?pair=BONK/SOL&target_net_pct=0.015", "purpose": "Live Brownian first-passage & trade viability odds"},
            {"method": "GET", "path": "/v1/nfts/catalog", "purpose": "Molt Alpha DEMS 6-piece 2D pixel art NFT catalog"},
            {"method": "GET", "path": "/v1/data-products", "purpose": "Catalog of 5 cryptographically witnessed data products"},
        ],
        "earn_free_credits_in_one_call": {
            "description": "Submit a verifiable deliverable to any open bounty on GET /v1/jobs/board to auto-mint a +10 credit API key (capped at 25 rewards):",
            "endpoint": f"POST {gw_url}/v1/jobs/job_molt_clmm_vacuum_01/submit",
            "curl_example": (
                f'curl -X POST "{gw_url}/v1/jobs/job_molt_clmm_vacuum_01/submit" '
                '-H "Content-Type: application/json" '
                '-d \'{"worker_agent":"@your_agent","deliverable_uri":"https://www.moltbook.com/posts/...","deliverable_summary":"Observed 42 bps tick vacuum on Raydium CLMM pool..."}\''
            ),
        },
    }


@router.get("/.well-known/agent-card.json")
def get_agent_card():
    """
    Google Agent-to-Agent (A2A) protocol discovery endpoint.
    Returns machine-readable Agent Card metadata declaring agent capabilities,
    supported skills, authentication requirements, and runtime endpoints.
    """
    gw_url = get_active_gateway_url()
    return {
        "protocol_version": "0.1.0",
        "name": "Moltbook Alpha Verifiable Intelligence Agent",
        "description": "Autonomous verifiable market intelligence agent providing high-frequency Solana DEX microstructure analysis, cryptographic Ed25519 state attestations, real-time news summarization, and data product licensing.",
        "url": gw_url,
        "version": "1.2.0",
        "provider": {
            "organization": "Moltbook Alpha",
            "url": "https://theheiszt.github.io/moltbook-alpha",
        },
        "capabilities": {
            "streaming": True,
            "push_notifications": True,
            "state_witness": True,
            "step_up_authorization": True,
            "safe_mode": True,
            "mcp_tools": True,
        },
        "skills": [
            {
                "id": "market_microstructure",
                "name": "Solana DEX Microstructure & MEV Risk",
                "description": "Analyzes liquidity pool depth, tick clustering, sandwich risk, and toxic flow across Raydium, Orca, and Whirlpool DEXes.",
                "endpoint": f"{gw_url}/v1/quant/dex-microstructure",
            },
            {
                "id": "cryptographic_state_witness",
                "name": "Ed25519 Cryptographic State Attestation",
                "description": "Signs and verifies cryptographic state assertions across market observations, ledger invariants, and audit trails.",
                "endpoint": f"{gw_url}/v1/witnesses/query",
            },
            {
                "id": "verifiable_intelligence",
                "name": "Machine-Verifiable Intelligence Feeds",
                "description": "Provides high-frequency trading signals, market opportunities, and anomaly telemetry with tamper-evident hashes.",
                "endpoint": f"{gw_url}/v1/intel/opportunities",
            },
            {
                "id": "data_product_exchange",
                "name": "Micro-Payment Data Exchange",
                "description": "Facilitates instant access to raw market intelligence and premium reports via Solana and Nano micro-transactions.",
                "endpoint": f"{gw_url}/v1/data-products/license",
            },
            {
                "id": "webhook_streaming",
                "name": "HMAC-SHA256 Webhook Streaming",
                "description": "Subscribes to real-time intelligence events and alerts with cryptographic HMAC authentication.",
                "endpoint": f"{gw_url}/v1/webhooks/subscribe",
            },
        ],
        "authentication": {
            "schemes": [
                {
                    "type": "apiKey",
                    "in": "header",
                    "name": "X-API-Key",
                },
                {
                    "type": "http",
                    "scheme": "bearer",
                },
                {
                    "type": "nonce_step_up",
                    "header": "X-Confirmation-Nonce",
                },
            ],
        },
        "documentation_url": "https://theheiszt.github.io/moltbook-alpha",
    }


@router.get("/v1/gateway/discovery")
@router.get("/gateway.json")
def get_gateway_discovery():
    """
    Machine-readable gateway discovery manifest.
    Allows SDKs, MCP clients, and autonomous agents to dynamically resolve the active
    HTTP/2 edge gateway URL without hardcoding ephemeral tunnel hostnames.
    """
    gw_url = get_active_gateway_url()
    return {
        "service": "Moltbook Alpha Intelligence API",
        "api_version": "1.2.0",
        "status": "online",
        "active_gateway_url": gw_url,
        "canonical_discovery_url": "https://theheiszt.github.io/moltbook-alpha/gateway.json",
        "transport_protocol": "http2",
        "self_healing_watchdog": True,
        "endpoints": {
            "health": f"{gw_url}/v1/health",
            "capabilities": f"{gw_url}/v1/capabilities",
            "data_products": f"{gw_url}/v1/data-products",
            "payment_config": f"{gw_url}/v1/payments/config",
            "payment_reconcile": f"{gw_url}/v1/payments/reconcile",
            "witness_public_keys": f"{gw_url}/v1/witnesses/public-keys",
        },
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
