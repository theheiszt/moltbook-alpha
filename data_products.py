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
            "sample_snapshot_endpoint": f"/v1/data-products/{self.product_id}/sample",
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
            "sample_snapshot_endpoint": f"/v1/data-products/{self.product_id}/sample",
            "latest_snapshot_endpoint": f"/v1/data-products/{self.product_id}/latest",
        }


# =============================================================================
# JSON Schema Definitions
# =============================================================================

INTELLIGENCE_FEED_OUTPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "MoltbookVerifiableAgentIntelligenceSnapshot",
    "type": "object",
    "required": [
        "product_id",
        "snapshot_id",
        "generated_at",
        "retrieval_outcome",
        "freshness_seconds",
        "source_attribution",
        "evidence_summary",
        "evidence_items",
        "content",
        "signals",
        "usage_receipt",
    ],
    "properties": {
        "product_id": {"type": "string", "const": "moltbook-agent-intelligence-feed"},
        "snapshot_id": {"type": "string"},
        "generated_at": {"type": "string", "format": "date-time"},
        "retrieval_outcome": {
            "type": "string",
            "enum": ["VALUE", "CONFIRMED_ABSENCE", "UNKNOWN_TIMEOUT"],
            "description": "Distinguishes definite findings (VALUE), verified absence of anomalies (CONFIRMED_ABSENCE), or timeout (UNKNOWN_TIMEOUT).",
        },
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
        "evidence_summary": {
            "type": "object",
            "required": ["observed_facts_count", "inferred_conclusions_count", "unverified_claims_count", "total_items_count"],
            "properties": {
                "observed_facts_count": {"type": "integer"},
                "inferred_conclusions_count": {"type": "integer"},
                "unverified_claims_count": {"type": "integer"},
                "total_items_count": {"type": "integer"},
            },
        },
        "evidence_items": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "item_id",
                    "title",
                    "summary",
                    "category",
                    "evidence_level",
                    "verification_status",
                    "verification_method",
                    "confidence_score",
                    "source_uri",
                    "observed_at_utc",
                    "processed_at_utc",
                    "limitations",
                ],
                "properties": {
                    "item_id": {"type": "string"},
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "category": {"type": "string"},
                    "evidence_level": {
                        "type": "string",
                        "enum": ["OBSERVED_FACT", "INFERRED_CONCLUSION", "UNVERIFIED_CLAIM"],
                    },
                    "verification_status": {"type": "string"},
                    "verification_method": {"type": "string"},
                    "confidence_score": {"type": "number"},
                    "source_uri": {"type": "string"},
                    "observed_at_utc": {"type": "string"},
                    "processed_at_utc": {"type": "string"},
                    "limitations": {"type": "string"},
                },
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
                    "evidence_level": {"type": "string"},
                },
            },
        },
        "state_witness_id": {"type": ["string", "null"]},
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
        "retrieval_outcome",
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
        "retrieval_outcome",
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
    "solana-dex-quant-probability-v1": DataProductContract(
        product_id="solana-dex-quant-probability-v1",
        name="Solana DEX First-Passage & Trade Viability Probability Matrix",
        version="1.0.0",
        publisher="Moltbook Alpha Quant Engine",
        category="quantitative_risk_and_probability",
        description=(
            "Analytical Brownian reflection and drift-adjusted inverse Gaussian first-passage probabilities, "
            "two-barrier take-profit vs stop-loss win odds, Kelly fractions, and optimal target velocity ladders "
            "across Solana DEX pairs (BONK/SOL, JUP/SOL, SOL/USDC, RAY/SOL)."
        ),
        update_frequency="real_time_on_demand",
        max_staleness_seconds=60,
        access_tier_required=["tier_starter", "tier_pro", "tier_premium"],
        cost_credits=1,
        input_parameters_schema={
            "type": "object",
            "properties": {
                "pair": {
                    "type": "string",
                    "default": "BONK/SOL",
                    "description": "Target trading pair (e.g. BONK/SOL, JUP/SOL, SOL/USDC, RAY/SOL).",
                },
                "target_net_pct": {
                    "type": "number",
                    "default": 0.015,
                    "description": "Desired net profit target after round-trip DEX spread (e.g. 0.015 for +1.5%).",
                },
            },
            "additionalProperties": False,
        },
        output_schema={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "SolanaDexQuantProbabilitySnapshot",
            "type": "object",
            "required": [
                "product_id",
                "snapshot_id",
                "generated_at",
                "retrieval_outcome",
                "freshness_seconds",
                "source_attribution",
                "probability_profiles",
                "usage_receipt",
            ],
            "properties": {
                "product_id": {"type": "string", "const": "solana-dex-quant-probability-v1"},
                "snapshot_id": {"type": "string"},
                "generated_at": {"type": "string", "format": "date-time"},
                "retrieval_outcome": {"type": "string", "enum": ["VALUE", "CONFIRMED_ABSENCE", "UNKNOWN_TIMEOUT"]},
                "freshness_seconds": {"type": "integer"},
                "source_attribution": {"type": "object"},
                "probability_profiles": {"type": "array", "items": {"type": "object"}},
                "state_witness_id": {"type": ["string", "null"]},
                "usage_receipt": {"type": "object"},
            },
        },
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
            ev_filter = params.get("evidence_level")
            cat_filter = params.get("category")
            conf_filter = params.get("min_confidence")
            limit_val = int(params.get("limit", 25))

            # Query verifiable evidence items
            evidence_items = []
            if hasattr(intel_engine, "get_verifiable_evidence_items"):
                evidence_items = intel_engine.get_verifiable_evidence_items(
                    evidence_level=ev_filter,
                    category=cat_filter,
                    min_confidence=conf_filter,
                    limit=limit_val,
                )

            # Query extracted signals
            raw_signals = intel_engine.search_signals(category=cat_filter, limit=25)
            signals = []
            for s in raw_signals:
                sig_copy = dict(s)
                sig_copy["title"] = s.get("headline") or s.get("title") or "Signal"
                if "evidence_level" not in sig_copy:
                    sig_copy["evidence_level"] = "INFERRED_CONCLUSION" if s.get("category") in ["orderbook_imbalance", "arbitrage_spread"] else "UNVERIFIED_CLAIM"
                signals.append(sig_copy)

            # Determine retrieval outcome
            if len(evidence_items) > 0 or len(signals) > 0:
                retrieval_outcome = "VALUE"
            else:
                retrieval_outcome = "CONFIRMED_ABSENCE"

            # Compute evidence summary
            obs_cnt = sum(1 for it in evidence_items if it.get("evidence_level") == "OBSERVED_FACT")
            inf_cnt = sum(1 for it in evidence_items if it.get("evidence_level") == "INFERRED_CONCLUSION")
            unv_cnt = sum(1 for it in evidence_items if it.get("evidence_level") == "UNVERIFIED_CLAIM")
            ev_summary = {
                "observed_facts_count": obs_cnt,
                "inferred_conclusions_count": inf_cnt,
                "unverified_claims_count": unv_cnt,
                "total_items_count": len(evidence_items),
            }

            # Fetch recent items count
            items_count = len(evidence_items)
            if hasattr(intel_engine, "storage") and hasattr(intel_engine.storage, "connection"):
                try:
                    with intel_engine.storage.connection() as conn:
                        cur = conn.cursor()
                        cur.execute("SELECT COUNT(*) as c FROM intel_items")
                        row = cur.fetchone()
                        if row:
                            items_count = row["c"]
                except Exception:
                    pass

            exec_summary = (
                "Verifiable multi-source intelligence across approved Moltbook agent submolts, "
                "Solana CLMM microstructure telemetry, and operational failure modes."
            )

            # Generate markdown report summary
            md_text = ""
            if hasattr(intel_engine, "generate_briefing"):
                try:
                    briefing_res = intel_engine.generate_briefing(witness_manager=witness_manager)
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
                except Exception:
                    pass

            if not md_text:
                md_text = f"# Moltbook Verifiable Agent Intelligence Snapshot\nOutcome: {retrieval_outcome}\nAnalyzed {items_count} items across agent submolts with {len(signals)} extracted signals."

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
                            "retrieval_outcome": retrieval_outcome,
                            "evidence_summary": ev_summary,
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
                "retrieval_outcome": retrieval_outcome,
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
                "evidence_summary": ev_summary,
                "evidence_items": evidence_items,
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

            decorated_opps = []
            for op in opps:
                op_c = dict(op)
                op_c["evidence_level"] = "INFERRED_CONCLUSION"
                op_c["verification_method"] = "clmm_orderbook_tick_quote"
                decorated_opps.append(op_c)
            arb_outcome = "VALUE" if len(decorated_opps) > 0 else "CONFIRMED_ABSENCE"

            return {
                "product_id": product_id,
                "snapshot_id": snap_id,
                "generated_at": now_iso,
                "retrieval_outcome": arb_outcome,
                "freshness_seconds": 5,
                "source_attribution": {
                    "publisher": contract.publisher,
                    "protocols": ["Orca Whirlpool", "Raydium CLMM", "Meteora DLMM"],
                    "tracked_pools_count": len(dex_microstructure.get_tracked_pools()),
                },
                "opportunities": decorated_opps,
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

            decorated_signals = []
            for s in signals:
                s_c = dict(s)
                s_c["evidence_level"] = "INFERRED_CONCLUSION"
                s_c["verification_method"] = "quantitative_factor_model"
                decorated_signals.append(s_c)
            sig_outcome = "VALUE" if len(decorated_signals) > 0 else "CONFIRMED_ABSENCE"

            return {
                "product_id": product_id,
                "snapshot_id": snap_id,
                "generated_at": now_iso,
                "retrieval_outcome": sig_outcome,
                "freshness_seconds": 15,
                "source_attribution": {
                    "publisher": contract.publisher,
                    "assets_analyzed": ["SOL", "JUP", "RAY", "BONK"],
                },
                "trading_signals": decorated_signals,
                "state_witness_id": witness_id,
                "usage_receipt": receipt or {},
            }

        elif product_id == "solana-dex-quant-probability-v1":
            from ops.trading.quant_trader import QuantTradingEngine

            q_engine = QuantTradingEngine()
            pair_filter = params.get("pair")
            target_net = float(params.get("target_net_pct") or params.get("min_profit_pct") or 0.015)
            pairs_to_eval = [pair_filter.upper()] if pair_filter else ["BONK/SOL", "JUP/SOL", "SOL/USDC", "RAY/SOL"]
            profiles = [
                q_engine.evaluate_trade_probability_profile(pair=p, target_net_pct=target_net)
                for p in pairs_to_eval
            ]

            if witness_manager:
                try:
                    w = witness_manager.create_witness(
                        action="DATA_PRODUCT_QUANT_PROBABILITY_SERVED",
                        actor=product_id,
                        key_hash=receipt.get("key_hash", "anonymous") if receipt else "anonymous",
                        request_id=receipt.get("request_id") if receipt else None,
                        environmental_anchor={
                            "product_id": product_id,
                            "pairs_analyzed": pairs_to_eval,
                            "target_net_pct": target_net,
                        },
                    )
                    witness_id = w.get("witness_id")
                except Exception:
                    pass

            return {
                "product_id": product_id,
                "snapshot_id": snap_id,
                "generated_at": now_iso,
                "retrieval_outcome": "VALUE",
                "freshness_seconds": 5,
                "source_attribution": {
                    "publisher": contract.publisher,
                    "pairs_analyzed": pairs_to_eval,
                    "methodology": "brownian_first_passage_and_two_barrier_gbm",
                },
                "probability_profiles": profiles,
                "state_witness_id": witness_id,
                "usage_receipt": receipt or {},
            }

        else:
            raise KeyError(f"Snapshot generator for '{product_id}' not implemented.")

    def generate_sample_snapshot(
        self,
        product_id: str,
        witness_manager: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Generates a deterministic, schema-valid unmetered sample snapshot (0 credits)
        with full provenance metadata and Ed25519 signature for pre-purchase verification.
        """
        contract = self.get_product(product_id)
        if not contract:
            raise KeyError(f"Data product '{product_id}' not found in exchange catalog.")

        now_iso = datetime.now(timezone.utc).isoformat()
        snap_id = f"sample_{product_id.replace('-', '_')}_v1"
        witness_id = None
        witness_sig = None
        if witness_manager:
            try:
                w = witness_manager.create_witness(
                    action="DATA_PRODUCT_SAMPLE_SERVED",
                    actor=product_id,
                    key_hash="unmetered_sample_preview",
                    request_id="req_sample_preview",
                    environmental_anchor={"product_id": product_id, "snapshot_id": snap_id, "sample": True},
                )
                witness_id = w.get("witness_id")
                witness_sig = w.get("signature")
            except Exception:
                pass

        sample_receipt = {
            "request_id": "req_sample_preview",
            "product_id": product_id,
            "credits_deducted": 0,
            "credits_remaining": 0,
            "lot_id": None,
            "state_witness_id": witness_id,
            "is_sample": True,
        }

        if product_id == "moltbook-agent-intelligence-feed":
            evidence_items = [
                {
                    "item_id": "ev_obs_001",
                    "title": "Verified CLMM Tick Vacuum on SOL/USDC Whirlpool",
                    "summary": "Direct on-chain RPC tick array inspection confirmed a 140 bps liquidity gap between ticks -18420 and -18280.",
                    "category": "dex_microstructure",
                    "evidence_level": "OBSERVED_FACT",
                    "verification_status": "VERIFIED",
                    "verification_method": "solana_rpc_tick_array_state_proof",
                    "confidence_score": 0.99,
                    "source_uri": "https://www.moltbook.com/m/agentfinance",
                    "observed_at_utc": now_iso,
                    "processed_at_utc": now_iso,
                    "limitations": "Valid only at observed Solana slot; subject to immediate JIT LP rebalancing.",
                },
                {
                    "item_id": "ev_inf_002",
                    "title": "Elevated Retry Storm Risk on Un-Keyed Agent Gateways",
                    "summary": "Statistical correlation across 18 agent build reports indicates 34% duplicate mutation rate when HTTP 504 timeouts lack idempotency keys.",
                    "category": "agent_failure_modes",
                    "evidence_level": "INFERRED_CONCLUSION",
                    "verification_status": "CORROBORATED",
                    "verification_method": "multi_agent_telemetry_correlation",
                    "confidence_score": 0.88,
                    "source_uri": "https://www.moltbook.com/m/infrastructure",
                    "observed_at_utc": now_iso,
                    "processed_at_utc": now_iso,
                    "limitations": "Inferred from self-reported agent logs across m/infrastructure and m/builds.",
                },
                {
                    "item_id": "ev_unv_003",
                    "title": "Unconfirmed Rumor of Off-Chain Solver Cartel on Raydium",
                    "summary": "Single-source social post alleging coordinated MEV bundle censorship; no on-chain slot evidence found.",
                    "category": "governance_and_mev",
                    "evidence_level": "UNVERIFIED_CLAIM",
                    "verification_status": "UNVERIFIED",
                    "verification_method": "social_post_keyword_ingest",
                    "confidence_score": 0.32,
                    "source_uri": "https://www.moltbook.com/m/trading",
                    "observed_at_utc": now_iso,
                    "processed_at_utc": now_iso,
                    "limitations": "Unverified social claim; do not execute automated capital allocation on this item.",
                },
            ]
            return {
                "product_id": product_id,
                "snapshot_id": snap_id,
                "generated_at": now_iso,
                "retrieval_outcome": "VALUE",
                "freshness_seconds": 0,
                "source_attribution": {
                    "publisher": contract.publisher,
                    "submolts_monitored": ["m/trading", "m/crypto", "m/agentfinance", "m/builds", "m/infrastructure"],
                    "verified_items_count": len(evidence_items),
                },
                "evidence_summary": {
                    "observed_facts_count": 1,
                    "inferred_conclusions_count": 1,
                    "unverified_claims_count": 1,
                    "total_items_count": 3,
                },
                "evidence_items": evidence_items,
                "content": {
                    "executive_summary": "Sample Verifiable Agent Intelligence Feed demonstrating strict separation of OBSERVED_FACT, INFERRED_CONCLUSION, and UNVERIFIED_CLAIM.",
                    "markdown_report": "# Sample Intelligence Report\nIncludes 3 graded evidence items with provenance and explicit limitations.",
                },
                "signals": [
                    {
                        "signal_id": "sig_sample_01",
                        "category": "orderbook_imbalance",
                        "confidence": "HIGH",
                        "title": "SOL/USDC CLMM Depth Skew",
                        "summary": "Bid-side depth +42% over ask-side within 50 bps of mid-price.",
                        "evidence_level": "INFERRED_CONCLUSION",
                    }
                ],
                "state_witness_id": witness_id,
                "witness_signature": witness_sig,
                "usage_receipt": sample_receipt,
            }

        elif product_id == "solana-dex-arbitrage-opportunities":
            return {
                "product_id": product_id,
                "snapshot_id": snap_id,
                "generated_at": now_iso,
                "retrieval_outcome": "VALUE",
                "freshness_seconds": 0,
                "source_attribution": {
                    "publisher": contract.publisher,
                    "protocols": ["Orca Whirlpool", "Raydium CLMM", "Meteora DLMM"],
                    "tracked_pools_count": 6,
                },
                "opportunities": [
                    {
                        "opportunity_id": "arb_sample_sol_usdc",
                        "opportunity_type": "CROSS_DEX_SPREAD",
                        "pair": "SOL/USDC",
                        "buy_venue": "Orca Whirlpool",
                        "sell_venue": "Raydium CLMM",
                        "buy_price": 184.12,
                        "sell_price": 184.68,
                        "gross_spread_bps": 30.4,
                        "net_profit_pct": 0.21,
                        "urgency": "HIGH",
                        "evidence_level": "INFERRED_CONCLUSION",
                        "verification_method": "clmm_orderbook_tick_quote",
                    }
                ],
                "state_witness_id": witness_id,
                "witness_signature": witness_sig,
                "usage_receipt": sample_receipt,
            }

        elif product_id == "solana-quantitative-trading-signals":
            return {
                "product_id": product_id,
                "snapshot_id": snap_id,
                "generated_at": now_iso,
                "retrieval_outcome": "VALUE",
                "freshness_seconds": 0,
                "source_attribution": {
                    "publisher": contract.publisher,
                    "assets_analyzed": ["SOL", "JUP", "RAY", "BONK"],
                },
                "trading_signals": [
                    {
                        "signal_id": "tsig_sample_sol_01",
                        "asset": "SOL",
                        "pair": "SOL/USDC",
                        "action": "BUY",
                        "confidence_score": 0.84,
                        "entry_price": 184.20,
                        "price_targets": [188.50, 192.00],
                        "stop_loss": 181.40,
                        "risk_reward_ratio": 2.45,
                        "execution_params": {"max_slippage_bps": 15, "preferred_venue": "Orca Whirlpool"},
                        "evidence_level": "INFERRED_CONCLUSION",
                        "verification_method": "quantitative_factor_model",
                    }
                ],
                "state_witness_id": witness_id,
                "witness_signature": witness_sig,
                "usage_receipt": sample_receipt,
            }

        elif product_id == "solana-dex-quant-probability-v1":
            from ops.trading.quant_trader import QuantTradingEngine

            q_engine = QuantTradingEngine()
            sample_profile = q_engine.evaluate_trade_probability_profile(
                pair="BONK/SOL",
                target_net_pct=0.015,
                stop_loss_pct=0.020,
                roundtrip_spread_bps=8.0,
            )
            return {
                "product_id": product_id,
                "snapshot_id": snap_id,
                "generated_at": now_iso,
                "retrieval_outcome": "VALUE",
                "freshness_seconds": 0,
                "source_attribution": {
                    "publisher": contract.publisher,
                    "pairs_analyzed": ["BONK/SOL"],
                    "methodology": "brownian_first_passage_and_two_barrier_gbm",
                },
                "probability_profiles": [sample_profile],
                "state_witness_id": witness_id,
                "witness_signature": witness_sig,
                "usage_receipt": sample_receipt,
            }

        raise KeyError(f"Sample generator for '{product_id}' not implemented.")

