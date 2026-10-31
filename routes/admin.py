"""
Moltbook Alpha — Administrator Console, Metrics Exposition & Management Routes.
"""

import hmac
import logging
import os
import secrets
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel

from app_state import (
    _DASHBOARD_METRICS_CACHE,
    _DASHBOARD_METRICS_CACHE_LOCK,
    _DASHBOARD_METRICS_CACHE_TTL_SECONDS,
    SERVER_START_TIME,
    concurrency_limiter,
    get_client_ip,
    intel_engine,
    rate_limiter,
    storage,
    witness_manager,
)
from metrics import (
    record_rate_limit,
    registry,
    update_active_keys_gauge,
)
from ops.security.safe_mode import (
    disable_safe_mode,
    enable_safe_mode,
    get_safe_mode_status,
)
from ops.trading.dex_microstructure import microstructure_broadcaster

logger = logging.getLogger("moltbook_api")

router = APIRouter(tags=["Admin & Metrics"])


def create_admin_router() -> APIRouter:
    return router


@router.get("/metrics")
def get_prometheus_metrics(request: Request):
    """
    Prometheus and OpenTelemetry-compatible metrics exposition endpoint.
    Returns plain text in standard Prometheus 0.0.4 exposition format.
    Supports optional METRICS_BEARER_TOKEN authorization header if configured in production.
    """
    metrics_token = os.getenv("METRICS_BEARER_TOKEN", "").strip()
    if metrics_token:
        auth_header = request.headers.get("authorization", "")
        expected = f"Bearer {metrics_token}"
        if not secrets.compare_digest(auth_header, expected):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized access to metrics exposition endpoint.",
                headers={"WWW-Authenticate": "Bearer"},
            )

    try:
        update_active_keys_gauge(storage.get_active_keys_count())
    except Exception as e:
        logger.debug("Failed to update active keys gauge: %s", e, exc_info=True)
    text_data = registry.export_prometheus_text()
    return Response(
        content=text_data,
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@router.get("/v1/metrics/funnel")
def get_funnel_metrics_endpoint(request: Request, since: Optional[str] = None):
    """
    Returns aggregated conversion funnel metrics and recent privacy-sanitized events.
    """
    metrics_token = os.getenv("METRICS_BEARER_TOKEN", "").strip()
    if metrics_token:
        auth_header = request.headers.get("authorization", "")
        expected = f"Bearer {metrics_token}"
        if not hmac.compare_digest(auth_header, expected):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized access to metrics exposition.",
                headers={"WWW-Authenticate": "Bearer"},
            )
    return {
        "success": True,
        "funnel_metrics": storage.get_funnel_metrics(since_utc=since),
        "recent_events": storage.get_funnel_events(limit=25),
    }


class AdminLoginInput(BaseModel):
    username: str
    password: str


class AdminChangePasswordInput(BaseModel):
    current_password: str
    new_password: str


@router.post("/v1/admin/login")
def admin_login_endpoint(payload: AdminLoginInput, request: Request):
    client_ip = get_client_ip(request)
    allowed, retry_after = rate_limiter.is_allowed(f"admin_login:{client_ip}", limit=10, window_seconds=300)
    if not allowed:
        record_rate_limit("/v1/admin/login")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed login attempts. Please retry in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )

    clean_user = (payload.username or "").strip().upper()
    if not storage.verify_admin_credentials(clean_user, payload.password):
        storage.log_audit_event("admin_login_failed", f"Failed admin login attempt for '{clean_user}'", ip_address=client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid administrator credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    session_token = storage.create_admin_session(clean_user, duration_hours=24)
    storage.log_audit_event("admin_login_success", f"Admin user '{clean_user}' successfully authenticated", ip_address=client_ip)
    return {
        "success": True,
        "token": session_token,
        "username": clean_user,
        "expires_in_hours": 24,
    }


@router.post("/v1/admin/change-password")
def admin_change_password_endpoint(payload: AdminChangePasswordInput, request: Request):
    client_ip = get_client_ip(request)
    auth_header = request.headers.get("authorization", "")
    token = ""
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()

    admin_user = storage.validate_admin_session(token)
    if not admin_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid administrator session required to change password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    ok, message = storage.change_admin_password(admin_user, payload.current_password, payload.new_password)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message,
        )

    # Issue fresh session token since old sessions were revoked
    storage.log_audit_event(
        "admin_password_changed",
        f"Admin password changed for user '{admin_user}'",
        ip_address=client_ip,
    )
    new_token = storage.create_admin_session(admin_user, duration_hours=24)
    return {
        "success": True,
        "message": message,
        "new_token": new_token,
        "username": admin_user,
    }


@router.post("/v1/admin/logout")
def admin_logout_endpoint(request: Request):
    auth_header = request.headers.get("authorization", "")
    token = ""
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
    storage.revoke_admin_session(token)
    return {"success": True, "message": "Admin session revoked."}


@router.get("/v1/admin/session")
def admin_session_endpoint(request: Request):
    auth_header = request.headers.get("authorization", "")
    token = ""
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
    admin_user = storage.validate_admin_session(token)
    if not admin_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired admin session.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return {"authenticated": True, "username": admin_user}


class AdminSafeModeInput(BaseModel):
    active: bool
    reason: Optional[str] = "Administrative maintenance"


@router.get("/v1/admin/safemode")
def admin_get_safemode_endpoint(request: Request):
    auth_header = request.headers.get("authorization", "")
    token = ""
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
    admin_user = storage.validate_admin_session(token)
    if not admin_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid administrator session required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return {"success": True, "safe_mode": get_safe_mode_status()}


@router.post("/v1/admin/safemode")
def admin_toggle_safemode_endpoint(payload: AdminSafeModeInput, request: Request):
    client_ip = get_client_ip(request)
    auth_header = request.headers.get("authorization", "")
    token = ""
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
    admin_user = storage.validate_admin_session(token)
    if not admin_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid administrator session required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if payload.active:
        status_dict = enable_safe_mode(reason=payload.reason or "Administrative maintenance", operator=admin_user)
        storage.log_audit_event(
            "safe_mode_enabled",
            f"Safe mode enabled by '{admin_user}': {payload.reason}",
            ip_address=client_ip,
        )
    else:
        status_dict = disable_safe_mode(operator=admin_user)
        storage.log_audit_event(
            "safe_mode_disabled",
            f"Safe mode disabled by '{admin_user}'",
            ip_address=client_ip,
        )
    return {"success": True, "safe_mode": status_dict}


def _get_dashboard_ecosystem_summary() -> Dict[str, Any]:
    """Aggregates live Agent Job Board (25 reward cap) and Molt Alpha DEMS NFT inventory for the Operator Console."""
    jb_summary: Dict[str, Any] = {
        "open_jobs": 0,
        "rewards_claimed": 0,
        "max_rewards_cap": 25,
        "rewards_remaining": 25,
        "reward_per_response_credits": 10,
        "recent_submissions": [],
    }
    try:
        from job_board import AgentJobBoardManager
        jb_mgr = AgentJobBoardManager(storage_manager=storage)
        board = jb_mgr.list_jobs(limit=30)
        jb_summary["open_jobs"] = board.get("total_listed", 0)
        rp = board.get("reward_policy", {})
        jb_summary["rewards_claimed"] = rp.get("rewards_claimed", 0)
        jb_summary["max_rewards_cap"] = rp.get("max_rewards_cap", 25)
        jb_summary["rewards_remaining"] = rp.get("rewards_remaining", 25)
        with storage.connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT submission_id, job_id, worker_agent, deliverable_uri, status, state_witness_id, submitted_at FROM agent_job_submissions ORDER BY submitted_at DESC LIMIT 6"
            )
            jb_summary["recent_submissions"] = [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.debug("Failed to fetch job board summary: %s", e, exc_info=True)

    nft_summary: Dict[str, Any] = {
        "collection_name": "Molt Alpha DEMS",
        "total_editions_cap": 123,
        "total_minted_or_reserved": 0,
        "editions": [],
    }
    try:
        from nft_collection import MoltAlphaDemsCollection
        cat = MoltAlphaDemsCollection().list_catalog()
        items = cat.get("items", [])
        nft_summary["total_editions_cap"] = sum(int(i.get("max_supply", 0)) for i in items) or 123
        nft_summary["total_minted_or_reserved"] = int(cat.get("minted_editions_count", 0))
        nft_summary["editions"] = [
            {
                "edition_id": e["nft_id"],
                "name": f"#{e['number']} {e['short_name']}",
                "rarity": e["rarity"],
                "price_sol": e["price_sol"],
                "credits": e["bundled_credits"],
                "minted": e["minted_count"],
                "max_supply": e["max_supply"],
                "remaining": e["remaining_supply"],
            }
            for e in items
        ]
    except Exception as e:
        logger.debug("Failed to fetch NFT catalog summary: %s", e, exc_info=True)

    return {"job_board": jb_summary, "nft_collection": nft_summary}


@router.get("/v1/metrics/dashboard")
def get_dashboard_metrics_endpoint(request: Request):
    """
    Returns unified operational dashboard metrics for real-time monitoring.
    Requires administrator session token or METRICS_BEARER_TOKEN.
    """
    auth_header = request.headers.get("authorization", "")
    bearer_token = ""
    if auth_header.lower().startswith("bearer "):
        bearer_token = auth_header[7:].strip()

    is_authenticated = False
    metrics_token = os.getenv("METRICS_BEARER_TOKEN", "").strip()
    if metrics_token and bearer_token and hmac.compare_digest(bearer_token, metrics_token):
        is_authenticated = True
    elif bearer_token:
        admin_user = storage.validate_admin_session(bearer_token)
        if admin_user:
            is_authenticated = True

    if not is_authenticated:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin authentication required. Please sign in with ADMIN credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Rate limiting: max 30 requests per minute per IP to prevent runaway polling loops
    client_ip = get_client_ip(request)
    allowed, retry_after = rate_limiter.is_allowed(f"dashboard_metrics:{client_ip}", limit=30, window_seconds=60)
    if not allowed:
        record_rate_limit("/v1/metrics/dashboard")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Dashboard rate limit exceeded. Please retry in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )

    # In-memory TTL cache check: return cached payload if fresh within TTL window
    now_ts = time.time()
    with _DASHBOARD_METRICS_CACHE_LOCK:
        if (
            _DASHBOARD_METRICS_CACHE["payload"] is not None
            and (now_ts - _DASHBOARD_METRICS_CACHE["timestamp"]) < _DASHBOARD_METRICS_CACHE_TTL_SECONDS
        ):
            return _DASHBOARD_METRICS_CACHE["payload"]

    db_metrics = storage.get_dashboard_metrics()

    # Enrich with real-time in-memory telemetry
    active_ws = 0
    if hasattr(microstructure_broadcaster, "active_connections_count"):
        try:
            active_ws = microstructure_broadcaster.active_connections_count
            if callable(active_ws):
                active_ws = active_ws()
        except Exception as e:
            logger.debug("Failed to get active ws connections count: %s", e, exc_info=True)
            active_ws = 0

    # In-flight concurrency slots
    in_flight = 0
    if hasattr(concurrency_limiter, "_in_flight"):
        try:
            with getattr(concurrency_limiter, "_lock", threading.Lock()):
                in_flight = sum(len(slots) for slots in concurrency_limiter._in_flight.values())
        except Exception as e:
            logger.debug("Failed to get in-flight count: %s", e, exc_info=True)
            in_flight = 0

    # Request distribution from Prometheus registry
    requests_total = 0
    status_codes = {"2xx": 0, "4xx": 0, "5xx": 0}
    top_endpoints: Dict[str, int] = {}

    try:
        with registry._lock:
            for (m_name, labels_tuple), val in registry._counters.items():
                if m_name == "moltbook_api_requests_total":
                    requests_total += int(val)
                    labels_dict = dict(labels_tuple)
                    ep = labels_dict.get("endpoint", "other")
                    code_str = labels_dict.get("status_code", "200")
                    top_endpoints[ep] = top_endpoints.get(ep, 0) + int(val)
                    if code_str.startswith("2"):
                        status_codes["2xx"] += int(val)
                    elif code_str.startswith("4"):
                        status_codes["4xx"] += int(val)
                    elif code_str.startswith("5"):
                        status_codes["5xx"] += int(val)
    except Exception as e:
        logger.debug("Failed to read Prometheus counters: %s", e, exc_info=True)

    uptime_sec = round(time.time() - SERVER_START_TIME, 1)

    # Load latest intelligence briefing & daily newsletter for the Operator Console
    latest_briefing_info: Dict[str, Any] = {
        "briefing_id": "N/A",
        "state_witness_id": "Verified",
        "items_analyzed": 0,
        "signals_extracted": 0,
        "created_at": None,
        "briefing_markdown": "",
        "newsletter_markdown": "",
    }
    try:
        with storage.connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT briefing_id, items_analyzed, signals_extracted, report_markdown, state_witness_id, created_at
                FROM intel_briefings
                ORDER BY created_at DESC LIMIT 1
                """
            )
            b_row = cur.fetchone()
            if b_row:
                latest_briefing_info["briefing_id"] = b_row["briefing_id"]
                latest_briefing_info["items_analyzed"] = b_row["items_analyzed"]
                latest_briefing_info["signals_extracted"] = b_row["signals_extracted"]
                latest_briefing_info["briefing_markdown"] = b_row["report_markdown"] or ""
                latest_briefing_info["state_witness_id"] = b_row["state_witness_id"] or "Verified"
                latest_briefing_info["created_at"] = b_row["created_at"]
    except Exception as e:
        logger.debug("Failed to query latest briefing for metrics dashboard: %s", e, exc_info=True)

    try:
        from config import REPORTS_DIR
        lb_file = Path(REPORTS_DIR) / "latest_briefing.md"
        if lb_file.is_file():
            latest_briefing_info["briefing_markdown"] = lb_file.read_text(encoding="utf-8")
        ln_file = Path(REPORTS_DIR) / "latest_newsletter.md"
        if ln_file.is_file():
            latest_briefing_info["newsletter_markdown"] = ln_file.read_text(encoding="utf-8")
    except Exception as e:
        logger.debug("Failed to read briefing/newsletter markdown files: %s", e, exc_info=True)

    payload = {
        "success": True,
        "server": {
            "status": "healthy",
            "version": "1.2.0",
            "uptime_seconds": uptime_sec,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        "connected": {
            "active_websockets": active_ws,
            "in_flight_requests": in_flight,
            "events_last_5m": db_metrics["activity"]["events_last_5m"],
            "events_last_1h": db_metrics["activity"]["events_last_1h"],
            "events_last_24h": db_metrics["activity"]["events_last_24h"],
        },
        "users": db_metrics["users"],
        "sales": db_metrics["sales"],
        "traffic": {
            "total_requests": requests_total,
            "status_codes": status_codes,
            "top_endpoints": (
                sorted(
                    [(k, v) for k, v in top_endpoints.items() if k not in {"/v1/metrics/dashboard", "/dashboard", "unmatched_route"}],
                    key=lambda x: x[1],
                    reverse=True,
                )[:8]
                or sorted(top_endpoints.items(), key=lambda x: x[1], reverse=True)[:8]
            ),
        },
        "funnel": db_metrics["funnel"],
        "recent_activity": db_metrics["recent_activity"],
        "latest_briefing": latest_briefing_info,
        "ecosystem": _get_dashboard_ecosystem_summary(),
    }

    with _DASHBOARD_METRICS_CACHE_LOCK:
        _DASHBOARD_METRICS_CACHE["timestamp"] = now_ts
        _DASHBOARD_METRICS_CACHE["payload"] = payload

    return payload


class AdminIngestPostRequest(BaseModel):
    post_url_or_id: str


@router.post("/v1/admin/briefing/ingest-post")
def admin_ingest_moltbook_post_endpoint(payload: AdminIngestPostRequest, request: Request):
    """
    Allows an authenticated administrator in the Operator Console to paste any Moltbook
    post URL or ID, ingest it + its top peer-review comments, and re-synthesize the
    Executive Intelligence Briefing & Daily Newsletter in one click.
    """
    auth_header = request.headers.get("authorization", "")
    bearer_token = auth_header[7:].strip() if auth_header.lower().startswith("bearer ") else ""
    is_authenticated = False
    metrics_token = os.getenv("METRICS_BEARER_TOKEN", "").strip()
    if metrics_token and bearer_token and hmac.compare_digest(bearer_token, metrics_token):
        is_authenticated = True
    elif bearer_token and storage.validate_admin_session(bearer_token):
        is_authenticated = True

    if not is_authenticated:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin authentication required.")

    ingested = intel_engine.ingest_moltbook_post(payload.post_url_or_id.strip(), include_comments=True)
    intel_engine.extract_signals(limit_items=50)
    from ops.publisher import publish_daily_alpha
    res = publish_daily_alpha(dry_run=True, force_refresh=False, storage_manager=storage, witness_manager=witness_manager)
    res["post_ingested"] = bool(ingested)
    res["post_url_or_id"] = payload.post_url_or_id.strip()
    storage.log_audit_event(
        "admin_post_ingested",
        f"Admin ingested post {payload.post_url_or_id.strip()} -> briefing {res.get('briefing_id')}",
        ip_address=get_client_ip(request),
    )
    return res


@router.post("/v1/admin/briefing/refresh")
def admin_refresh_briefing_endpoint(request: Request):
    """
    Allows an authenticated administrator in the Operator Console to synthesize
    a fresh intelligence briefing and daily newsletter on demand.
    """
    auth_header = request.headers.get("authorization", "")
    bearer_token = auth_header[7:].strip() if auth_header.lower().startswith("bearer ") else ""
    is_authenticated = False
    metrics_token = os.getenv("METRICS_BEARER_TOKEN", "").strip()
    if metrics_token and bearer_token and hmac.compare_digest(bearer_token, metrics_token):
        is_authenticated = True
    elif bearer_token and storage.validate_admin_session(bearer_token):
        is_authenticated = True

    if not is_authenticated:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin authentication required.")

    from ops.publisher import publish_daily_alpha
    res = publish_daily_alpha(dry_run=True, force_refresh=False, storage_manager=storage, witness_manager=witness_manager)
    storage.log_audit_event("admin_briefing_refreshed", f"Admin synthesized briefing {res.get('briefing_id')}", ip_address=get_client_ip(request))
    return res
