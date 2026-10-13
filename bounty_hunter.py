"""
GitHub & Web3 Bounty Monitor & Solution Preparer.
Scans for funded bounties across GitHub (Algora, Opire, Polar.sh, IssueHunt)
and parses requirements so we can immediately generate complete solutions.
"""

import urllib.request
import json
from pathlib import Path
from datetime import datetime

BOUNTY_DIR = Path(r"i:\Scripts and Programs\moltbook-intel\bounties")
BOUNTY_DIR.mkdir(parents=True, exist_ok=True)

SEARCH_QUERIES = [
    'is:issue is:open label:bounty "BOUNTY"',
    'is:issue is:open "opire" "bounty"',
    'is:issue is:open "algora" "$"',
    'is:issue is:open "polar.sh" "pledged"',
]

def search_github_bounties():
    results = []
    seen_urls = set()

    for q in SEARCH_QUERIES:
        url = f"https://api.github.com/search/issues?q={urllib.parse.quote(q)}&sort=created&order=desc&per_page=15"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "BountyHunterBot/1.0", "Accept": "application/vnd.github.v3+json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                for item in data.get("items", []):
                    html_url = item.get("html_url")
                    if html_url not in seen_urls:
                        seen_urls.add(html_url)
                        results.append({
                            "title": item.get("title"),
                            "url": html_url,
                            "comments": item.get("comments", 0),
                            "created_at": item.get("created_at"),
                            "body": item.get("body", "") or "",
                            "repository_url": item.get("repository_url")
                        })
        except Exception as e:
            print(f"[!] Error querying GitHub for '{q}': {e}")

    return results

def save_bounty_watchlist():
    bounties = search_github_bounties()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        "# Active GitHub & Web3 Bounty Opportunities",
        f"**Scanned:** {timestamp} | **Found:** {len(bounties)} listings\n",
        "| Title | Comments | Link |",
        "|---|---|---|"
    ]

    for b in bounties[:25]:
        title = b["title"].replace("|", "\\|")
        lines.append(f"| {title} | {b['comments']} | [View Issue]({b['url']}) |")

    out_file = BOUNTY_DIR / "active_bounties.md"
    with open(out_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    # Also save raw JSON for downstream solver agents
    with open(BOUNTY_DIR / "active_bounties.json", "w", encoding="utf-8") as f:
        json.dump(bounties, f, indent=2)

    print(f"[+] Saved {len(bounties)} bounties to {out_file}")
    return out_file

if __name__ == "__main__":
    save_bounty_watchlist()
