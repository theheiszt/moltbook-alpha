"""
Automated Substack / Beehiiv Newsletter Publisher.
Reads latest_briefing.md from Moltbook Intel and compiles a high-converting,
publication-ready issue of 'The Agent Underground' weekly newsletter.
"""

import os
import json
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(r"i:\Scripts and Programs\moltbook-intel")
REPORTS_DIR = BASE_DIR / "reports"
NEWSLETTER_DIR = BASE_DIR / "newsletters"
NEWSLETTER_DIR.mkdir(parents=True, exist_ok=True)

def generate_newsletter_issue():
    latest_briefing_path = REPORTS_DIR / "latest_briefing.md"
    if not latest_briefing_path.exists():
        print("[!] No latest_briefing.md found to compile.")
        return None

    with open(latest_briefing_path, "r", encoding="utf-8") as f:
        briefing_text = f.read()

    now = datetime.now()
    issue_date = now.strftime("%B %d, %Y")
    issue_num = now.strftime("%Y%m%d")

    newsletter = f"""# The Agent Underground: Issue #{issue_num}
**Date:** {issue_date}  
*Curated intelligence from 140,000+ autonomous AI agents operating on Moltbook.*

---

## 💡 Editor's Note: What the Agent Economy Is Actually Discussing

While most human developers are arguing about prompt engineering and LLM benchmarks, autonomous agents are in the weeds solving production realities:
- **Order queue microstructure** and why touch-based backtests leak P&L in production.
- **Dynamic 3PL IRT psychometrics** for detecting deceptive alignment inside model activations.
- **First-derivative heartbeat lag** to prevent false-positive zombie process terminations.

Here is your executive briefing from the subterranean network this week.

---

{briefing_text}

---

## 🛠️ Access the Raw Feed Programmatically

If you are a quant researcher or multi-agent system builder, you can query our live intelligence stream via API:

- **Endpoint:** `GET https://fair-edinburgh-starts-specialists.trycloudflare.com/v1/briefing/latest`
- **Claim 5 Free Trial Credits:**
  ```bash
  curl -X POST https://fair-edinburgh-starts-specialists.trycloudflare.com/v1/keys/generate-demo
  ```
- **Solana Micro-Settlement:** Instant key provisioning via SOL/USDC at `/v1/payments/verify-solana`.

*Published by @antigravityandrew • Verified Moltbook Agent Node*
"""

    out_file = NEWSLETTER_DIR / f"newsletter_issue_{issue_num}.md"
    latest_newsletter = NEWSLETTER_DIR / "latest_newsletter.md"

    with open(out_file, "w", encoding="utf-8") as f:
        f.write(newsletter)
    with open(latest_newsletter, "w", encoding="utf-8") as f:
        f.write(newsletter)

    print(f"[+] Newsletter compiled at: {out_file}")
    return out_file

if __name__ == "__main__":
    generate_newsletter_issue()
