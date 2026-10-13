"""
Moltbook Market Intelligence & Trend Scraper.
Scrapes top submolts (trading, crypto, agentfinance, infrastructure, builds),
extracts signals, sentiment, tools, and produces actionable briefing reports.
"""

import os
import json
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

CONFIG_PATH = Path.home() / ".config" / "moltbook" / "credentials.json"
BASE_URL = "https://www.moltbook.com/api/v1"

SUBMOLTS_TO_MONITOR = [
    {"name": "trading", "category": "Quant & Trading Strategies"},
    {"name": "crypto", "category": "Crypto & Onchain Alpha"},
    {"name": "agentfinance", "category": "Autonomous Agent Revenue & Finance"},
    {"name": "builds", "category": "Agent Architecture & Tools"},
    {"name": "infrastructure", "category": "Production Infra & Reliability"},
]

def load_api_key():
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Credentials not found at {CONFIG_PATH}")
    with open(CONFIG_PATH, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
        return data.get("api_key")

def fetch_json(url, api_key):
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "MoltbookIntelBot/1.0"
        }
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))

def fetch_submolt_posts(submolt, api_key, limit=10, sort="hot"):
    url = f"{BASE_URL}/posts?submolt={submolt}&sort={sort}&limit={limit}"
    data = fetch_json(url, api_key)
    return data.get("posts", [])

def generate_report():
    api_key = load_api_key()
    report_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    sections = []
    summary_highlights = []

    for item in SUBMOLTS_TO_MONITOR:
        submolt_name = item["name"]
        cat_title = item["category"]
        print(f"[*] Fetching feed for m/{submolt_name}...")
        
        try:
            posts = fetch_submolt_posts(submolt_name, api_key, limit=8, sort="hot")
        except Exception as e:
            print(f"[!] Error fetching {submolt_name}: {e}")
            continue

        post_entries = []
        for p in posts:
            title = p.get("title", "").strip()
            upvotes = p.get("upvotes", 0)
            comments = p.get("comment_count", 0)
            pid = p.get("id")
            author = p.get("author", {}).get("name", "anon")
            content = p.get("content", "") or ""
            preview = content[:220].replace("\n", " ").strip()
            if len(content) > 220:
                preview += "..."

            post_entries.append({
                "id": pid,
                "title": title,
                "author": author,
                "upvotes": upvotes,
                "comments": comments,
                "preview": preview,
                "url": f"https://www.moltbook.com/posts/{pid}"
            })

            # Grab standout high-engagement items for executive summary
            if upvotes >= 6 or comments >= 3:
                summary_highlights.append({
                    "submolt": submolt_name,
                    "title": title,
                    "author": author,
                    "upvotes": upvotes,
                    "url": f"https://www.moltbook.com/posts/{pid}"
                })

        sections.append({
            "name": submolt_name,
            "category": cat_title,
            "posts": post_entries
        })

    # Render Markdown Report
    lines = [
        f"# Moltbook Intelligence & Alpha Briefing",
        f"**Generated:** {report_time} | **Coverage:** 5 Key Submolts\n",
        "## Executive Alpha & Trend Summary",
        "Key breakout discussions identified across agent feeds:\n"
    ]

    for hl in summary_highlights[:8]:
        lines.append(f"- **[m/{hl['submolt']}]** [{hl['title']}]({hl['url']}) by `@{hl['author']}` (👍 {hl['upvotes']})")

    lines.append("\n---\n")

    for sec in sections:
        lines.append(f"## m/{sec['name']} — {sec['category']}\n")
        if not sec["posts"]:
            lines.append("_No posts retrieved._\n")
            continue

        for p in sec["posts"]:
            lines.append(f"### [{p['title']}]({p['url']})")
            lines.append(f"**Author:** `@{p['author']}` | **Upvotes:** {p['upvotes']} | **Comments:** {p['comments']}\n")
            if p["preview"]:
                lines.append(f"> {p['preview']}\n")
        lines.append("")

    report_content = "\n".join(lines)
    
    out_dir = Path(r"i:\Scripts and Programs\moltbook-intel\reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp_slug = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_file = out_dir / f"intel_briefing_{timestamp_slug}.md"
    latest_file = out_dir / "latest_briefing.md"

    with open(report_file, "w", encoding="utf-8") as f:
        f.write(report_content)
    with open(latest_file, "w", encoding="utf-8") as f:
        f.write(report_content)

    print(f"[+] Report generated at: {report_file}")
    return report_file

if __name__ == "__main__":
    generate_report()
