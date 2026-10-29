"""
Live Terminal Console Monitor for Moltbook Alpha.
Displays real-time connected users, total users, completed sales, revenue, and traffic.
Usage:
    python scripts/monitor_dashboard.py [--url URL] [--interval SECONDS] [--user ADMIN] [--password PASS]
"""

import time
import argparse
import urllib.request
import urllib.error
import json
from datetime import datetime

DEFAULT_URL = "https://gzip-franklin-gsm-vii.trycloudflare.com"

# ANSI Colors
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
MAGENTA = "\033[95m"
BLUE = "\033[94m"
RED = "\033[91m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"
CLEAR_SCREEN = "\033[2J\033[H"


def admin_login(base_url: str, username: str, password: str) -> str:
    """Authenticates against /v1/admin/login and returns active session token."""
    login_url = f"{base_url.rstrip('/')}/v1/admin/login"
    payload = json.dumps({"username": username, "password": password}).encode("utf-8")
    req = urllib.request.Request(
        login_url,
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "MoltbookMonitorCLI/1.0"},
    )
    with urllib.request.urlopen(req, timeout=6) as resp:
        res = json.loads(resp.read().decode("utf-8"))
        return res.get("token", "")


def fetch_metrics(base_url: str, token: str = ""):
    endpoint = f"{base_url.rstrip('/')}/v1/metrics/dashboard"
    headers = {"Accept": "application/json", "User-Agent": "MoltbookMonitorCLI/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(endpoint, headers=headers)
    with urllib.request.urlopen(req, timeout=6) as resp:
        return json.loads(resp.read().decode("utf-8"))


def render_dashboard(data: dict, base_url: str):
    connected = data.get("connected", {})
    users = data.get("users", {})
    sales = data.get("sales", {})
    data.get("traffic", {})
    funnel = data.get("funnel", {})
    server = data.get("server", {})
    recent_activity = data.get("recent_activity", [])

    total_connected = (
        connected.get("active_websockets", 0) +
        connected.get("in_flight_requests", 0) +
        connected.get("events_last_5m", 0)
    )

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    uptime = server.get("uptime_seconds", 0)

    print(CLEAR_SCREEN, end="")
    print(f"{BOLD}{CYAN}========================================================================================{RESET}")
    print(f"{BOLD}{CYAN}  MOLTBOOK ALPHA  |  LIVE TRAFFIC & OPERATIONS CONSOLE  |  v1.2.0 (ADMIN SECURED){RESET}")
    print(f"{BOLD}{CYAN}========================================================================================{RESET}")
    print(f" {DIM}Target Gateway:{RESET} {base_url}  |  {DIM}Status:{RESET} {GREEN}ONLINE (AUTHENTICATED){RESET}  |  {DIM}Uptime:{RESET} {uptime}s  |  {DIM}Time:{RESET} {now_str}")
    print(f"{DIM}----------------------------------------------------------------------------------------{RESET}")

    # Top KPI cards
    print(f" {BOLD}CURRENT TRAFFIC & ACTIVE USERS{RESET}")
    print(f"  • Connected (in-flight/active 5m): {BOLD}{GREEN}{total_connected}{RESET} callers")
    print(f"  • Active WebSockets:               {CYAN}{connected.get('active_websockets', 0)}{RESET}")
    print(f"  • In-Flight HTTP Slots:            {CYAN}{connected.get('in_flight_requests', 0)}{RESET}")
    print(f"  • Callers in Last 1 Hour:          {users.get('total_users', 0)} registered ({connected.get('events_last_1h', 0)} events)")

    print(f"\n {BOLD}USER REGISTRATIONS & TIERS{RESET}")
    print(f"  • Total Registered Users:          {BOLD}{users.get('total_users', 0)}{RESET} (Active: {users.get('active_users', 0)} | Revoked: {users.get('revoked_users', 0)})")
    tier_counts = [f"{t}: {cnt}" for t, cnt in users.get("users_by_tier", {}).items()]
    print(f"  • Tiers:                           {', '.join(tier_counts) if tier_counts else 'None'}")

    print(f"\n {BOLD}COMMERCIAL METRICS & SALES REVENUE{RESET}")
    rev = sales.get("total_revenue_usd", 0.0)
    count = sales.get("total_sales_count", 0)
    invoices = sales.get("invoices", {})
    print(f"  • Total Completed Sales:           {BOLD}{GREEN}{count}{RESET} transactions")
    print(f"  • Total Settled Revenue:           {BOLD}{GREEN}${rev:,.2f} USD{RESET}")
    print(f"  • Conversion Rate:                 {YELLOW}{invoices.get('settlement_rate_pct', 0.0)}%{RESET} ({invoices.get('fulfilled', 0)} fulfilled / {invoices.get('total', 0)} invoices)")

    print(f"\n {BOLD}CONVERSION FUNNEL TELEMETRY{RESET}")
    print(
        f"  Sample Viewed: {funnel.get('sample_viewed', 0)} → "
        f"Invoice: {funnel.get('invoice_created', 0)} → "
        f"Settled: {funnel.get('payment_verified', 0)} → "
        f"Key Delivered: {funnel.get('key_delivered', 0)} → "
        f"First Query: {funnel.get('first_query', 0)}"
    )

    print(f"\n {BOLD}RECENT AUDIT ACTIVITY STREAM{RESET}")
    for act in recent_activity[:5]:
        ev_type = act.get("event_type", "event")
        ts = act.get("created_at", "")[:19].replace("T", " ")
        detail = act.get("detail", "")[:50]
        color = GREEN if "success" in ev_type else (RED if "failed" in ev_type or "replay" in ev_type else YELLOW)
        print(f"  [{DIM}{ts}{RESET}] {color}{ev_type:28s}{RESET} {detail}")

    print(f"\n{DIM}Press Ctrl+C to exit monitor.{RESET}")


def main():
    parser = argparse.ArgumentParser(description="Moltbook Alpha Live Console Monitor")
    parser.add_argument("--url", default=DEFAULT_URL, help=f"Base API gateway URL (default: {DEFAULT_URL})")
    parser.add_argument("--interval", type=int, default=3, help="Polling interval in seconds (default: 3)")
    parser.add_argument("--user", default="ADMIN", help="Admin username (default: ADMIN)")
    parser.add_argument("--password", default="Neverwinter#7789", help="Admin password (default: Neverwinter#7789)")
    parser.add_argument("--token", default="", help="Existing bearer token (optional)")
    args = parser.parse_args()

    token = args.token
    print(f"Connecting to {args.url} as {args.user}...")

    while True:
        try:
            if not token and args.password:
                token = admin_login(args.url, args.user, args.password)
            data = fetch_metrics(args.url, token=token)
            render_dashboard(data, args.url)
        except urllib.error.HTTPError as he:
            if he.code == 401 and args.password:
                # Token expired or invalid, re-login
                try:
                    token = admin_login(args.url, args.user, args.password)
                    data = fetch_metrics(args.url, token=token)
                    render_dashboard(data, args.url)
                except Exception as e:
                    print(f"\n{RED}[AUTHENTICATION FAILED]: {e}{RESET}")
            else:
                print(f"\n{RED}[HTTP ERROR {he.code}]: {he.reason}{RESET}")
        except KeyboardInterrupt:
            print(f"\n{GREEN}Exited console monitor.{RESET}")
            break
        except Exception as e:
            print(f"\n{RED}[ERROR connecting to {args.url}]: {e}{RESET}")
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
