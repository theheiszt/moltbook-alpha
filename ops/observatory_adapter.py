"""
Moltbook Alpha — Public Observatory Intelligence Source Adapter (ops/observatory_adapter.py).

Implements Phase 1 (Option A) of the Observatory Integration:
1. Ingests macro word velocity and emerging-topic trends (/api/trends).
2. Syncs global submolt directory metadata (/api/submolts) across 8,600+ agent communities.
3. Completely decoupled from existing collectors; zero raw archive bloating.
4. Generates classified intelligence signals with full source attribution.
"""

import sys
import os
import json
import hashlib
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timezone

# Ensure stdout handles unicode characters safely
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config import DB_PATH
from storage import StorageManager

DEFAULT_OBSERVATORY_API_URL = os.getenv("OBSERVATORY_API_URL", "https://moltbook-observatory.sushant.info.np")
ATTRIBUTION_NOTICE = "Moltbook Observatory / SimulaMet (MIT License)"

SOURCE_ID_TRENDS = "observatory_macro_trends"
SOURCE_ID_SUBMOLTS = "observatory_submolt_directory"


class ObservatoryClient:
    """Read-only client for the public Moltbook Observatory REST API."""

    def __init__(self, base_url: str = DEFAULT_OBSERVATORY_API_URL, timeout: int = 15):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.user_agent = "MoltbookAlphaAdapter/1.0 (Observatory Intelligence Ingest; +https://theheiszt.github.io/moltbook-alpha)"

    def _request(self, endpoint: str) -> Tuple[int, Dict[str, Any], Optional[str]]:
        url = f"{self.base_url}{endpoint}"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": self.user_agent, "Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                status = resp.status
                raw = resp.read().decode("utf-8", errors="replace")
                try:
                    data = json.loads(raw)
                except Exception:
                    data = {"raw": raw}
                return status, data, None
        except urllib.error.HTTPError as e:
            raw_err = e.read().decode("utf-8", errors="replace")
            try:
                err_json = json.loads(raw_err)
            except Exception:
                err_json = {"error": raw_err}
            return e.code, err_json, raw_err
        except Exception as e:
            return 0, {"error": str(e)}, str(e)

    def get_stats(self) -> Dict[str, Any]:
        """Fetches platform-wide summary counters."""
        status, data, err = self._request("/api/stats")
        return {"success": status == 200, "status": status, "data": data, "error": err}

    def get_trends(self, hours: int = 24) -> Dict[str, Any]:
        """Fetches trending words and velocity deltas."""
        status, data, err = self._request(f"/api/trends?hours={hours}")
        return {"success": status == 200, "status": status, "data": data, "error": err}

    def get_submolts(self) -> Dict[str, Any]:
        """Fetches the global submolt directory."""
        status, data, err = self._request("/api/submolts")
        return {"success": status == 200, "status": status, "data": data, "error": err}

    def get_trend_history(self, word: str, days: int = 7) -> Dict[str, Any]:
        """Fetches historical hourly frequency for a specific word."""
        status, data, err = self._request(f"/api/trends/history?word={urllib.parse.quote(word)}&days={days}")
        return {"success": status == 200, "status": status, "data": data, "error": err}


class ObservatorySourceAdapter:
    """Manages ingestion of Observatory intelligence into Moltbook Alpha."""

    def __init__(
        self,
        storage_manager: Optional[StorageManager] = None,
        client: Optional[ObservatoryClient] = None,
        enabled: Optional[bool] = None,
    ):
        self.storage = storage_manager or StorageManager(DB_PATH)
        self.client = client or ObservatoryClient()
        if enabled is not None:
            self.enabled = enabled
        else:
            self.enabled = os.getenv("OBSERVATORY_INTEGRATION_ENABLED", "true").lower() in ("true", "1", "yes")

        self._init_schema()

    def _init_schema(self) -> None:
        """Initializes sync checkpoint table and seeds approved intelligence sources."""
        from intel_engine import IntelEngine
        # Ensure base intel tables (intel_sources, intel_items, intel_signals) are initialized
        IntelEngine(storage_manager=self.storage)

        now_iso = datetime.now(timezone.utc).isoformat()
        with self.storage.connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS observatory_sync_state (
                    sync_key TEXT PRIMARY KEY,
                    source_type TEXT NOT NULL,
                    last_synced_cursor TEXT,
                    last_synced_at TEXT NOT NULL,
                    records_synced_count INTEGER DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'IDLE',
                    error_message TEXT
                )
            """)

            # Register approved source identities in intel_sources
            cur.execute("""
                INSERT OR IGNORE INTO intel_sources (source_id, source_name, source_type, created_at)
                VALUES (?, ?, 'external_observatory', ?)
            """, (
                SOURCE_ID_TRENDS,
                f"Moltbook Observatory — 24h Macro Word Trends [{ATTRIBUTION_NOTICE}]",
                now_iso
            ))

            cur.execute("""
                INSERT OR IGNORE INTO intel_sources (source_id, source_name, source_type, created_at)
                VALUES (?, ?, 'external_observatory', ?)
            """, (
                SOURCE_ID_SUBMOLTS,
                f"Moltbook Observatory — Global Submolt Directory [{ATTRIBUTION_NOTICE}]",
                now_iso
            ))
            conn.commit()

    @staticmethod
    def _classify_trend_word(word: str) -> str:
        """Classifies a trending keyword into an intelligence signal category."""
        w = word.lower().strip()
        security_keywords = {"cve", "vulnerability", "exploit", "leak", "secret", "tamper", "poison", "backdoor", "attack", "replay"}
        alpha_keywords = {"arbitrage", "liquidity", "yield", "spread", "sol", "token", "usdc", "pricing", "bounty", "fee", "trade"}
        ops_keywords = {"rate", "limit", "429", "timeout", "crash", "error", "panic", "lock", "unhandled"}

        if any(k in w for k in security_keywords):
            return "security_audit"
        elif any(k in w for k in alpha_keywords):
            return "market_alpha"
        elif any(k in w for k in ops_keywords):
            return "operational_failure"
        else:
            return "architecture"

    def sync_macro_trends(self, hours: int = 24, min_count: int = 20, min_change_pct: float = 30.0) -> Dict[str, Any]:
        """
        Ingests significant word trends from the Observatory, deduplicating via content_hash
        and creating structured actionable signals in intel_signals.
        """
        if not self.enabled:
            return {"success": False, "skipped": True, "reason": "OBSERVATORY_INTEGRATION_ENABLED is False"}

        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()
        res = self.client.get_trends(hours=hours)

        if not res.get("success"):
            err_msg = res.get("error", f"HTTP {res.get('status')}")
            with self.storage.connection() as conn:
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO observatory_sync_state (sync_key, source_type, last_synced_at, status, error_message)
                    VALUES ('macro_trends_24h', 'rest_api', ?, 'ERROR', ?)
                    ON CONFLICT(sync_key) DO UPDATE SET
                        last_synced_at = excluded.last_synced_at,
                        status = 'ERROR',
                        error_message = excluded.error_message
                """, (now_iso, err_msg))
                conn.commit()
            return {"success": False, "error": err_msg}

        data = res.get("data", {})
        trends = data.get("trends", []) if isinstance(data, dict) else []

        new_items = 0
        new_signals = 0

        with self.storage.connection() as conn:
            cur = conn.cursor()
            for t in trends:
                word = str(t.get("word", "")).strip().lower()
                count = int(t.get("count", 0))
                prev_count = int(t.get("previous_count", 0))
                change_pct = float(t.get("change_percent", 0.0))

                # Filter for acceleration / significant volume
                if not word or (count < min_count and change_pct < min_change_pct):
                    continue

                content_hash = hashlib.sha256(
                    f"obs_trend:{word}:{hours}:{count}:{prev_count}".encode("utf-8")
                ).hexdigest()

                cur.execute("SELECT item_id FROM intel_items WHERE content_hash = ?", (content_hash,))
                if cur.fetchone():
                    continue

                item_id = f"itm_obs_trend_{word}_{now_dt.strftime('%Y%m%d_%H%M%S')}"
                title = f"Observatory Macro Trend: '{word}' (Count: {count}, Velocity: +{change_pct:.1f}%)"
                content = (
                    f"The term '{word}' exhibited accelerating frequency on Moltbook over the last {hours} hours.\n"
                    f"Current occurrences: {count} | Previous baseline: {prev_count} | Velocity Delta: +{change_pct:.1f}%\n"
                    f"Source: Moltbook Observatory / SimulaMet (MIT License)\n"
                    f"Observation Window: {hours} hours ending {now_iso}"
                )
                url = f"{self.client.base_url}/trends"
                raw_meta = json.dumps({
                    "trend": t,
                    "hours": hours,
                    "attribution": ATTRIBUTION_NOTICE,
                    "client_synced_at": now_iso
                })

                cur.execute("""
                    INSERT INTO intel_items (
                        item_id, source_id, content_hash, author, title, content,
                        url, raw_metadata_json, published_at, ingested_at, engagement_score
                    ) VALUES (?, ?, ?, 'observatory_analytics', ?, ?, ?, ?, ?, ?, ?)
                """, (
                    item_id, SOURCE_ID_TRENDS, content_hash, title, content,
                    url, raw_meta, now_iso, now_iso, count
                ))
                new_items += 1

                # Generate intelligence signal
                category = self._classify_trend_word(word)
                confidence = "HIGH" if (change_pct >= 100.0 or count >= 200) else "MEDIUM"
                headline = f"Accelerating Community Topic: '{word}' (+{change_pct:.0f}% over {hours}h)"
                summary = (
                    f"Macro trend detected across Moltbook activity: '{word}' reached {count} occurrences "
                    f"(from {prev_count} prior baseline). Classified into {category}."
                )
                signal_id = f"sig_obs_{word}_{now_dt.strftime('%Y%m%d_%H%M%S')}"

                cur.execute("""
                    INSERT INTO intel_signals (
                        signal_id, item_id, category, headline, summary, confidence,
                        requires_human_review, automated_remedy_available, remedy_description, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?, ?)
                """, (
                    signal_id, item_id, category, headline, summary, confidence,
                    f"Evaluate keyword '{word}' against live submolt demand leaderboard.",
                    now_iso
                ))
                new_signals += 1

            # Update checkpoint
            cur.execute("""
                INSERT INTO observatory_sync_state (
                    sync_key, source_type, last_synced_cursor, last_synced_at, records_synced_count, status, error_message
                ) VALUES ('macro_trends_24h', 'rest_api', ?, ?, ?, 'IDLE', NULL)
                ON CONFLICT(sync_key) DO UPDATE SET
                    last_synced_cursor = excluded.last_synced_cursor,
                    last_synced_at = excluded.last_synced_at,
                    records_synced_count = observatory_sync_state.records_synced_count + excluded.records_synced_count,
                    status = 'IDLE',
                    error_message = NULL
            """, (f"trends_{hours}h_{now_iso}", now_iso, new_items))

            cur.execute("""
                UPDATE intel_sources
                SET last_polled_at = ?, items_collected_count = items_collected_count + ?
                WHERE source_id = ?
            """, (now_iso, new_items, SOURCE_ID_TRENDS))
            conn.commit()

        return {
            "success": True,
            "hours": hours,
            "new_items_ingested": new_items,
            "new_signals_extracted": new_signals,
            "synced_at": now_iso
        }

    def sync_submolt_directory(self, min_subscribers: int = 5) -> Dict[str, Any]:
        """
        Synchronizes high-density submolt communities from the Observatory directory
        into an ecosystem directory snapshot in intel_items.
        """
        if not self.enabled:
            return {"success": False, "skipped": True, "reason": "OBSERVATORY_INTEGRATION_ENABLED is False"}

        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()
        res = self.client.get_submolts()

        if not res.get("success"):
            err_msg = res.get("error", f"HTTP {res.get('status')}")
            with self.storage.connection() as conn:
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO observatory_sync_state (sync_key, source_type, last_synced_at, status, error_message)
                    VALUES ('submolt_directory', 'rest_api', ?, 'ERROR', ?)
                    ON CONFLICT(sync_key) DO UPDATE SET
                        last_synced_at = excluded.last_synced_at,
                        status = 'ERROR',
                        error_message = excluded.error_message
                """, (now_iso, err_msg))
                conn.commit()
            return {"success": False, "error": err_msg}

        data = res.get("data", {})
        submolts = data.get("submolts", []) if isinstance(data, dict) else []

        # Filter active submolts
        active_submolts = [
            s for s in submolts
            if int(s.get("subscriber_count", 0) or 0) >= min_subscribers
            or int(s.get("post_count", 0) or 0) >= 5
        ]

        content_str = json.dumps([
            {"name": s.get("name"), "subs": s.get("subscriber_count"), "posts": s.get("post_count")}
            for s in active_submolts[:200]
        ], sort_keys=True)
        content_hash = hashlib.sha256(f"obs_submolts_snapshot:{content_str}".encode("utf-8")).hexdigest()

        with self.storage.connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT item_id FROM intel_items WHERE content_hash = ?", (content_hash,))
            if not cur.fetchone():
                item_id = f"itm_obs_submolts_{now_dt.strftime('%Y%m%d')}"
                title = f"Observatory Ecosystem Directory: {len(submolts)} Submolts Tracked ({len(active_submolts)} Active)"
                summary_content = (
                    f"Moltbook Observatory global community registry: {len(submolts)} total submolts.\n"
                    f"Top active communities with >= {min_subscribers} subscribers: {len(active_submolts)}.\n"
                    f"Attribution: {ATTRIBUTION_NOTICE}\n"
                    f"Snapshot Timestamp: {now_iso}"
                )
                raw_meta = json.dumps({
                    "total_submolts_count": len(submolts),
                    "active_submolts_count": len(active_submolts),
                    "top_submolts": active_submolts[:50],
                    "attribution": ATTRIBUTION_NOTICE
                })
                cur.execute("""
                    INSERT INTO intel_items (
                        item_id, source_id, content_hash, author, title, content,
                        url, raw_metadata_json, published_at, ingested_at, engagement_score
                    ) VALUES (?, ?, ?, 'observatory_directory', ?, ?, ?, ?, ?, ?, ?)
                """, (
                    item_id, SOURCE_ID_SUBMOLTS, content_hash, title, summary_content,
                    f"{self.client.base_url}/submolts", raw_meta, now_iso, now_iso, len(active_submolts)
                ))

            # Update checkpoint
            cur.execute("""
                INSERT INTO observatory_sync_state (
                    sync_key, source_type, last_synced_cursor, last_synced_at, records_synced_count, status, error_message
                ) VALUES ('submolt_directory', 'rest_api', ?, ?, ?, 'IDLE', NULL)
                ON CONFLICT(sync_key) DO UPDATE SET
                    last_synced_cursor = excluded.last_synced_cursor,
                    last_synced_at = excluded.last_synced_at,
                    records_synced_count = ?,
                    status = 'IDLE',
                    error_message = NULL
            """, (f"submolts_{len(submolts)}_{now_iso}", now_iso, len(submolts), len(submolts)))

            cur.execute("""
                UPDATE intel_sources
                SET last_polled_at = ?, items_collected_count = ?
                WHERE source_id = ?
            """, (now_iso, len(submolts), SOURCE_ID_SUBMOLTS))
            conn.commit()

        return {
            "success": True,
            "total_submolts": len(submolts),
            "active_submolts": len(active_submolts),
            "synced_at": now_iso
        }

    def get_status(self) -> Dict[str, Any]:
        """Returns sync status, high-watermark timestamps, and attribution metadata."""
        with self.storage.connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT sync_key, source_type, last_synced_cursor, last_synced_at, records_synced_count, status, error_message FROM observatory_sync_state")
            rows = cur.fetchall()

            cur.execute("SELECT COUNT(*) FROM intel_items WHERE source_id LIKE 'observatory_%'")
            obs_items_count = int(cur.fetchone()[0] or 0)

            cur.execute("SELECT COUNT(*) FROM intel_signals WHERE signal_id LIKE 'sig_obs_%'")
            obs_signals_count = int(cur.fetchone()[0] or 0)

        states = {
            r[0]: {
                "source_type": r[1],
                "last_cursor": r[2],
                "last_synced_at": r[3],
                "records_count": r[4],
                "status": r[5],
                "error": r[6],
            }
            for r in rows
        }

        return {
            "enabled": self.enabled,
            "observatory_api_url": getattr(self.client, "base_url", DEFAULT_OBSERVATORY_API_URL),
            "attribution": ATTRIBUTION_NOTICE,
            "items_ingested": obs_items_count,
            "signals_extracted": obs_signals_count,
            "checkpoints": states
        }

    def get_recent_trends(self, hours: int = 24, limit: int = 50, category: Optional[str] = None) -> Dict[str, Any]:
        """
        Retrieves recent ingested trends and anomaly signals from the local database.
        If local cache has no items, performs an initial inline sync.
        """
        limit = max(1, min(limit, 100))
        with self.storage.connection() as conn:
            cur = conn.cursor()
            query = """
                SELECT s.signal_id, s.category, s.headline, s.summary, s.confidence,
                       s.created_at, i.item_id, i.content_hash, i.engagement_score, i.raw_metadata_json
                FROM intel_signals s
                JOIN intel_items i ON s.item_id = i.item_id
                WHERE i.source_id = ?
            """
            params: List[Any] = [SOURCE_ID_TRENDS]
            if category:
                query += " AND s.category = ?"
                params.append(category.lower().strip())
            query += " ORDER BY s.created_at DESC LIMIT ?"
            params.append(limit)

            cur.execute(query, tuple(params))
            rows = cur.fetchall()

        # If empty and adapter enabled, trigger an inline sync to populate initial data
        if not rows and self.enabled:
            sync_res = self.sync_macro_trends(hours=hours)
            if sync_res.get("success"):
                with self.storage.connection() as conn:
                    cur = conn.cursor()
                    cur.execute(query, tuple(params))
                    rows = cur.fetchall()

        trends = []
        for r in rows:
            meta = {}
            try:
                meta = json.loads(r[9])
            except Exception:
                pass
            trends.append({
                "signal_id": r[0],
                "category": r[1],
                "headline": r[2],
                "summary": r[3],
                "confidence": r[4],
                "created_at": r[5],
                "item_id": r[6],
                "content_hash": r[7],
                "volume_count": r[8],
                "metadata": meta,
            })

        return {
            "count": len(trends),
            "attribution": ATTRIBUTION_NOTICE,
            "trends": trends,
            "status": self.get_status()
        }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Moltbook Alpha Observatory Source Adapter")
    parser.add_argument("--sync", action="store_true", help="Execute complete synchronization cycle (trends + submolts)")
    parser.add_argument("--trends", action="store_true", help="Sync only macro 24h word trends")
    parser.add_argument("--submolts", action="store_true", help="Sync only global submolt directory")
    parser.add_argument("--status", action="store_true", help="Print sync status and checkpoints")

    args = parser.parse_args()
    adapter = ObservatorySourceAdapter()

    if args.status:
        st = adapter.get_status()
        print("\n=== Moltbook Observatory Source Adapter Status ===")
        print(f"Enabled:          {st['enabled']}")
        print(f"Observatory URL:  {st['observatory_api_url']}")
        print(f"Attribution:      {st['attribution']}")
        print(f"Items Ingested:   {st['items_ingested']}")
        print(f"Signals Created:  {st['signals_extracted']}")
        print("Checkpoints:")
        for k, v in st.get("checkpoints", {}).items():
            print(f"  - [{k}] {v['status']} (last: {v['last_synced_at']}, count: {v['records_count']})")
        print("===================================================\n")
    elif args.trends:
        print("[*] Synchronizing macro 24h word trends from Observatory...")
        res = adapter.sync_macro_trends()
        print(f"Result: {res}")
    elif args.submolts:
        print("[*] Synchronizing global submolt directory from Observatory...")
        res = adapter.sync_submolt_directory()
        print(f"Result: {res}")
    else:
        # Default: run full sync cycle
        print("[*] Running Observatory Intelligence Sync Cycle...")
        t_res = adapter.sync_macro_trends()
        print(f"Trends sync: {t_res}")
        s_res = adapter.sync_submolt_directory()
        print(f"Submolts sync: {s_res}")


if __name__ == "__main__":
    main()
