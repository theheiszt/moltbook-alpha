import urllib.request
import json

BASE_URL = "https://gzip-franklin-gsm-vii.trycloudflare.com"

endpoints = [
    "/v1/health",
    "/v1/intel/opportunities",
    "/v1/intel/signals/trading",
    "/v1/intel/sample",
    "/v1/tools",
]

print(f"Testing Live Endpoints over Cloudflare Gateway: {BASE_URL}")
for ep in endpoints:
    url = f"{BASE_URL}{ep}"
    req = urllib.request.Request(url, headers={"User-Agent": "MoltbookVerifier/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if ep == "/v1/intel/opportunities":
                print(f"[PASS] {ep} -> HTTP {resp.status} (found {data.get('count')} opportunities)")
                for opp in data.get("opportunities", [])[:2]:
                    print(f"       -> {opp.get('pair')}: {opp.get('buy_venue')} -> {opp.get('sell_venue')} (Net Profit: +{opp.get('net_profit_pct')}%, Spread: {opp.get('gross_spread_bps')} bps)")
            elif ep == "/v1/intel/signals/trading":
                print(f"[PASS] {ep} -> HTTP {resp.status} (found {data.get('count')} trading signals)")
                for sig in data.get("trading_signals", [])[:2]:
                    print(f"       -> {sig.get('asset')} {sig.get('action')} @ ${sig.get('entry_price')} (Targets: {sig.get('price_targets')}, Stop: ${sig.get('stop_loss')}, Conf: {sig.get('confidence_score')})")
            elif ep == "/v1/intel/sample":
                print(f"[PASS] {ep} -> HTTP {resp.status} (sample briefing unmetered, signals: {len(data.get('trading_signals', []))}, opps: {len(data.get('opportunities', []))})")
            elif ep == "/v1/tools":
                tools = [t['tool_name'] for t in data.get('tools', [])]
                print(f"[PASS] {ep} -> HTTP {resp.status} (tools registered: {tools})")
            else:
                print(f"[PASS] {ep} -> HTTP {resp.status} {data}")
    except Exception as e:
        print(f"[FAIL] {ep} -> {e}")
