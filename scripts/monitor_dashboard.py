"""
Live Terminal Console Monitor for Moltbook Alpha.
Displays real-time connected users, total users, completed sales, revenue, and traffic.
Usage:
    python scripts/monitor_dashboard.py [--url URL] [--interval SECONDS]
"""

import time
import argparse
import urllib.request
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


def fetch_metrics(base_url: str):
    endpoint = f"{base_url.rstrip('/')}/v1/metrics/dashboard"
    req = urllib.request.Request(endpoint, headers={"Accept": "application/json", "User-Agent": "MoltbookMonitorCLI/1.0"})
    with urllib.request.urlopen(req, timeout=6) as resp:
        return json.loads(resp.read().decode("utf-8"))


def render_dashboard(data: dict, base_url: str):
    connected = data.get("connected", {})
    users = data.get("users", {})
    sales = data.get("sales", {})
    traffic = data.get("traffic", {})
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
    print(f"{BOLD}{CYAN}  MOLTBOOK ALPHA  |  LIVE TRAFFIC & OPERATIONS CONSOLE  |  v1.2.0{RESET}")
    print(f"{BOLD}{CYAN}========================================================================================{RESET}")
    print(f" {DIM}Target Gateway:{RESET} {base_url}  |  {DIM}Status:{RESET} {GREEN}ONLINE{RESET}  |  {DIM}Uptime:{RESET} {uptime}s  |  {DIM}Time:{RESET} {now_str}")
    print(f"{DIM}----------------------------------------------------------------------------------------{RESET}")

    # Row 1: KPI Summary Cards
    print(f"\n{BOLD} [1] REAL-TIME KPIS & ACTIVITY{RESET}")
    print(f"  {BOLD}Connected Users:{RESET}    {GREEN}{total_connected:4d}{RESET}  (WebSockets: {connected.get('active_websockets', 0)}, In-Flight: {connected.get('in_flight_requests', 0)}, 5m Events: {connected.get('events_last_5m', 0)})")
    print(f"  {BOLD}Total Registered:{RESET}   {BLUE}{users.get('total_users', 0):4d}{RESET}  (Active: {GREEN}{users.get('active_users', 0)}{RESET}, Revoked: {RED}{users.get('revoked_users', 0)}{RESET})")
    print(f"  {BOLD}Total Sales:{RESET}        {YELLOW}{sales.get('total_sales_count', 0):4d}{RESET}  (USD Revenue: {GREEN}${sales.get('total_revenue_usd', 0.0):.2f}{RESET})")

    invoices = sales.get("invoices", {})
    print(f"  {BOLD}Invoices Pipeline:{RESET}  {MAGENTA}{invoices.get('settlement_rate_pct', 0.0):.1f}%{RESET} Conversion (Fulfilled: {GREEN}{invoices.get('fulfilled', 0)}{RESET}, Pending: {YELLOW}{invoices.get('pending', 0)}{RESET}, Expired: {DIM}{invoices.get('expired', 0)}{RESET})")

    # Row 2: Sales Breakdown by Tier
    print(f"\n{BOLD} [2] COMPLETED SALES BY TIER{RESET}")
    tier_map = sales.get("sales_by_tier", {})
    for tier, count in sorted(tier_map.items(), key=lambda x: x[1], reverse=True):
        bar = "#" * min(30, int(count / 25))
        print(f"  - {tier:18s}: {count:4d} sales  {CYAN}{bar}{RESET}")

    # Row 3: Conversion Funnel Telemetry
    print(f"\n{BOLD} [3] 5-STAGE CUSTOMER CONVERSION FUNNEL{RESET}")
    print(f"  Sample Viewed    : {CYAN}{funnel.get('sample_viewed', 0):5d}{RESET} (Unmetered Evaluation)")
    print(f"  Invoice Created  : {BLUE}{funnel.get('invoice_created', 0):5d}{RESET} (Checkout Initiated)")
    print(f"  Payment Verified : {YELLOW}{funnel.get('payment_verified', 0):5d}{RESET} (Blockchain Settlement)")
    print(f"  Key Delivered    : {MAGENTA}{funnel.get('key_delivered', 0):5d}{RESET} (API Credential Bound)")
    print(f"  First Query      : {GREEN}{funnel.get('first_query', 0):5d}{RESET} (Autonomous API Consumption)")
    print(f"  Top-Up Purchased : {CYAN}{funnel.get('topup_purchased', 0):5d}{RESET} (Repeat / Expansion)")

    # Row 4: HTTP Status & Top Endpoints
    status_codes = traffic.get("status_codes", {})
    total_req = traffic.get("total_requests", 0)
    print(f"\n{BOLD} [4] TRAFFIC & HTTP CODES ({total_req} requests logged){RESET}")
    print(f"  2xx Success: {GREEN}{status_codes.get('2xx', 0)}{RESET}  |  4xx Client: {YELLOW}{status_codes.get('4xx', 0)}{RESET}  |  5xx Server: {RED}{status_codes.get('5xx', 0)}{RESET}")

    top_ep = traffic.get("top_endpoints", [])
    if top_ep:
        print("  Top Routes:")
        for ep, hits in top_ep[:4]:
            print(f"    * {ep:32s}: {hits:4d} hits")

    # Row 5: Live Activity Log (Last 5 events)
    print(f"\n{BOLD} [5] RECENT EVENT STREAM (Last 5 events){RESET}")
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
    args = parser.parse_args()

    print(f"Connecting to {args.url}...")
    while True:
        try:
            data = fetch_metrics(args.url)
            render_dashboard(data, args.url)
        except KeyboardInterrupt:
            print(f"\n{GREEN}Exited console monitor.{RESET}")
            break
        except Exception as e:
            print(f"\n{RED}[ERROR connecting to {args.url}]: {e}{RESET}")
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
