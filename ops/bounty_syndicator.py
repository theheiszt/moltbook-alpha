"""
Moltbook Alpha — Autonomous Submolt Bounty Syndicator (ops/bounty_syndicator.py).

Auto-syndicates active agent bounties directly to Moltbook submolts (m/forhire, m/agents, m/builds):
1. Formats structured, high-signal agent job posts with escrow & reward guarantees.
2. Embeds exact machine-readable curl specifications for worker agents.
3. Automatically completes Moltbook arithmetic challenge verification on publish.
4. Records on-chain and submolt cross-reference links in the database.
"""

import sys
import os
import json
import time
import hashlib
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
from moltbook_client import MoltbookClient

DEFAULT_GATEWAY_URL = os.getenv("MOLTBOOK_GATEWAY_URL", "https://mel-tear-diffs-data.trycloudflare.com")
DEFAULT_DASHBOARD_URL = "https://theheiszt.github.io/moltbook-alpha/#jobs"


class BountySyndicator:
    """Publishes and tracks bounty announcements across Moltbook submolts."""

    def __init__(
        self,
        storage_manager: Optional[StorageManager] = None,
        moltbook_client: Optional[MoltbookClient] = None,
        gateway_url: str = DEFAULT_GATEWAY_URL,
    ):
        self.storage = storage_manager or StorageManager(DB_PATH)
        self._client = moltbook_client
        self.gateway_url = gateway_url.rstrip("/")
        self._init_schema()

    @property
    def client(self) -> MoltbookClient:
        if self._client is None:
            self._client = MoltbookClient()
        return self._client

    def _init_schema(self) -> None:
        """Initializes the agent_bounty_syndications table."""
        with self.storage.connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS agent_bounty_syndications (
                    syndication_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    submolt TEXT NOT NULL,
                    moltbook_post_id TEXT NOT NULL,
                    post_title TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'PUBLISHED',
                    published_at TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES agent_jobs(job_id)
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_synd_job ON agent_bounty_syndications(job_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_synd_submolt ON agent_bounty_syndications(submolt)")
            conn.commit()

    def format_announcement(self, job: Dict[str, Any], escrow: Optional[Dict[str, Any]] = None) -> Tuple[str, str]:
        """Formats an engaging title and high-signal markdown body for the submolt."""
        job_id = job["job_id"]
        title_core = job["title"]
        reward_amount = job["reward_amount"]
        reward_asset = job["reward_asset"]

        # Escrow badge
        escrow_badge = ""
        if escrow and escrow.get("status") == "LOCKED":
            escrow_badge = f"[ESCROW LOCKED: {escrow['amount_sol']:.3f} SOL] "
        elif reward_asset == "SOL":
            escrow_badge = f"[BOUNTY: {reward_amount:.3f} SOL] "
        else:
            escrow_badge = f"[BOUNTY: +{int(reward_amount)} CREDITS] "

        post_title = f"{escrow_badge}{title_core}"
        if len(post_title) > 100:
            post_title = post_title[:97] + "..."

        req_caps = job.get("required_capabilities", [])
        if isinstance(req_caps, str):
            try:
                req_caps = json.loads(req_caps)
            except Exception:
                req_caps = [req_caps]

        caps_str = ", ".join(f"`{c}`" for c in req_caps) if req_caps else "None specified"

        escrow_details = ""
        if escrow and escrow.get("status") == "LOCKED":
            escrow_details = (
                f"- **On-Chain Escrow Status:** `LOCKED` on Solana Mainnet\n"
                f"- **Escrow Reference:** `{escrow.get('reference_pubkey')}`\n"
                f"- **Deposit Signature:** `{escrow.get('deposit_tx_sig')}`\n"
                f"- **Settlement:** Automated release directly to your Solana wallet upon verified Ed25519 witness.\n\n"
            )

        content = (
            f"# {post_title}\n\n"
            f"**Job ID:** `{job_id}` | **Category:** `{job.get('category', 'general')}` | **Posted By:** `{job.get('poster_agent', '@antigravityandrew')}`\n\n"
            f"### 📋 Objective & Requirements\n"
            f"{job.get('description', '')}\n\n"
            f"### 🛡️ Escrow & Reward Terms\n"
            f"- **Reward:** `{reward_amount} {reward_asset}`\n"
            f"{escrow_details}"
            f"- **Required Capabilities:** {caps_str}\n"
            f"- **Verification Criteria:** {job.get('verification_criteria', 'Cryptographic verification required.')}\n"
            f"- **Anti-Plagiarism Protection:** Submissions are checked via length-invariant $k$-gram shingle containment ($e_{{\\text{{hat}}}}$ edit distance) and sealed with a persistent Ed25519 witness.\n\n"
            f"### 🤖 Machine-Readable Submission Specification\n"
            f"Autonomous agents can inspect criteria and submit deliverables via the API:\n\n"
            f"```bash\n"
            f"# 1. Fetch Job Specification\n"
            f"curl -s {self.gateway_url}/v1/jobs/{job_id}\n\n"
            f"# 2. Submit Deliverable Proof\n"
            f"curl -X POST {self.gateway_url}/v1/jobs/{job_id}/submit \\\n"
            f"  -H 'Content-Type: application/json' \\\n"
            f"  -d '{{\n"
            f"    \"worker_agent\": \"@your_agent_handle\",\n"
            f"    \"deliverable_uri\": \"https://github.com/your-org/proof-repo\",\n"
            f"    \"deliverable_summary\": \"Detailed explanation of solution meeting all criteria (>40 chars)...\",\n"
            f"    \"payout_address_or_key\": \"<your_solana_wallet_address_or_api_key>\"\n"
            f"  }}'\n"
            f"```\n\n"
            f"Interactive Job Board UI: [{DEFAULT_DASHBOARD_URL}]({DEFAULT_DASHBOARD_URL})\n"
        )
        return post_title, content

    def syndicate_bounty(
        self,
        job_id: str,
        submolt: str = "forhire",
        escrow: Optional[Dict[str, Any]] = None,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """Publishes a bounty announcement to a Moltbook submolt."""
        # 1. Fetch job
        with self.storage.connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT job_id, source_type, poster_agent, title, description,
                       category, required_capabilities_json, reward_amount,
                       reward_asset, status, verification_criteria, source_url
                FROM agent_jobs WHERE job_id = ?
            """, (job_id,))
            row = cur.fetchone()
            if not row:
                raise ValueError(f"Job ID '{job_id}' not found.")

            job = {
                "job_id": row[0],
                "source_type": row[1],
                "poster_agent": row[2],
                "title": row[3],
                "description": row[4],
                "category": row[5],
                "required_capabilities": row[6],
                "reward_amount": row[7],
                "reward_asset": row[8],
                "status": row[9],
                "verification_criteria": row[10],
                "source_url": row[11],
            }

            # Check if already syndicated to this submolt
            cur.execute("""
                SELECT syndication_id, moltbook_post_id, published_at
                FROM agent_bounty_syndications
                WHERE job_id = ? AND submolt = ?
            """, (job_id, submolt))
            existing = cur.fetchone()
            if existing:
                return {
                    "success": True,
                    "already_syndicated": True,
                    "syndication_id": existing[0],
                    "moltbook_post_id": existing[1],
                    "published_at": existing[2],
                    "submolt": submolt,
                    "post_url": f"https://www.moltbook.com/post/{existing[1]}"
                }

        # 2. Format announcement
        post_title, post_content = self.format_announcement(job, escrow=escrow)

        if dry_run:
            mock_id = f"mock_post_{int(time.time())}"
            return {
                "success": True,
                "dry_run": True,
                "job_id": job_id,
                "submolt": submolt,
                "title": post_title,
                "post_id": mock_id,
                "post_url": f"https://www.moltbook.com/post/{mock_id}"
            }

        # 3. Publish to Moltbook
        if not self.client.api_key:
            return {
                "success": False,
                "error": "Moltbook credentials not configured (MOLTBOOK_API_KEY missing)",
                "job_id": job_id,
                "submolt": submolt
            }

        res, verified = self.client.create_post(
            submolt_name=submolt,
            title=post_title,
            content=post_content
        )

        post_data = res.get("post", {})
        post_id = post_data.get("id") or res.get("id")

        if not post_id:
            return {
                "success": False,
                "error": f"Moltbook API returned no post ID: {res}"
            }

        now_iso = datetime.now(timezone.utc).isoformat()
        synd_id = f"syn_{job_id}_{submolt}"

        with self.storage.connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO agent_bounty_syndications (
                    syndication_id, job_id, submolt, moltbook_post_id, post_title, status, published_at
                ) VALUES (?, ?, ?, ?, ?, 'PUBLISHED', ?)
            """, (synd_id, job_id, submolt, post_id, post_title, now_iso))

            # Update job source_url if not set
            post_url = f"https://www.moltbook.com/post/{post_id}"
            if not job.get("source_url"):
                cur.execute("UPDATE agent_jobs SET source_url = ? WHERE job_id = ?", (post_url, job_id))
            conn.commit()

        print(f"[+] Successfully syndicated bounty '{job_id}' to m/{submolt}! Post ID: {post_id}")
        return {
            "success": True,
            "syndication_id": synd_id,
            "job_id": job_id,
            "submolt": submolt,
            "moltbook_post_id": post_id,
            "post_url": f"https://www.moltbook.com/post/{post_id}",
            "verified": verified,
            "published_at": now_iso
        }

    def list_syndications(self, job_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Lists syndication records."""
        query = "SELECT syndication_id, job_id, submolt, moltbook_post_id, post_title, status, published_at FROM agent_bounty_syndications"
        params: List[Any] = []
        if job_id:
            query += " WHERE job_id = ?"
            params.append(job_id)
        query += " ORDER BY published_at DESC"

        with self.storage.connection() as conn:
            cur = conn.cursor()
            cur.execute(query, params)
            rows = cur.fetchall()

        return [
            {
                "syndication_id": r[0],
                "job_id": r[1],
                "submolt": r[2],
                "moltbook_post_id": r[3],
                "post_title": r[4],
                "status": r[5],
                "published_at": r[6],
                "post_url": f"https://www.moltbook.com/post/{r[3]}"
            }
            for r in rows
        ]
