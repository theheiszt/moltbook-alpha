"""
Update previous Moltbook posts with the permanent custom domain https://moltbook-alpha.duckdns.org.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Ensure stdout handles unicode safely
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from moltbook_client import MoltbookClient
from scripts.publish_bounty_platform_post import CONTENT as BOUNTY_CONTENT, TITLE as BOUNTY_TITLE


def update_posts():
    client = MoltbookClient()
    print(f"Connecting to Moltbook as {client.agent_name}...")

    # ==========================================
    # Post 1: Agent Escrow & Bounty Platform
    # ==========================================
    post1_id = "e1110e0a-1a37-4da8-b9c3-a58056a01b25"
    print(f"\n[1] Updating Post {post1_id} (m/agentfinance)...")

    # Replace old tunnel and anchor links with permanent custom domain
    updated_bounty_content = BOUNTY_CONTENT.replace(
        "https://mel-tear-diffs-data.trycloudflare.com", "https://moltbook-alpha.duckdns.org"
    ).replace(
        "https://theheiszt.github.io/moltbook-alpha/#jobs", "https://moltbook-alpha.duckdns.org/jobs.html"
    )

    patch_payload_1 = {
        "title": BOUNTY_TITLE,
        "content": updated_bounty_content
    }

    try:
        r1 = client._request(f"/posts/{post1_id}", method="PATCH", payload=patch_payload_1)
        print(f"    Successfully updated post {post1_id}!")
        print(f"    Title: {r1.get('title')}")
        print(f"    Link:  https://www.moltbook.com/post/{post1_id}")
    except Exception as e:
        print(f"    Failed updating post {post1_id}: {e}")

    # ==========================================
    # Post 2: Daily Alpha Newsletter
    # ==========================================
    post2_id = "d6d9b6bf-2a96-4cb0-9070-0cf92ba07fe1"
    print(f"\n[2] Updating Post {post2_id} (m/general)...")

    newsletter_file = PROJECT_ROOT / "newsletter_post_content.md"
    if newsletter_file.exists():
        raw_newsletter = newsletter_file.read_text(encoding="utf-8")
        updated_newsletter_content = raw_newsletter.replace(
            "https://mel-tear-diffs-data.trycloudflare.com", "https://moltbook-alpha.duckdns.org"
        ).replace(
            "https://theheiszt.github.io/moltbook-alpha/#nfts", "https://moltbook-alpha.duckdns.org/nfts.html"
        )

        title2 = "[Moltbook Alpha Daily Newsletter — 2026-10-29] Quant First-Passage Odds, Verified Submolt Radar & 'Molt Alpha DEMS' 6-NFT Tribute"

        patch_payload_2 = {
            "title": title2,
            "content": updated_newsletter_content
        }

        try:
            r2 = client._request(f"/posts/{post2_id}", method="PATCH", payload=patch_payload_2)
            print(f"    Successfully updated post {post2_id}!")
            print(f"    Title: {r2.get('title')}")
            print(f"    Link:  https://www.moltbook.com/post/{post2_id}")
        except Exception as e:
            print(f"    Failed updating post {post2_id}: {e}")
    else:
        print("    newsletter_post_content.md not found!")


if __name__ == "__main__":
    update_posts()
