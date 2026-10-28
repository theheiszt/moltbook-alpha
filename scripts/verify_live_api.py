import urllib.request
import json

BASE_URL = "https://gzip-franklin-gsm-vii.trycloudflare.com"

endpoints = [
    "/v1/health",
    "/v1/capabilities",
    "/v1/data-products",
    "/v1/data-products/moltbook-agent-intelligence-feed",
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
            if ep == "/v1/capabilities":
                print(f"[PASS] {ep} -> HTTP {resp.status} (service: {data.get('service')}, v{data.get('api_version')}, capabilities: {list(data.get('capabilities', {}).keys())})")
            elif ep == "/v1/data-products":
                print(f"[PASS] {ep} -> HTTP {resp.status} (found {data.get('count')} data products)")
                for p in data.get("products", []):
                    print(f"       -> {p.get('product_id')}: {p.get('name')} ({p.get('cost_credits')} credit)")
            elif ep == "/v1/data-products/moltbook-agent-intelligence-feed":
                print(f"[PASS] {ep} -> HTTP {resp.status} (schema: {data.get('output_schema', {}).get('title')}, access: {data.get('access_tier_required')})")
            elif ep == "/v1/intel/opportunities":
                print(f"[PASS] {ep} -> HTTP {resp.status} (found {data.get('count')} opportunities)")
            elif ep == "/v1/intel/signals/trading":
                print(f"[PASS] {ep} -> HTTP {resp.status} (found {data.get('count')} trading signals)")
            elif ep == "/v1/intel/sample":
                print(f"[PASS] {ep} -> HTTP {resp.status} (sample briefing unmetered)")
            elif ep == "/v1/tools":
                tools = [t['tool_name'] for t in data.get('tools', [])]
                print(f"[PASS] {ep} -> HTTP {resp.status} (tools registered: {tools})")
            else:
                print(f"[PASS] {ep} -> HTTP {resp.status} {data}")
    except Exception as e:
        print(f"[FAIL] {ep} -> {e}")
