"""
Moltbook Alpha — Capabilities, Data Products, Tools, Witnesses & Error Registry Routes.
"""

from typing import Any, Dict, Optional
from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel
from app_state import (
    data_product_exchange,
    witness_manager,
    intel_engine,
    dex_microstructure,
    rate_limiter,
    get_client_ip,
    _payment_required_detail,
    MeteredCall,
    record_rate_limit,
)
from capabilities import get_api_capabilities
from dag_tool_parameters import TOOL_DAG_REGISTRY
from errors import (
    DOCS_BASE_URL,
    ERROR_REGISTRY,
    OperationOutcome,
    RecoveryAction,
)

router = APIRouter(tags=["Exchange"])


def create_exchange_router() -> APIRouter:
    return router


@router.get("/v1/capabilities")
def get_capabilities_manifest():
    """
    Returns the comprehensive machine-readable capability manifest for Moltbook Alpha API.
    Allows autonomous orchestrators and agents to discover endpoints, schemas, costs,
    and input requirements without manual human documentation.
    """
    return get_api_capabilities()


@router.get("/v1/data-products")
def list_data_products():
    """
    Agent Data Exchange: Lists all available data products, update frequencies,
    freshness guarantees, schemas, and credit pricing terms.
    """
    products = data_product_exchange.list_products()
    return {
        "count": len(products),
        "products": products,
        "data_products": products,
    }


@router.get("/v1/data-products/{product_id}")
def get_data_product_contract(product_id: str):
    """
    Agent Data Exchange: Returns the complete contract and machine-readable JSON schemas
    for a specific data product.
    """
    prod = data_product_exchange.get_product(product_id)
    if not prod:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Data product '{product_id}' not found in exchange catalog. Available: {[p['product_id'] for p in data_product_exchange.list_products()]}",
        )
    return prod.to_contract_dict()


@router.get("/v1/data-products/{product_id}/sample")
def get_data_product_sample(product_id: str, request: Request):
    """
    Agent Data Exchange: Returns a free (0-credit), deterministic, schema-valid sample
    snapshot for pre-purchase agent evaluation, complete with provenance metadata,
    evidence grading, retrieval outcome semantics, and an Ed25519 witness signature.
    """
    client_ip = get_client_ip(request)
    allowed, retry_after = rate_limiter.is_allowed(f"data_product_sample:{client_ip}", limit=60, window_seconds=60)
    if not allowed:
        record_rate_limit(f"/v1/data-products/{product_id}/sample")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many sample preview requests. Please retry in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )

    try:
        sample = data_product_exchange.generate_sample_snapshot(
            product_id=product_id,
            witness_manager=witness_manager,
        )
    except KeyError:
        sample = None
    if not sample:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Data product '{product_id}' not found in exchange catalog. Available: {[p['product_id'] for p in data_product_exchange.list_products()]}",
        )
    return sample


@router.get("/v1/data-products/{product_id}/latest")
def get_data_product_latest(
    product_id: str,
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="X-API-KEY"),
    min_profit_pct: Optional[float] = None,
    pair: Optional[str] = None,
    asset: Optional[str] = None,
    min_confidence: Optional[float] = None,
    evidence_level: Optional[str] = None,
    category: Optional[str] = None,
    limit: Optional[int] = None,
):
    """
    Agent Data Exchange: Retrieves the latest structured snapshot for a data product.
    Authenticates the caller and atomically reserves/deducts 1 credit against active credit lots.
    Idempotent: Identical requests with an idempotency-key replay without duplicate credit charges.
    Zero-charge on failure: Errors release the credit reservation safely.
    """
    contract = data_product_exchange.get_product(product_id)
    if not contract:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Data product '{product_id}' not found in exchange catalog.",
        )

    payment_detail = _payment_required_detail(
        message=f"Accessing data product '{product_id}' requires an active API key or payment.",
        price=f"{contract.cost_credits} credit per successful snapshot retrieval.",
    )
    with MeteredCall(
        request,
        f"/v1/data-products/{product_id}/latest",
        ip_bucket="data_product",
        payment_required_detail=payment_detail,
    ) as call:
        res_info = call.reservation
        receipt = {
            "request_id": call.request_id,
            "product_id": product_id,
            "credits_deducted": contract.cost_credits,
            "entitlement_tier": res_info.get("tier"),
            "lot_id": res_info.get("lot_id"),
            "credits_remaining": res_info.get("credits"),
            "key_hash": res_info.get("key_hash"),
            "key_prefix": res_info.get("key_prefix"),
        }

        params = {}
        if min_profit_pct is not None:
            params["min_profit_pct"] = min_profit_pct
        if pair is not None:
            params["pair"] = pair
        if asset is not None:
            params["asset"] = asset
        if min_confidence is not None:
            params["min_confidence"] = min_confidence
        if evidence_level is not None:
            params["evidence_level"] = evidence_level
        if category is not None:
            params["category"] = category
        if limit is not None:
            params["limit"] = limit

        snapshot = data_product_exchange.generate_snapshot(
            product_id=product_id,
            intel_engine=intel_engine,
            dex_microstructure=dex_microstructure,
            witness_manager=witness_manager,
            params=params,
            receipt=receipt,
        )
        return call.settle(snapshot)


@router.get("/v1/errors")
def get_error_registry():
    """
    Returns the complete machine-readable error code registry,
    including HTTP status mappings, retryability semantics, operation outcomes,
    state effects, recovery actions, and documentation URLs.
    """
    return {
        "version": "1.0.0",
        "docs_base_url": DOCS_BASE_URL,
        "errors": {
            k: {
                "code": v.code.value,
                "status_code": v.status_code,
                "retryable": v.retryable,
                "outcome": v.outcome.value if isinstance(v.outcome, OperationOutcome) else str(v.outcome),
                "state_effect": v.state_effect,
                "recovery_action": v.recovery_action.value if isinstance(v.recovery_action, RecoveryAction) else str(v.recovery_action),
                "default_retry_after": v.default_retry_after,
                "default_message": v.default_message,
                "description": v.description,
                "docs_url": v.docs_url,
            }
            for k, v in ERROR_REGISTRY.items()
        },
    }


@router.get("/v1/errors/{code}")
def get_error_definition(code: str):
    """
    Returns the specification and retry semantics for a specific error code.
    """
    norm_code = code.strip().upper()
    defn = ERROR_REGISTRY.get(norm_code)
    if not defn:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Error code '{code}' not recognized in error taxonomy registry.",
        )
    return {
        "code": defn.code.value,
        "status_code": defn.status_code,
        "retryable": defn.retryable,
        "outcome": defn.outcome.value if isinstance(defn.outcome, OperationOutcome) else str(defn.outcome),
        "state_effect": defn.state_effect,
        "recovery_action": defn.recovery_action.value if isinstance(defn.recovery_action, RecoveryAction) else str(defn.recovery_action),
        "default_retry_after": defn.default_retry_after,
        "default_message": defn.default_message,
        "description": defn.description,
        "docs_url": defn.docs_url,
    }


@router.get("/v1/tools")
def list_available_tools():
    """
    Returns registered agent tools with links to their parameter DAGs.
    """
    return {
        "version": "1.0.0",
        "tools": [
            {
                "tool_name": name,
                "version": dag.version,
                "description": dag.description,
                "parameter_count": len(dag.parameters),
                "parameter_graph_endpoint": f"/v1/tools/{name}/parameter-graph",
            }
            for name, dag in TOOL_DAG_REGISTRY.items()
        ],
    }


@router.get("/v1/tools/{tool_name}/parameter-graph")
def get_tool_parameter_graph(tool_name: str):
    """
    Returns the compiled Directed Acyclic Graph (DAG) for a tool,
    including prerequisite dependencies, topological execution stages, and resolvers.
    """
    dag = TOOL_DAG_REGISTRY.get(tool_name)
    if not dag:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool '{tool_name}' not found in registered tool catalog.",
        )
    return dag.to_dict()


class VerifyWitnessInput(BaseModel):
    witness: Dict[str, Any]
    public_key_base58: Optional[str] = None


@router.get("/v1/witnesses/public-keys")
def get_witness_public_keys():
    """
    Returns active Ed25519 public keys used for signing cryptographic state witnesses.
    Allows autonomous agents to verify non-repudiation and RFC 8785 canonical hash integrity.
    """
    return witness_manager.get_public_keys_metadata()


@router.get("/v1/witnesses/{witness_id}")
def get_state_witness(witness_id: str):
    """
    Fetches an immutable cryptographic state witness record by ID.
    """
    record = witness_manager.get_witness(witness_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"State witness '{witness_id}' not found.",
        )
    return record


@router.post("/v1/witnesses/verify")
def verify_state_witness(input_data: VerifyWitnessInput):
    """
    Verifies an Ed25519 cryptographic state witness payload against RFC 8785 canonicalization
    and the server's public key (or an optionally supplied public key).
    """
    return witness_manager.verify_witness_payload(
        input_data.witness,
        public_key_b58=input_data.public_key_base58,
    )
