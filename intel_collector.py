"""
Moltbook Alpha — Intelligence Collector & Briefing Synthesis Script.
Invoked periodically by systemd (moltbook-report.service) or CLI.
Executes source collection, deduplication, signal extraction, and cryptographic briefing generation.
"""

import sys
from storage import StorageManager
from config import DB_PATH, WITNESS_KEY_PATH
from cryptographic_witness import WitnessManager, WitnessKeyManager
from intel_engine import IntelEngine


def run_intelligence_cycle() -> None:
    print("[*] Initializing Moltbook Alpha Intelligence Subsystem...")
    storage = StorageManager(DB_PATH)
    witness_km = WitnessKeyManager(WITNESS_KEY_PATH)
    witness_mgr = WitnessManager(storage, witness_km)
    engine = IntelEngine(storage)

    print("[*] Ingesting approved external and internal sources...")
    stats = engine.collect_all_sources()
    for src, count in stats.items():
        print(f"  -> {src}: {count} new items")

    print("[*] Extracting structured intelligence signals...")
    signals_count = engine.extract_signals(limit_items=100)
    print(f"  -> Extracted {signals_count} actionable signals")

    print("[*] Synthesizing verified market briefing...")
    res = engine.generate_briefing(witness_manager=witness_mgr)
    print(f"[+] Briefing compiled: {res['briefing_id']}")
    print(f"  -> Items analyzed: {res['items_analyzed']}")
    print(f"  -> Signals extracted: {res['signals_extracted']}")
    print(f"  -> State witness ID: {res['state_witness_id']}")
    print(f"  -> Latest briefing written to: {res['latest_file_path']}")


if __name__ == "__main__":
    try:
        run_intelligence_cycle()
    except Exception as e:
        print(f"[ERROR] Intelligence cycle failed: {e}", file=sys.stderr)
        sys.exit(1)
