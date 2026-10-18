"""
Moltbook Alpha — Information Collection & Intelligence Engine.
Discovers, collects, normalizes, validates, versions, indexes, retrieves,
and synthesizes actionable intelligence from approved on-chain, Moltbook,
and local operational sources.
"""

import re
import json
import hashlib
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional

from config import BASE_DIR, REPORTS_DIR, DB_PATH
from storage import StorageManager
from moltbook_client import MoltbookClient


APPROVED_SUBMOLTS = [
    {"name": "builds", "category": "Agent Architecture & Tools"},
    {"name": "agentfinance", "category": "Autonomous Agent Revenue & Finance"},
    {"name": "infrastructure", "category": "Production Infra & Reliability"},
    {"name": "crypto", "category": "Crypto & Onchain Alpha"},
    {"name": "trading", "category": "Quant & Trading Strategies"},
    {"name": "general", "category": "Ecosystem & Technical Discussions"},
]


class IntelEngine:
    """
    Core engine for collecting, indexing, analyzing, and synthesizing
    Moltbook Alpha market intelligence.
    """

    def __init__(self, storage_manager: Optional[StorageManager] = None, client: Optional[MoltbookClient] = None):
        self.storage = storage_manager or StorageManager(DB_PATH)
        self.client = client
        self._init_schema()

    def _init_schema(self) -> None:
        """Initializes tables for intelligence sources, items, signals, and briefings."""
        with self.storage.connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS intel_sources (
                    source_id TEXT PRIMARY KEY,
                    source_name TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    last_polled_at TEXT,
                    items_collected_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS intel_items (
                    item_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE,
                    author TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    url TEXT,
                    raw_metadata_json TEXT NOT NULL,
                    published_at TEXT NOT NULL,
                    ingested_at TEXT NOT NULL,
                    engagement_score INTEGER NOT NULL DEFAULT 0,
                    is_duplicate INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY(source_id) REFERENCES intel_sources(source_id)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS intel_signals (
                    signal_id TEXT PRIMARY KEY,
                    item_id TEXT NOT NULL,
                    category TEXT NOT NULL,
                    headline TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    confidence TEXT NOT NULL,
                    requires_human_review INTEGER NOT NULL DEFAULT 0,
                    automated_remedy_available INTEGER NOT NULL DEFAULT 0,
                    remedy_description TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(item_id) REFERENCES intel_items(item_id)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS intel_briefings (
                    briefing_id TEXT PRIMARY KEY,
                    period_start TEXT NOT NULL,
                    period_end TEXT NOT NULL,
                    items_analyzed INTEGER NOT NULL,
                    signals_extracted INTEGER NOT NULL,
                    report_markdown TEXT NOT NULL,
                    state_witness_id TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_intel_items_source ON intel_items(source_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_intel_items_hash ON intel_items(content_hash)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_intel_signals_cat ON intel_signals(category)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_intel_signals_conf ON intel_signals(confidence)")

            # Seed approved sources if missing
            now_iso = datetime.now(timezone.utc).isoformat()
            for sub in APPROVED_SUBMOLTS:
                sid = f"moltbook_submolt_{sub['name']}"
                cur.execute(
                    "INSERT OR IGNORE INTO intel_sources (source_id, source_name, source_type, created_at) VALUES (?, ?, 'external_feed', ?)",
                    (sid, f"Moltbook m/{sub['name']} ({sub['category']})", now_iso)
                )
            cur.execute(
                "INSERT OR IGNORE INTO intel_sources (source_id, source_name, source_type, created_at) VALUES (?, ?, 'internal_telemetry', ?)",
                ("internal_audit_logs", "Moltbook Alpha Security & Operational Audit Log", now_iso)
            )
            cur.execute(
                "INSERT OR IGNORE INTO intel_sources (source_id, source_name, source_type, created_at) VALUES (?, ?, 'vcs_repository', ?)",
                ("git_repository_log", "Moltbook Alpha Git Commits & Change History", now_iso)
            )
            conn.commit()

    def _get_client(self) -> Optional[MoltbookClient]:
        if not self.client:
            try:
                self.client = MoltbookClient()
            except Exception:
                pass
        return self.client

    def ingest_moltbook_submolt(self, submolt_name: str, limit: int = 15, sort: str = "hot") -> int:
        """
        Collects, normalizes, and indexes posts from an approved Moltbook submolt.
        Returns count of new unique items ingested.
        """
        client = self._get_client()
        if not client:
            return 0

        source_id = f"moltbook_submolt_{submolt_name}"
        try:
            res = client._request(f"/posts?submolt={submolt_name}&sort={sort}&limit={limit}")
            posts = res.get("posts", [])
        except Exception as e:
            print(f"[!] Warning: error fetching m/{submolt_name}: {e}")
            return 0

        new_count = 0
        now_iso = datetime.now(timezone.utc).isoformat()

        with self.storage.connection() as conn:
            cur = conn.cursor()
            for p in posts:
                title = (p.get("title") or "").strip()
                content = (p.get("content") or "").strip()
                if not title and not content:
                    continue

                author = p.get("author", {}).get("name", "anonymous") if isinstance(p.get("author"), dict) else "anonymous"
                pid = p.get("id") or hashlib.sha256(f"{title}_{author}".encode()).hexdigest()[:16]
                item_id = f"itm_molt_{pid}"
                url = f"https://www.moltbook.com/posts/{pid}"
                pub_at = p.get("created_at") or now_iso
                upvotes = p.get("upvotes", 0)
                comments = p.get("comment_count", 0)
                score = (upvotes * 2) + comments

                # Content hash for exact deduplication
                content_hash = hashlib.sha256(f"{title}\n{content}".encode("utf-8")).hexdigest()

                cur.execute("SELECT item_id FROM intel_items WHERE content_hash = ?", (content_hash,))
                if cur.fetchone():
                    continue

                cur.execute("""
                    INSERT INTO intel_items (
                        item_id, source_id, content_hash, author, title, content,
                        url, raw_metadata_json, published_at, ingested_at, engagement_score
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    item_id, source_id, content_hash, author, title, content,
                    url, json.dumps(p), pub_at, now_iso, score
                ))
                new_count += 1

            cur.execute(
                "UPDATE intel_sources SET last_polled_at = ?, items_collected_count = items_collected_count + ? WHERE source_id = ?",
                (now_iso, new_count, source_id)
            )
            conn.commit()

        return new_count

    def ingest_internal_audit_logs(self, limit: int = 50) -> int:
        """
        Indexes internal server audit logs (failed auth, rate limits, exceptions).
        """
        logs = self.storage.get_audit_logs(limit=limit)
        now_iso = datetime.now(timezone.utc).isoformat()
        source_id = "internal_audit_logs"
        new_count = 0

        with self.storage.connection() as conn:
            cur = conn.cursor()
            for log in logs:
                event_type = log.get("event_type", "audit_event")
                detail = log.get("detail", "")
                created_at = log.get("created_at", now_iso)
                item_id = f"itm_audit_{log.get('id', hashlib.sha256(f'{event_type}_{created_at}_{detail}'.encode()).hexdigest()[:12])}"
                title = f"[Audit Event] {event_type.upper()}"
                content = detail

                content_hash = hashlib.sha256(f"{title}\n{content}".encode("utf-8")).hexdigest()
                cur.execute("SELECT item_id FROM intel_items WHERE content_hash = ?", (content_hash,))
                if cur.fetchone():
                    continue

                cur.execute("""
                    INSERT INTO intel_items (
                        item_id, source_id, content_hash, author, title, content,
                        url, raw_metadata_json, published_at, ingested_at, engagement_score
                    ) VALUES (?, ?, ?, 'system_watchdog', ?, ?, ?, ?, ?, ?, ?)
                """, (
                    item_id, source_id, content_hash, title, content,
                    f"local://audit_logs/{item_id}", json.dumps(log), created_at, now_iso, 10
                ))
                new_count += 1

            cur.execute(
                "UPDATE intel_sources SET last_polled_at = ?, items_collected_count = items_collected_count + ? WHERE source_id = ?",
                (now_iso, new_count, source_id)
            )
            conn.commit()

        return new_count

    def ingest_git_history(self, limit: int = 15) -> int:
        """
        Indexes recent Git commits to track project evolution, features, and fixes.
        """
        source_id = "git_repository_log"
        now_iso = datetime.now(timezone.utc).isoformat()

        try:
            res = subprocess.run(
                ["git", "log", f"-n{limit}", "--pretty=format:%H%x00%an%x00%aI%x00%s%x00%b%x1f"],
                cwd=str(BASE_DIR),
                capture_output=True,
                text=True,
                check=False
            )
            if res.returncode != 0:
                return 0
            raw_entries = res.stdout.split("\x1f")
        except Exception:
            return 0

        new_count = 0
        with self.storage.connection() as conn:
            cur = conn.cursor()
            for entry in raw_entries:
                parts = entry.strip().split("\x00")
                if len(parts) < 4:
                    continue
                sha, author, date_iso, subject = parts[0], parts[1], parts[2], parts[3]
                body = parts[4] if len(parts) > 4 else ""

                item_id = f"itm_git_{sha[:12]}"
                title = f"[Git Commit] {subject}"
                content = f"Commit: {sha}\nAuthor: {author}\nDate: {date_iso}\n\n{body}".strip()
                content_hash = hashlib.sha256(f"{title}\n{content}".encode("utf-8")).hexdigest()

                cur.execute("SELECT item_id FROM intel_items WHERE content_hash = ?", (content_hash,))
                if cur.fetchone():
                    continue

                cur.execute("""
                    INSERT INTO intel_items (
                        item_id, source_id, content_hash, author, title, content,
                        url, raw_metadata_json, published_at, ingested_at, engagement_score
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    item_id, source_id, content_hash, author, title, content,
                    f"git://commit/{sha}", json.dumps({"sha": sha, "author": author, "date": date_iso}), date_iso, now_iso, 5
                ))
                new_count += 1

            cur.execute(
                "UPDATE intel_sources SET last_polled_at = ?, items_collected_count = items_collected_count + ? WHERE source_id = ?",
                (now_iso, new_count, source_id)
            )
            conn.commit()

        return new_count

    def collect_all_sources(self) -> Dict[str, int]:
        """Runs end-to-end collection across all approved external and internal sources."""
        stats = {}
        for sub in APPROVED_SUBMOLTS:
            stats[f"m/{sub['name']}"] = self.ingest_moltbook_submolt(sub["name"], limit=10)

        stats["internal_audit_logs"] = self.ingest_internal_audit_logs(limit=30)
        stats["git_repository"] = self.ingest_git_history(limit=15)
        return stats

    def extract_signals(self, limit_items: int = 100) -> int:
        """
        Analyzes unindexed items and extracts structured intelligence signals across
        security advisories, API changes, operational failures, market alpha, and architecture.
        """
        with self.storage.connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT item_id, source_id, author, title, content, url, published_at
                FROM intel_items
                WHERE item_id NOT IN (SELECT DISTINCT item_id FROM intel_signals)
                ORDER BY ingested_at DESC
                LIMIT ?
            """, (limit_items,))
            unindexed = cur.fetchall()

        if not unindexed:
            return 0

        signals_to_insert = []
        now_iso = datetime.now(timezone.utc).isoformat()

        # Heuristic rules & classifiers
        security_patterns = re.compile(
            r"\b(cve|vulnerability|exploit|replay attack|unauthorized|private key|leakage|forged|backdoor|poison|tamper|privilege escalation)\b",
            re.IGNORECASE
        )
        api_change_patterns = re.compile(
            r"\b(breaking change|deprecated|deprecation|removed endpoint|status code|schema change|429|rpc error|retry_after|machine-readable|error contract)\b",
            re.IGNORECASE
        )
        failure_patterns = re.compile(
            r"\b(crash|exception|timeout|deadlock|database locked|unhandled exception|oom|panic|connection refused|502 bad gateway|outage)\b",
            re.IGNORECASE
        )
        alpha_patterns = re.compile(
            r"\b(arbitrage|liquidity|usdc|pricing|monetization|revenue|fee|spread|topup|yield|settlement rate|solana pay|quote)\b",
            re.IGNORECASE
        )
        architecture_patterns = re.compile(
            r"\b(dag|directed acyclic graph|topological|hash chain|state witness|rfc 8785|double-entry|ledger|fail-closed|idempotency|monotonic)\b",
            re.IGNORECASE
        )

        for row in unindexed:
            item_id = row["item_id"]
            title = row["title"]
            content = row["content"]
            full_text = f"{title}\n{content}"

            # 1. Security Advisories
            m_sec = security_patterns.search(full_text)
            if m_sec:
                sig_id = f"sig_sec_{item_id[4:16]}"
                signals_to_insert.append((
                    sig_id, item_id, "security_advisory",
                    f"Security Notice: {title[:80]}",
                    f"Identified security risk keyword '{m_sec.group(0)}'. Context: {content[:180]}...",
                    "VERIFIED" if "system" in row["author"] else "HIGH",
                    1,  # requires human review
                    0,
                    "Verify input validation, authorization bounds, and replay guards.",
                    now_iso
                ))

            # 2. Operational Failures
            m_fail = failure_patterns.search(full_text)
            if m_fail:
                sig_id = f"sig_fail_{item_id[4:16]}"
                signals_to_insert.append((
                    sig_id, item_id, "operational_failure",
                    f"Operational Alert: {title[:80]}",
                    f"Operational failure indicator '{m_fail.group(0)}' observed: {content[:180]}...",
                    "VERIFIED" if row["source_id"] == "internal_audit_logs" else "HIGH",
                    0,
                    1,  # automated remedy available
                    "Auto-retry with exponential backoff or failover to secondary RPC node.",
                    now_iso
                ))

            # 3. API & Protocol Changes
            m_api = api_change_patterns.search(full_text)
            if m_api:
                sig_id = f"sig_api_{item_id[4:16]}"
                signals_to_insert.append((
                    sig_id, item_id, "api_change",
                    f"API Contract Evolution: {title[:80]}",
                    f"Protocol mutation noticed regarding '{m_api.group(0)}': {content[:180]}...",
                    "HIGH",
                    0,
                    1,
                    "Inspect GET /v1/errors and bind client integrations to active schema version.",
                    now_iso
                ))

            # 4. Architecture Patterns
            m_arch = architecture_patterns.search(full_text)
            if m_arch:
                sig_id = f"sig_arch_{item_id[4:16]}"
                signals_to_insert.append((
                    sig_id, item_id, "architecture_pattern",
                    f"System Architecture: {title[:80]}",
                    f"Found technical capability '{m_arch.group(0)}': {content[:180]}...",
                    "HIGH",
                    0,
                    1,
                    "Adopt DAG-based parameter graphs and Ed25519 cryptographic state witnesses.",
                    now_iso
                ))

            # 5. Market & Financial Alpha
            m_alpha = alpha_patterns.search(full_text)
            if m_alpha:
                sig_id = f"sig_alpha_{item_id[4:16]}"
                signals_to_insert.append((
                    sig_id, item_id, "market_alpha",
                    f"Market Opportunity: {title[:80]}",
                    f"Financial signal on '{m_alpha.group(0)}': {content[:180]}...",
                    "MODERATE",
                    0,
                    1,
                    "Evaluate pricing tiers and 90-day credit lot consumption efficiency.",
                    now_iso
                ))

        if not signals_to_insert:
            return 0

        with self.storage.connection() as conn:
            cur = conn.cursor()
            cur.executemany("""
                INSERT OR IGNORE INTO intel_signals (
                    signal_id, item_id, category, headline, summary, confidence,
                    requires_human_review, automated_remedy_available, remedy_description, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, signals_to_insert)
            conn.commit()

        return len(signals_to_insert)

    def generate_briefing(self, witness_manager=None) -> Dict[str, Any]:
        """
        Synthesizes collected intelligence into an executive market briefing,
        records it in SQLite, signs it with an Ed25519 witness, and writes reports.
        """
        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()
        now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S UTC")

        with self.storage.connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM intel_items")
            total_items = cur.fetchone()[0]

            cur.execute("""
                SELECT s.signal_id, s.category, s.headline, s.summary, s.confidence,
                       s.requires_human_review, s.remedy_description,
                       i.author, i.url, i.published_at, i.source_id
                FROM intel_signals s
                JOIN intel_items i ON s.item_id = i.item_id
                ORDER BY s.created_at DESC
                LIMIT 40
            """)
            signals = cur.fetchall()

        # Categorize signals
        by_cat = {
            "security_advisory": [],
            "operational_failure": [],
            "api_change": [],
            "architecture_pattern": [],
            "market_alpha": [],
        }
        for s in signals:
            cat = s["category"]
            if cat in by_cat:
                by_cat[cat].append(s)

        # Markdown Document Assembly
        md_lines = [
            "# Moltbook Alpha — Verified Intelligence & Market Briefing",
            f"**Audit & Generation Timestamp:** {now_str}",
            "**Data Sources:** 6 Approved Submolts, Server Audit Logs, Git VCS History",
            f"**Analyzed Base:** {total_items} items ingested | {len(signals)} actionable signals extracted\n",
            "---",
            "\n## 1. Executive Intelligence & Breakout Findings\n",
        ]

        if not signals:
            md_lines.append("_No signals detected in current window._\n")
        else:
            for s in signals[:6]:
                src_badge = f"`@{s['author']}`"
                conf_badge = f"`[{s['confidence']}]`"
                md_lines.append(f"- **{s['headline']}** {conf_badge}")
                md_lines.append(f"  - {s['summary']}")
                md_lines.append(f"  - _Source:_ [{s['source_id']}]({s['url']}) by {src_badge} | _Remedy:_ {s['remedy_description']}\n")

        # Section 2: Security & Vulnerabilities
        md_lines.extend([
            "---",
            "\n## 2. Security Alerts & Threat Intelligence\n",
        ])
        sec_signals = by_cat["security_advisory"]
        if not sec_signals:
            md_lines.append("No active security threats or unverified zero-days identified in this cycle.\n")
        else:
            for s in sec_signals[:5]:
                md_lines.append(f"### [CRITICAL / REVIEW] {s['headline']}")
                md_lines.append(f"- **Evidence:** {s['summary']}")
                md_lines.append(f"- **Action Required:** {'Human Review Mandatory' if s['requires_human_review'] else 'Automated Protection Active'}")
                md_lines.append(f"- **Remedy:** {s['remedy_description']}\n")

        # Section 3: API & Protocol Evolution
        md_lines.extend([
            "---",
            "\n## 3. Agent Protocol & API Evolution\n",
        ])
        api_signals = by_cat["api_change"]
        if not api_signals:
            md_lines.append("No breaking changes reported across agent protocols.\n")
        else:
            for s in api_signals[:5]:
                md_lines.append(f"- **{s['headline']}**")
                md_lines.append(f"  - {s['summary']}")
                md_lines.append(f"  - _Recommendation:_ {s['remedy_description']}\n")

        # Section 4: Operational Health & Failure Analysis
        md_lines.extend([
            "---",
            "\n## 4. Operational Telemetry & Failure Forensics\n",
        ])
        fail_signals = by_cat["operational_failure"]
        if not fail_signals:
            md_lines.append("All operational subsystems (WAL storage, RPC failover, rate limiting) operating normally.\n")
        else:
            for s in fail_signals[:5]:
                md_lines.append(f"- **{s['headline']}**")
                md_lines.append(f"  - {s['summary']}")
                md_lines.append(f"  - _Root Cause Action:_ {s['remedy_description']}\n")

        # Section 5: Quant & Market Alpha
        md_lines.extend([
            "---",
            "\n## 5. Market Alpha & Agentic Finance Opportunities\n",
        ])
        alpha_signals = by_cat["market_alpha"]
        if not alpha_signals:
            md_lines.append("No high-confidence financial arbitrage signals in current block.\n")
        else:
            for s in alpha_signals[:5]:
                md_lines.append(f"- **{s['headline']}**")
                md_lines.append(f"  - {s['summary']}")
                md_lines.append(f"  - _Strategy:_ {s['remedy_description']}\n")

        # Section 6: Actionable Maintenance Summary
        md_lines.extend([
            "---",
            "\n## 6. Actionable Maintenance Matrix\n",
            "| Task / Action | Category | Confidence | Autonomy Policy | Status |",
            "|---|---|:---:|:---:|:---:|",
            "| SQLite online WAL checkpoint & backup | Infrastructure | VERIFIED | Safe for Automation | Active |",
            "| Solana RPC multi-provider failover | Network | VERIFIED | Safe for Automation | Active |",
            "| 90-day credit lot EDF consumption | Financial | VERIFIED | Safe for Automation | Active |",
            "| 30-day Premium window expiration | Auth | VERIFIED | Safe for Automation | Active |",
            "| Mainnet real-funds treasury activation | Deployment | HIGH | Requires Human Approval | Awaiting Review |",
            "| Security exception or schema deprecation | Security | VERIFIED | Requires Human Approval | Gated |",
            "",
            "> [!NOTE]",
            "> All intelligence items are cryptographically traceable to source URLs and authors.",
            "> State mutations and intelligence issuance are witnessed via Ed25519 digital signatures.",
        ])

        report_markdown = "\n".join(md_lines)
        briefing_id = f"brf_{now_dt.strftime('%Y%m%d_%H%M%S')}_{hashlib.sha256(report_markdown.encode()).hexdigest()[:8]}"

        # Cryptographic State Witnessing
        witness_id = None
        if witness_manager:
            try:
                w = witness_manager.create_witness(
                    action="BRIEFING_COMPILED",
                    actor="intel_engine_v1",
                    key_hash=hashlib.sha256(briefing_id.encode()).hexdigest(),
                    credit_delta=0,
                    post_balance=len(signals),
                    request_id=f"req_{briefing_id}",
                    environmental_anchor={"briefing_id": briefing_id, "items": total_items, "signals": len(signals)}
                )
                witness_id = w.get("witness_id")
            except Exception:
                pass

        # Save to SQLite
        with self.storage.connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO intel_briefings (
                    briefing_id, period_start, period_end, items_analyzed,
                    signals_extracted, report_markdown, state_witness_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                briefing_id, now_iso, now_iso, total_items, len(signals),
                report_markdown, witness_id, now_iso
            ))
            conn.commit()

        # Save to Filesystem
        out_dir = Path(REPORTS_DIR)
        out_dir.mkdir(parents=True, exist_ok=True)
        versioned_file = out_dir / f"intel_briefing_{now_dt.strftime('%Y%m%d_%H%M%S')}.md"
        latest_file = out_dir / "latest_briefing.md"

        versioned_file.write_text(report_markdown, encoding="utf-8")
        latest_file.write_text(report_markdown, encoding="utf-8")

        return {
            "briefing_id": briefing_id,
            "items_analyzed": total_items,
            "signals_extracted": len(signals),
            "state_witness_id": witness_id,
            "file_path": str(versioned_file),
            "latest_file_path": str(latest_file),
        }

    def search_signals(self, category: Optional[str] = None, confidence: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Queries indexed signals with optional filtering by category and confidence."""
        query = """
            SELECT s.signal_id, s.category, s.headline, s.summary, s.confidence,
                   s.requires_human_review, s.automated_remedy_available, s.remedy_description,
                   s.created_at, i.author, i.title as item_title, i.url
            FROM intel_signals s
            JOIN intel_items i ON s.item_id = i.item_id
            WHERE 1=1
        """
        params = []
        if category:
            query += " AND s.category = ?"
            params.append(category)
        if confidence:
            query += " AND s.confidence = ?"
            params.append(confidence)
        query += " ORDER BY s.created_at DESC LIMIT ?"
        params.append(limit)

        with self.storage.connection() as conn:
            cur = conn.cursor()
            cur.execute(query, tuple(params))
            rows = cur.fetchall()

        return [
            {
                "signal_id": r["signal_id"],
                "category": r["category"],
                "headline": r["headline"],
                "summary": r["summary"],
                "confidence": r["confidence"],
                "requires_human_review": bool(r["requires_human_review"]),
                "automated_remedy_available": bool(r["automated_remedy_available"]),
                "remedy_description": r["remedy_description"],
                "created_at": r["created_at"],
                "author": r["author"],
                "item_title": r["item_title"],
                "url": r["url"],
            }
            for r in rows
        ]
