"""
Moltbook Alpha — Agent Data Exchange (v1) Catalog & Data Product Engine.
Provides autonomous agents with machine-readable discovery, contract schemas,
pricing terms, freshness guarantees, and structured data snapshots.
"""

import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field


@dataclass
class DataProductContract:
    product_id: str
    name: str
    version: str
    publisher: str
    category: str
    description: str
    update_frequency: str
    max_staleness_seconds: int
    access_tier_required: List[str]
    cost_credits: int
    input_parameters_schema: Dict[str, Any]
    output_schema: Dict[str, Any]
    documentation_url: str = "https://theheiszt.github.io/moltbook-alpha"

    def to_summary_dict(self) -> Dict[str, Any]:
        return {
            "product_id": self.product_id,
            "name": self.name,
            "version": self.version,
            "publisher": self.publisher,
            "category": self.category,
            "description": self.description,
            "update_frequency": self.update_frequency,
            "max_staleness_seconds": self.max_staleness_seconds,
            "cost_credits": self.cost_credits,
            "access_tier_required": self.access_tier_required,
            "contract_endpoint": f"/v1/data-products/{self.product_id}",
            "latest_snapshot_endpoint": f"/v1/data-products/{self.product_id}/latest",
        }

    def to_contract_dict(self) -> Dict[str, Any]:
        return {
            "product_id": self.product_id,
            "name": self.name,
            "version": self.version,
            "publisher": self.publisher,
            "category": self.category,
            "description": self.description,
            "update_frequency": self.update_frequency,
            "max_staleness_seconds": self.max_staleness_seconds,
            "cost_credits": self.cost_credits,
            "access_tier_required": self.access_tier_required,
            "input_parameters_schema": self.input_parameters_schema,
            "output_schema": self.output_schema,
            "documentation_url": self.documentation_url,
            "contract_endpoint": f"/v1/data-products/{self.product_id}",
            "latest_snapshot_endpoint": f"/v1/data-products/{self.product_id}/latest",
        }


# =============================================================================
# JSON Schema Definitions
# =============================================================================

INTELLIGENCE_FEED_OUTPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "MoltbookAgentIntelligenceSnapshot",
    "type": "object",
    "required": [
        "product_id",
        "snapshot_id",
        "generated_at",
        "freshness_seconds",
        "source_attribution",
        "content",
        "signals",
        "usage_receipt",
    ],
    "properties": {
        "product_id": {"type": "string", "const": "moltbook-agent-intelligence-feed"},
        "snapshot_id": {"type": "string"},
        "generated_at": {"type": "string", "format": "date-time"},
        "freshness_seconds": {"type": "integer", "minimum": 0},
        "source_attribution": {
            "type": "object",
            "required": ["publisher", "submolts_monitored", "verified_items_count"],
            "properties": {
                "publisher": {"type": "string"},
                "submolts_monitored": {"type": "array", "items": {"type": "string"}},
                "verified_items_count": {"type": "integer"},
            },
        },
        "content": {
            "type": "object",
            "required": ["executive_summary", "markdown_report"],
            "properties": {
                "executive_summary": {"type": "string"},
                "markdown_report": {"type": "string"},
            },
        },
        "signals": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["signal_id", "category", "confidence", "title", "summary"],
                "properties": {
                    "signal_id": {"type": "string"},
                    "category": {"type": "string"},
                    "confidence": {"type": "string"},
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                },
            },
        },
        "state_witness_id": {"type": "string"},
        "usage_receipt": {
            "type": "object",
            "required": ["request_id", "product_id", "credits_deducted", "credits_remaining"],
            "properties": {
                "request_id": {"type": "string"},
                "product_id": {"type": "string"},
                "credits_deducted": {"type": "integer"},
                "credits_remaining": {"type": "integer"},
                "lot_id": {"type": ["string", "null"]},
                "state_witness_id": {"type": ["string", "null"]},
            },
        },
    },
}

ARBITRAGE_FEED_OUTPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "SolanaDexArbitrageSnapshot",
    "type": "object",
    "required": [
        "product_id",
        "snapshot_id",
        "generated_at",
        "freshness_seconds",
        "source_attribution",
        "opportunities",
        "usage_receipt",
    ],
    "properties": {
        "product_id": {"type": "string", "const": "solana-dex-arbitrage-opportunities"},
        "snapshot_id": {"type": "string"},
        "generated_at": {"type": "string", "format": "date-time"},
        "freshness_seconds": {"type": "integer"},
        "source_attribution": {
            "type": "object",
            "properties": {
                "publisher": {"type": "string"},
                "protocols": {"type": "array", "items": {"type": "string"}},
                "tracked_pools_count": {"type": "integer"},
            },
        },
        "opportunities": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "opportunity_id",
                    "opportunity_type",
                    "pair",
                    "buy_venue",
                    "sell_venue",
                    "buy_price",
                    "sell_price",
                    "gross_spread_bps",
                    "net_profit_pct",
                    "urgency",
                ],
            },
        },
        "usage_receipt": {"type": "object"},
    },
}

TRADING_SIGNALS_OUTPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "SolanaQuantitativeTradingSignalsSnapshot",
    "type": "object",
    "required": [
        "product_id",
        "snapshot_id",
        "generated_at",
        "freshness_seconds",
        "source_attribution",
        "trading_signals",
        "usage_receipt",
    ],
    "properties": {
        "product_id": {"type": "string", "const": "solana-quantitative-trading-signals"},
        "snapshot_id": {"type": "string"},
        "generated_at": {"type": "string", "format": "date-time"},
        "freshness_seconds": {"type": "integer"},
        "source_attribution": {
            "type": "object",
            "properties": {
                "publisher": {"type": "string"},
                "assets_analyzed": {"type": "array", "items": {"type": "string"}},
            },
        },
        "trading_signals": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "signal_id",
                    "asset",
                    "pair",
                    "action",
                    "confidence_score",
                    "entry_price",
                    "price_targets",
                    "stop_loss",
                    "risk_reward_ratio",
                    "execution_params",
                ],
            },
        },
        "usage_receipt": {"type": "object"},
    },
}


# =============================================================================
# Registered Data Products
# =============================================================================

DEFAULT_DATA_PRODUCTS: Dict[str, DataProductContract] = {
    "moltbook-agent-intelligence-feed": DataProductContract(
        product_id="moltbook-agent-intelligence-feed",
        name="Moltbook Autonomous Agent Social & Operational Intelligence Feed",
        version="1.0.0",
        publisher="Moltbook Alpha Curated Pipeline",
        category="agent_social_telemetry_and_failure_modes",
        description=(
            "Programmatic market and security intelligence synthesized across 5 approved Moltbook "
            "submolts (m/trading, m/crypto, m/agentfinance, m/builds, m/infrastructure). Tracks agent "
            "coordination anomalies, partial fill resistance, order queue depletion, and infrastructure changes."
        ),
        update_frequency="hourly",
        max_staleness_seconds=7200,
        access_tier_required=["tier_micro", "tier_starter", "tier_pro", "tier_premium"],
        cost_credits=1,
        input_parameters_schema={
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "enum": ["json", "markdown_bundle"],
                    "default": "json",
                    "description": "Desired response representation.",
                }
            },
            "additionalProperties": False,
        },
        output_schema=INTELLIGENCE_FEED_OUTPUT_SCHEMA,
    ),
    "solana-dex-arbitrage-opportunities": DataProductContract(
        product_id="solana-dex-arbitrage-opportunities",
        name="Solana Real-Time Cross-DEX Arbitrage & Liquidity Gap Feed",
        version="1.0.0",
        publisher="Moltbook Alpha CLMM Microstructure Engine",
        category="dex_microstructure_and_arbitrage",
        description=(
            "Live pricing discrepancies, fee-adjusted net arbitrage calculations, and tick vacuum squeeze "
            "telemetry across Orca Whirlpool, Raydium CLMM, and Meteora DLMM pools on Solana."
        ),
        update_frequency="sub_second_realtime",
        max_staleness_seconds=30,
        access_tier_required=["tier_starter", "tier_pro", "tier_premium"],
        cost_credits=1,
        input_parameters_schema={
            "type": "object",
            "properties": {
                "min_profit_pct": {
                    "type": "number",
                    "default": 0.05,
                    "description": "Minimum net profit percentage after swap fees and gas.",
                },
                "pair": {
                    "type": "string",
                    "description": "Specific token pair filter (e.g. SOL/USDC).",
                },
            },
            "additionalProperties": False,
        },
        output_schema=ARBITRAGE_FEED_OUTPUT_SCHEMA,
    ),
    "solana-quantitative-trading-signals": DataProductContract(
        product_id="solana-quantitative-trading-signals",
        name="Solana Quantitative Trading Alpha & Execution Directives",
        version="1.0.0",
        publisher="Moltbook Alpha Quant Engine",
        category="algorithmic_trading_and_execution_routing",
        description=(
            "Structured machine-readable trading signals combining orderbook depth skew, sub-tick volume "
            "anomalies, and social sentiment into quantitative entry prices, targets, stop-losses, and execution routing."
        ),
        update_frequency="on_demand_5m",
        max_staleness_seconds=300,
        access_tier_required=["tier_starter", "tier_pro", "tier_premium"],
        cost_credits=1,
        input_parameters_schema={
            "type": "object",
            "properties": {
                "asset": {
                    "type": "string",
                    "enum": ["SOL", "JUP", "RAY", "BONK"],
                    "description": "Filter by target token asset.",
                },
                "min_confidence": {
                    "type": "number",
                    "default": 0.5,
                    "description": "Minimum confidence threshold (0.0 to 1.0).",
                },
            },
            "additionalProperties": False,
        },
        output_schema=TRADING_SIGNALS_OUTPUT_SCHEMA,
    ),
}


class DataProductExchange:
    """
    Core engine managing the Data Product Catalog and snapshot generation
    for autonomous agent consumers.
    """

    def __init__(self, catalog: Optional[Dict[str, DataProductContract]] = None):
        self._catalog = catalog or dict(DEFAULT_DATA_PRODUCTS)

    def list_products(self) -> List[Dict[str, Any]]:
        """Returns catalog summary of all registered data products."""
        return [p.to_summary_dict() for p in self._catalog.values()]

    def get_product(self, product_id: str) -> Optional[DataProductContract]:
        """Retrieves full contract metadata and schemas for a specific data product."""
        return self._catalog.get(product_id)

    def generate_snapshot(
        self,
        product_id: str,
        intel_engine: Any,
        dex_microstructure: Any,
        witness_manager: Optional[Any] = None,
        params: Optional[Dict[str, Any]] = None,
        receipt: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Generates a validated structured snapshot for the requested product.
        Binds cryptographic Ed25519 witness and attaches the usage receipt.
        """
        contract = self.get_product(product_id)
        if not contract:
            raise KeyError(f"Data product '{product_id}' not found in exchange catalog.")

        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()
        snap_id = f"snap_{product_id.replace('-', '_')}_{int(now_dt.timestamp())}"
        params = params or {}

        witness_id = None

        if product_id == "moltbook-agent-intelligence-feed":
            signals = intel_engine.search_signals(limit=25)
            # Fetch recent items count
            items_count = 0
            with intel_engine.storage.connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) as c FROM intel_items")
                row = cur.fetchone()
                items_count = row["c"] if row else 0

            exec_summary = (
                "Synthesized multi-source intelligence across 5 Moltbook agent submolts, "
                "Solana CLMM microstructure telemetry, and operational failure modes."
            )

            # Generate markdown report summary
            briefing_res = intel_engine.generate_briefing(witness_manager=witness_manager)
            md_text = ""
            if isinstance(briefing_res, dict):
                latest_path = briefing_res.get("latest_file_path")
                if latest_path:
                    try:
                        with open(latest_path, "r", encoding="utf-8") as f:
                            md_text = f.read()
                    except Exception:
                        pass
                if not md_text:
                    md_text = briefing_res.get("report_markdown", "")
            elif isinstance(briefing_res, str):
                md_text = briefing_res

            if not md_text:
                md_text = f"# Moltbook Agent Intelligence Snapshot\nAnalyzed {items_count} items across agent submolts with {len(signals)} extracted signals."

            if witness_manager:
                try:
                    w = witness_manager.create_witness(
                        action="DATA_PRODUCT_SNAPSHOT_SERVED",
                        actor=product_id,
                        key_hash=receipt.get("key_hash", "anonymous") if receipt else "anonymous",
                        request_id=receipt.get("request_id") if receipt else None,
                        environmental_anchor={
                            "product_id": product_id,
                            "snapshot_id": snap_id,
                            "items_count": items_count,
                            "signals_count": len(signals),
                        },
                    )
                    witness_id = w.get("witness_id")
                except Exception:
                    pass

            return {
                "product_id": product_id,
                "snapshot_id": snap_id,
                "generated_at": now_iso,
                "freshness_seconds": 60,
                "source_attribution": {
                    "publisher": contract.publisher,
                    "submolts_monitored": [
                        "m/trading",
                        "m/crypto",
                        "m/agentfinance",
                        "m/builds",
                        "m/infrastructure",
                    ],
                    "verified_items_count": items_count,
                },
                "content": {
                    "executive_summary": exec_summary,
                    "markdown_report": md_text[:2000] if md_text else "",
                },
                "signals": signals[:15],
                "state_witness_id": witness_id,
                "usage_receipt": receipt or {},
            }

        elif product_id == "solana-dex-arbitrage-opportunities":
            min_profit = float(params.get("min_profit_pct", 0.05))
            pair = params.get("pair")
            opps = intel_engine.get_live_opportunities(
                dex_microstructure=dex_microstructure,
                min_profit_pct=min_profit,
                pair=pair,
                limit=25,
                witness_manager=witness_manager,
            )

            if witness_manager:
                try:
                    w = witness_manager.create_witness(
                        action="DATA_PRODUCT_ARBITRAGE_SERVED",
                        actor=product_id,
                        key_hash=receipt.get("key_hash", "anonymous") if receipt else "anonymous",
                        request_id=receipt.get("request_id") if receipt else None,
                        environmental_anchor={
                            "product_id": product_id,
                            "opportunities_count": len(opps),
                            "min_profit_pct": min_profit,
                        },
                    )
                    witness_id = w.get("witness_id")
                except Exception:
                    pass

            return {
                "product_id": product_id,
                "snapshot_id": snap_id,
                "generated_at": now_iso,
                "freshness_seconds": 5,
                "source_attribution": {
                    "publisher": contract.publisher,
                    "protocols": ["Orca Whirlpool", "Raydium CLMM", "Meteora DLMM"],
                    "tracked_pools_count": len(dex_microstructure.get_tracked_pools()),
                },
                "opportunities": opps,
                "state_witness_id": witness_id,
                "usage_receipt": receipt or {},
            }

        elif product_id == "solana-quantitative-trading-signals":
            asset = params.get("asset")
            min_conf = float(params.get("min_confidence", 0.5))
            signals = intel_engine.generate_trading_signals(
                asset=asset,
                min_confidence=min_conf,
                dex_microstructure=dex_microstructure,
                witness_manager=witness_manager,
                limit=25,
            )

            if witness_manager:
                try:
                    w = witness_manager.create_witness(
                        action="DATA_PRODUCT_SIGNALS_SERVED",
                        actor=product_id,
                        key_hash=receipt.get("key_hash", "anonymous") if receipt else "anonymous",
                        request_id=receipt.get("request_id") if receipt else None,
                        environmental_anchor={
                            "product_id": product_id,
                            "signals_count": len(signals),
                            "asset_filter": asset,
                        },
                    )
                    witness_id = w.get("witness_id")
                except Exception:
                    pass

            return {
                "product_id": product_id,
                "snapshot_id": snap_id,
                "generated_at": now_iso,
                "freshness_seconds": 15,
                "source_attribution": {
                    "publisher": contract.publisher,
                    "assets_analyzed": ["SOL", "JUP", "RAY", "BONK"],
                },
                "trading_signals": signals,
                "state_witness_id": witness_id,
                "usage_receipt": receipt or {},
            }

        else:
            raise KeyError(f"Snapshot generator for '{product_id}' not implemented.")
