"""
Moltbook Alpha — Pydantic Response Schemas for Core and Metered Routes.
Declares explicit typed response models for API documentation and client SDK contract typing.
"""

from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, ConfigDict


class BaseResponseSchema(BaseModel):
    model_config = ConfigDict(extra="allow")


class IntelSignalsResponse(BaseResponseSchema):
    count: int
    signals: List[Dict[str, Any]]
    next_cursor: Optional[str] = None


class IntelOpportunitiesResponse(BaseResponseSchema):
    count: int
    min_profit_pct: float
    opportunities: List[Dict[str, Any]]
    timestamp_utc: Union[float, str]
    next_cursor: Optional[str] = None


class IntelTradingSignalsResponse(BaseResponseSchema):
    count: int
    min_confidence: Union[float, str]
    trading_signals: List[Dict[str, Any]]
    timestamp_utc: Union[float, str]


class IntelMicrostructureOverviewResponse(BaseResponseSchema):
    status: str
    tracked_pool_count: int
    active_anomaly_count: int
    depth_bps: Union[float, int]
    pools: List[Dict[str, Any]]
    recent_anomalies: List[Dict[str, Any]]
    state_witness_id: Optional[str] = None
    timestamp_utc: Union[float, str]


class IntelPoolMicrostructureResponse(BaseResponseSchema):
    pool_id: str
    protocol: str
    pair: str
    current_tick: Optional[int] = None
    current_price: float
    bid_depth_usd: float
    ask_depth_usd: float
    imbalance_ratio: float
    active_bin_count: int
    timestamp_utc: Union[float, str]
    raw_bins: List[Dict[str, Any]]
    anomalies: List[Dict[str, Any]]
    state_witness: Optional[Dict[str, Any]] = None


class BriefingLatestResponse(BaseResponseSchema):
    success: bool
    user_tier: str
    credits_remaining: int
    briefing_markdown: str
    trading_signals: List[Dict[str, Any]]
    opportunities: List[Dict[str, Any]]
    state_witness_id: Optional[str] = None


class DataProductLatestResponse(BaseResponseSchema):
    product_id: str
    snapshot_id: str
    generated_at: str
    retrieval_outcome: Optional[str] = None
    freshness_seconds: Optional[int] = None
    source_attribution: Optional[Dict[str, Any]] = None
    state_witness_id: Optional[str] = None
    usage_receipt: Optional[Dict[str, Any]] = None


class AccountQuotaUsageResponse(BaseResponseSchema):
    success: bool
    key_prefix: str
    tier: str
    credits_remaining: int
    is_active: bool
    created_at: str
    low_credit_warning: bool
    entitlement: Optional[Dict[str, Any]] = None
    credit_lots: Optional[List[Dict[str, Any]]] = None
    usage: Optional[Dict[str, Any]] = None
    rate_limit_state: Optional[Dict[str, Any]] = None


class QuantFirstPassageResponse(BaseResponseSchema):
    pair: str
    target_net_pct: float
    roundtrip_spread_bps: float
    required_gross_move_pct: float
    volatility_metrics: Dict[str, Any]
    two_barrier_analysis: Dict[str, Any]
    horizon_probabilities: List[Dict[str, Any]]
    optimal_target_ladder: List[Dict[str, Any]]
    recommended_target_net_pct: float
    state_witness_id: Optional[str] = None
    witness_signature: Optional[str] = None
    generated_at: str
    cache_status: Optional[str] = None
    cache_age_seconds: Optional[float] = None


class QuantTradeViabilityResponse(BaseResponseSchema):
    pair: str
    target_net_pct: float
    roundtrip_spread_bps: float
    required_gross_move_pct: float
    volatility_metrics: Dict[str, Any]
    two_barrier_analysis: Dict[str, Any]
    horizon_probabilities: List[Dict[str, Any]]
    optimal_target_ladder: List[Dict[str, Any]]
    recommended_target_net_pct: float
    state_witness_id: Optional[str] = None
    witness_signature: Optional[str] = None
    generated_at: str
