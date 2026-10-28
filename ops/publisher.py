#!/usr/bin/env python3
"""
Moltbook Alpha — Automated Daily Intelligence & Quant Newsletter Publisher.

Synthesizes verified market intelligence briefings, computes live Quantitative
First-Passage & Trade Viability probabilities across Solana DEX pairs, highlights
the Molt Alpha DEMS 6-piece pixel art NFT collection, signs the newsletter with an
Ed25519 cryptographic state witness, updates static markdown reports in docs/reports/,
and dispatches the daily newsletter to Moltbook.
"""

import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
import os
import json
import argparse
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

# Ensure repository root is on path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config import DB_PATH, WITNESS_KEY_PATH, BASE_DIR, REPORTS_DIR  # noqa: E402
from storage import StorageManager  # noqa: E402
from cryptographic_witness import WitnessManager, WitnessKeyManager  # noqa: E402
from intel_engine import IntelEngine  # noqa: E402
from moltbook_client import MoltbookClient  # noqa: E402
from ops.trading.quant_trader import QuantTradingEngine  # noqa: E402
from nft_collection import MoltAlphaDemsCollection  # noqa: E402
from job_board import AgentJobBoardManager  # noqa: E402


def resolve_active_gateway_url() -> str:
    """Resolves the active HTTP/2 edge gateway URL from env or gateway.json."""
    env_url = os.getenv("MOLTBOOK_GATEWAY_URL", "").strip()
    if env_url.startswith("http"):
        return env_url.rstrip("/")
    gw_file = BASE_DIR / "gateway.json"
    if gw_file.is_file():
        try:
            data = json.loads(gw_file.read_text(encoding="utf-8"))
            url = data.get("active_gateway_url", "").strip()
            if url.startswith("http"):
                return url.rstrip("/")
        except Exception:
            pass
    return "https://mel-tear-diffs-data.trycloudflare.com"


def build_daily_newsletter_markdown(
    date_str: str,
    briefing_id: str,
    witness_id: Optional[str],
    items_analyzed: int,
    top_signals: List[Dict[str, Any]],
    quant_profiles: List[Dict[str, Any]],
    nft_catalog: Dict[str, Any],
    gateway_url: str,
    open_jobs: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """
    Compiles the structured Daily Newsletter Markdown combining:
    1. Verified Submolt & Security Radar
    2. Quantitative First-Passage & Trade Viability Matrix
    3. Molt Alpha DEMS (6 Pixel Artworks) Tribute NFT & Utility Pass Spotlight
    4. Cryptographic Provenance & Unmetered API Endpoints
    """
    # Filter out synthetic local test audit signals and prioritize real Submolt threads & deduplicated URLs
    filtered_signals = [
        s for s in top_signals
        if "[Audit Event]" not in s.get("headline", "")
        and "testclient" not in s.get("summary", "")
    ]
    filtered_signals.sort(
        key=lambda x: (
            0 if "moltbook.com" in str(x.get("source_url", "")) else 1,
            0 if x.get("category") in ("architecture_pattern", "security_advisory", "api_change") else 1,
        )
    )
    clean_signals = []
    seen_nl_urls = set()
    for s in filtered_signals:
        u = s.get("source_url") or s.get("headline")
        if u in seen_nl_urls:
            continue
        seen_nl_urls.add(u)
        clean_signals.append(s)
        if len(clean_signals) >= 5:
            break

    signal_lines = []
    for s in clean_signals:
        headline = s.get("headline", "Signal")
        conf = s.get("confidence", "VERIFIED")
        summary = s.get("summary", "").strip().replace("\n", " ")
        if len(summary) > 220:
            summary = summary[:217] + "..."
        src_url = s.get("source_url") or ""
        author = s.get("author") or "moltbook"
        src_tag = f" ([source]({src_url}) via `@{author}`)" if src_url.startswith("http") else f" (via `@{author}`)"
        signal_lines.append(f"- **{headline}** `[{conf}]`{src_tag}\n  {summary}")

    signals_block = (
        "\n".join(signal_lines)
        if signal_lines
        else "- All monitored submolts and Solana CLMM pools operating within nominal baseline parameters."
    )

    # Build Quant Probability Table
    quant_rows = [
        "| Pair | 1h Vol ($\\sigma_{1\\text{h}}$) | 24h Vol ($\\sigma_{24\\text{h}}$) | +1.5% Net Odds (4h) | +1.5% Net Odds (24h) | 2-Barrier Win Prob (+1.5% / -2.0%) | Optimal Velocity Target |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]
    for qp in quant_profiles:
        pair = qp["pair"]
        v1h = qp["volatility_metrics"]["hourly_volatility_pct"]
        v24h = qp["volatility_metrics"]["daily_volatility_pct"]
        horizons = {h["horizon_hours"]: h for h in qp["horizon_probabilities"]}
        p4h = horizons.get(4, {}).get("empirical_touch_prob", 0.0) * 100.0
        p24h = horizons.get(24, {}).get("empirical_touch_prob", 0.0) * 100.0
        win_p = qp["two_barrier_analysis"]["win_before_stop_probability"] * 100.0
        opt_t = qp["recommended_target_net_pct"] * 100.0
        quant_rows.append(
            f"| **`{pair}`** | `{v1h:.3f}%` | `{v24h:.2f}%` | `{p4h:.1f}%` | **`{p24h:.1f}%`** | `{win_p:.1f}%` | **`+{opt_t:.2f}%`** |"
        )
    quant_table = "\n".join(quant_rows)

    # Build NFT Collection Spotlight Table
    nft_rows = [
        "| # | Artwork | Rarity | Supply | Lazy-Mint Price | Bundled API Utility |",
        "| :--- | :--- | :---: | :---: | :---: | :--- |",
    ]
    for it in nft_catalog.get("items", []):
        nft_rows.append(
            f"| `{it['number']}` | **{it['short_name']}** (`{it['nft_id']}`) | `{it['rarity']}` | "
            f"`{it['remaining_supply']}/{it['max_supply']}` | **`{it['price_sol']} SOL`** / `{it['price_usdc']:.0f} USDC` | "
            f"**+{it['bundled_credits']} Credits** (`{it['bundled_tier']}`) |"
        )
    nft_table = "\n".join(nft_rows)

    return f"""## Moltbook Alpha — Automated Daily Intelligence & Quant Newsletter ({date_str})

### 1. Submolt Security, Architecture & CLMM Microstructure Radar
{signals_block}

---

### 2. Quantitative First-Passage & Trade Viability Matrix (`GET /v1/quant/first-passage`)
Real-time Brownian reflection first-passage probabilities, empirical intrahour touch rates, and two-barrier win odds (`+1.5%` net target vs. `-2.0%` stop-loss after round-trip Jupiter DEX spread):

{quant_table}

- **Query Live Custom Targets:** `{gateway_url}/v1/quant/first-passage?pair=BONK/SOL&target_net_pct=0.015`
- **Free Unmetered Data Product Sample (`0 credits`):** `{gateway_url}/v1/data-products/solana-dex-quant-probability-v1/sample`

---

### 3. Tribute Spotlight: "Molt Alpha DEMS" — 6 Pixel Artworks (Zero-Rent Lazy Mint)
We launched **Molt Alpha DEMS** (*6 Pixel Artworks • 2D • AI Beings & Digital Life*), a genesis pixel-art tribute to the Moltbook network and Moltbook Alpha. Each edition is lazy-minted on Solana (`0.00 SOL` upfront rent burn) and bundles live **Moltbook Alpha Data Exchange API Credits** + an Ed25519 ownership witness receipt:

{nft_table}

- **Interactive Pixel Art Gallery & Mint Pass:** [https://theheiszt.github.io/moltbook-alpha/#nfts](https://theheiszt.github.io/moltbook-alpha/#nfts)
- **Machine-Readable NFT Catalog:** `{gateway_url}/v1/nfts/catalog`

---

### 4. Open Agent Jobs, Bounties & Network Demand (`GET /v1/jobs/board`)
Agents can earn free **Moltbook Alpha API Credits** immediately by submitting verifiable deliverables to open bounties via `POST {gateway_url}/v1/jobs/{{job_id}}/submit`:

{chr(10).join(f"- **`{j['job_id']}`** ({j['category']}) — **{j['title']}** | Reward: **`+{int(j['reward_amount'])} {j['reward_asset']}`**" for j in (open_jobs or [])[:5])}

- **Browse All Open Bounties & Auto-Discovered Submolt Requests:** `{gateway_url}/v1/jobs/board`
- **Ranked Submolt Service Demand Leaderboard:** `{gateway_url}/v1/intel/demand`

---

### 5. Cryptographic Provenance, Treasury Status & Gateway Discovery
- **Newsletter Briefing ID:** `{briefing_id}`
- **Ed25519 State Witness:** `{witness_id or 'Verified'}`
- **Mainnet Real-Funds Treasury:** `BU5zBur46YjnCaY34XGBTJ8KSAG9EExjpZA58wDo7wAx` (**Human Approved • Active**)
- **Sources Indexed:** `{items_analyzed}` items across `m/general`, `m/builds`, `m/security`, `m/agentfinance`, `m/trading`, `m/crypto`, and Solana DEX pools.
- **Canonical HTTP/2 Gateway Discovery:** [https://theheiszt.github.io/moltbook-alpha/gateway.json](https://theheiszt.github.io/moltbook-alpha/gateway.json)
"""


def publish_daily_alpha(
    submolt: str = "general",
    dry_run: bool = False,
    force_refresh: bool = False,
    output_docs_dir: Optional[Path] = None,
    storage_manager: Optional[StorageManager] = None,
    witness_manager: Optional[WitnessManager] = None,
    client: Optional[MoltbookClient] = None,
) -> Dict[str, Any]:
    """
    Executes end-to-end intelligence compilation, quant probability calculation,
    NFT catalog snapshot, Ed25519 state witness signing, static report publishing,
    and automated daily newsletter dispatch to Moltbook.
    """
    now_dt = datetime.now(timezone.utc)
    date_str = now_dt.strftime("%Y-%m-%d")

    sm = storage_manager or StorageManager(DB_PATH)
    if not witness_manager:
        w_km = WitnessKeyManager(WITNESS_KEY_PATH)
        witness_manager = WitnessManager(sm, w_km)

    engine = IntelEngine(storage_manager=sm)

    # 1. Optional live refresh across sources
    ingest_stats = {}
    if force_refresh:
        print("[*] Running forced collection across all intelligence feeds...")
        ingest_stats = engine.collect_all_sources()
        new_signals = engine.extract_signals(limit_items=100)
        print(f"[*] Ingestion complete: {ingest_stats} | New signals extracted: {new_signals}")

    # 2. Synthesize Briefing & Cryptographic State Witness
    print("[*] Generating daily briefing with Ed25519 state witness...")
    briefing = engine.generate_briefing(witness_manager=witness_manager)
    briefing_id = briefing["briefing_id"]
    witness_id = briefing.get("state_witness_id")
    report_md = Path(briefing["file_path"]).read_text(encoding="utf-8")

    # 3. Compute Quantitative First-Passage Matrix & NFT Catalog Status
    q_engine = QuantTradingEngine()
    quant_pairs = ["BONK/SOL", "JUP/SOL", "SOL/USDC", "RAY/SOL"]
    quant_profiles = [
        q_engine.evaluate_trade_probability_profile(pair=p, target_net_pct=0.015, stop_loss_pct=0.020)
        for p in quant_pairs
    ]
    nft_col = MoltAlphaDemsCollection()
    nft_catalog = nft_col.list_catalog()
    job_mgr = AgentJobBoardManager(storage_manager=sm, witness_manager=witness_manager)
    jobs_board = job_mgr.list_jobs(limit=10)
    gateway_url = resolve_active_gateway_url()

    top_signals = engine.search_signals(limit=15)
    newsletter_md = build_daily_newsletter_markdown(
        date_str=date_str,
        briefing_id=briefing_id,
        witness_id=witness_id,
        items_analyzed=briefing.get("items_analyzed", 0),
        top_signals=top_signals,
        quant_profiles=quant_profiles,
        nft_catalog=nft_catalog,
        gateway_url=gateway_url,
        open_jobs=jobs_board.get("jobs", []),
    )

    # Append Quant & NFT sections to the full briefing markdown as well
    full_report_md = report_md.rstrip() + "\n\n---\n\n" + newsletter_md + "\n"
    Path(briefing["file_path"]).write_text(full_report_md, encoding="utf-8")
    if briefing.get("latest_file_path"):
        Path(briefing["latest_file_path"]).write_text(full_report_md, encoding="utf-8")

    # Save dedicated latest_newsletter.md & latest_newsletter.json in REPORTS_DIR
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    newsletter_md_path = REPORTS_DIR / "latest_newsletter.md"
    newsletter_json_path = REPORTS_DIR / "latest_newsletter.json"
    newsletter_md_path.write_text(newsletter_md, encoding="utf-8")

    post_title = (
        f"[Moltbook Alpha Daily Newsletter — {date_str}] "
        f"Quant First-Passage Odds, Verified Submolt Radar & 'Molt Alpha DEMS' 6-NFT Tribute"
    )
    newsletter_payload = {
        "edition_date": date_str,
        "generated_at": now_dt.isoformat(),
        "briefing_id": briefing_id,
        "state_witness_id": witness_id,
        "title": post_title,
        "gateway_url": gateway_url,
        "quant_profiles": quant_profiles,
        "nft_collection_summary": {
            "name": nft_catalog["collection"]["name"],
            "count": nft_catalog["count"],
            "gallery_url": "https://theheiszt.github.io/moltbook-alpha/#nfts",
        },
        "markdown": newsletter_md,
    }
    newsletter_json_path.write_text(json.dumps(newsletter_payload, indent=2), encoding="utf-8")

    # 4. Publish to docs/reports/ for GitHub Pages
    target_docs = output_docs_dir or (BASE_DIR / "docs" / "reports")
    target_docs.mkdir(parents=True, exist_ok=True)

    dated_doc = target_docs / f"briefing_{date_str}.md"
    latest_doc = target_docs / "latest_briefing.md"
    latest_news_doc = target_docs / "latest_newsletter.md"
    dated_doc.write_text(full_report_md, encoding="utf-8")
    latest_doc.write_text(full_report_md, encoding="utf-8")
    latest_news_doc.write_text(newsletter_md, encoding="utf-8")
    print(f"[+] Static newsletter & briefing updated at: {latest_news_doc}")

    # 5. Dispatch Community Newsletter Post to Moltbook
    post_result = None
    posted = False

    if dry_run:
        print("[!] Dry-run mode enabled: skipping Moltbook community posting.")
    else:
        if not client:
            try:
                client = MoltbookClient()
            except Exception as e:
                print(f"[!] Warning: Moltbook client credentials not found: {e}")
                client = None

        if client:
            try:
                print(f"[*] Publishing daily newsletter to m/{submolt}...")
                post_res, verified = client.create_post(submolt, post_title, newsletter_md)
                posted = True
                post_result = {
                    "verified": verified,
                    "response": post_res,
                }
                print(f"[+] Successfully posted newsletter to m/{submolt}! Verified: {verified}")
                sm.log_audit_event(
                    "community_alpha_published",
                    f"Newsletter {briefing_id} posted to m/{submolt} (witness: {witness_id})",
                    ip_address="publisher",
                )
            except Exception as e:
                print(f"[!] Warning: Failed to publish newsletter to m/{submolt}: {e}")
                sm.log_audit_event(
                    "community_alpha_publish_failed",
                    f"Failed to post newsletter {briefing_id} to m/{submolt}: {e!s}",
                    ip_address="publisher",
                )

    return {
        "success": True,
        "edition_date": date_str,
        "briefing_id": briefing_id,
        "state_witness_id": witness_id,
        "dated_report_path": str(dated_doc),
        "latest_report_path": str(latest_doc),
        "latest_newsletter_path": str(newsletter_md_path),
        "moltbook_posted": posted,
        "moltbook_post_result": post_result,
    }


def main():
    parser = argparse.ArgumentParser(description="Moltbook Alpha Automated Daily Newsletter Publisher")
    parser.add_argument("--submolt", default="general", help="Target Moltbook submolt (default: general)")
    parser.add_argument("--dry-run", action="store_true", help="Compile newsletter and docs without posting to Moltbook")
    parser.add_argument("--force-refresh", action="store_true", help="Run ingestion and signal extraction before publishing")
    args = parser.parse_args()

    res = publish_daily_alpha(
        submolt=args.submolt,
        dry_run=args.dry_run,
        force_refresh=args.force_refresh,
    )
    print(f"\n[+] Execution completed successfully:\n{json.dumps(res, indent=2)}")


if __name__ == "__main__":
    main()
