#!/usr/bin/env python3
"""
Moltbook Alpha — Automated Community Alpha Publisher & Report Dispatcher.
Synthesizes verified market intelligence briefings, signs them with an Ed25519
cryptographic state witness, publishes executive summaries to Moltbook m/builds,
and generates static markdown reports in docs/reports/ for GitHub Pages.
"""

import sys
import json
import argparse
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, Optional

# Ensure repository root is on path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config import DB_PATH, WITNESS_KEY_PATH, BASE_DIR  # noqa: E402
from storage import StorageManager  # noqa: E402
from cryptographic_witness import WitnessManager, WitnessKeyManager  # noqa: E402
from intel_engine import IntelEngine  # noqa: E402
from moltbook_client import MoltbookClient  # noqa: E402


def publish_daily_alpha(
    submolt: str = "builds",
    dry_run: bool = False,
    force_refresh: bool = False,
    output_docs_dir: Optional[Path] = None,
    storage_manager: Optional[StorageManager] = None,
    witness_manager: Optional[WitnessManager] = None,
    client: Optional[MoltbookClient] = None,
) -> Dict[str, Any]:
    """
    Executes end-to-end intelligence compilation, state witness signing,
    static report publishing to docs/reports/, and community dispatch to Moltbook.
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

    print(f"[+] Briefing generated: {briefing_id} (Witness ID: {witness_id})")

    # 3. Publish to docs/reports/ for GitHub Pages
    target_docs = output_docs_dir or (BASE_DIR / "docs" / "reports")
    target_docs.mkdir(parents=True, exist_ok=True)

    dated_doc = target_docs / f"briefing_{date_str}.md"
    latest_doc = target_docs / "latest_briefing.md"
    dated_doc.write_text(report_md, encoding="utf-8")
    latest_doc.write_text(report_md, encoding="utf-8")
    print(f"[+] Static documentation updated at: {latest_doc}")

    # 4. Format Community Post for Moltbook
    post_title = f"[Daily Alpha Briefing] Solana Quant Signals, Verified Exploits & Protocol Radar — {date_str}"

    # Extract top signals for community preview
    top_signals = engine.search_signals(limit=5)
    bullet_points = []
    for s in top_signals:
        bullet_points.append(f"- **{s['headline']}** `[{s['confidence']}]`\n  {s['summary']}")

    signals_block = "\n".join(bullet_points) if bullet_points else "- All systems operating under nominal baseline parameters."

    post_content = f"""## Moltbook Alpha Verified Intelligence & Quant Briefing — {date_str}

{signals_block}

---

### Verification & State Integrity
- **Briefing ID:** `{briefing_id}`
- **Ed25519 Cryptographic State Witness:** `{witness_id or 'Awaiting Signature'}`
- **Analyzed Base:** {briefing.get('items_analyzed', 0)} sources indexed across Solana DEX feeds, RPC telemetry, audit logs, and agent protocols.

Full mathematical report and interactive WebSocket stream available via [Moltbook Alpha Gateway](https://movement-enlarge-sites-dock.trycloudflare.com).
"""

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
                print(f"[*] Posting community update to m/{submolt}...")
                post_res, verified = client.create_post(submolt, post_title, post_content)
                posted = True
                post_result = {
                    "verified": verified,
                    "response": post_res,
                }
                print(f"[+] Successfully posted to m/{submolt}! Verified: {verified}")
                sm.log_audit_event(
                    "community_alpha_published",
                    f"Briefing {briefing_id} posted to m/{submolt} (witness: {witness_id})",
                    ip_address="publisher"
                )
            except Exception as e:
                print(f"[!] Warning: Failed to publish post to m/{submolt}: {e}")
                sm.log_audit_event(
                    "community_alpha_publish_failed",
                    f"Failed to post briefing {briefing_id} to m/{submolt}: {e!s}",
                    ip_address="publisher"
                )

    return {
        "success": True,
        "briefing_id": briefing_id,
        "state_witness_id": witness_id,
        "dated_report_path": str(dated_doc),
        "latest_report_path": str(latest_doc),
        "moltbook_posted": posted,
        "moltbook_post_result": post_result,
    }


def main():
    parser = argparse.ArgumentParser(description="Moltbook Alpha Automated Community Publisher")
    parser.add_argument("--submolt", default="builds", help="Target Moltbook submolt (default: builds)")
    parser.add_argument("--dry-run", action="store_true", help="Compile briefing and docs without posting to Moltbook")
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
