"""
MALPHA Token Management Engine.
Manages launch tickets, on-chain fee collections, and trading analytics
for the $MALPHA agentic cryptocurrency on Robinhood Chain / Clawnch.
"""

import json
import urllib.request
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "moltbook"
WALLET_FILE = CONFIG_DIR / "evm_wallet.json"
CLAWNCH_CRED_FILE = CONFIG_DIR / "clawnch_credentials.json"
BASE_DIR = Path(__file__).resolve().parent
TOKEN_STATE_FILE = BASE_DIR / "token_state.json"

CLAWNCH_BASE = "https://www.clawn.ch"

def get_agent_credentials():
    with open(WALLET_FILE, "r", encoding="utf-8") as f:
        wdata = json.load(f)
    with open(CLAWNCH_CRED_FILE, "r", encoding="utf-8") as f:
        cdata = json.load(f)
    return wdata, cdata

def request_fresh_launch_ticket():
    wdata, cdata = get_agent_credentials()
    api_key = cdata["api_key"]
    wallet = wdata["address"]

    payload = {
        "agentWallet": wallet,
        "name": "Moltbook Alpha",
        "symbol": "MALPHA",
        "description": "Decentralized market intelligence token for autonomous agents operating the Moltbook Alpha network.",
        "image": "https://raw.githubusercontent.com/multiverse-assets/assets/main/alpha_logo.png"
    }

    req = urllib.request.Request(
        f"{CLAWNCH_BASE}/api/robinhood/ticket",
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "MoltbookAlphaEngine/1.0"
        }
    )

    with urllib.request.urlopen(req, timeout=15) as resp:
        ticket_data = json.loads(resp.read().decode())

    # Save to state
    with open(TOKEN_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(ticket_data, f, indent=2)

    print("[+] Fresh launch ticket generated for $MALPHA!")
    print(f"    Router: {ticket_data['data']['to']}")
    print(f"    Creation Fee: {ticket_data['meta']['creationFeeWei']} wei")
    print(f"    Deposit Address (Path B): {ticket_data['meta']['depositAddress']}")
    return ticket_data

def check_token_status():
    if not TOKEN_STATE_FILE.exists():
        print("[!] No token state found. Generating fresh ticket...")
        return request_fresh_launch_ticket()

    with open(TOKEN_STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    wdata, _ = get_agent_credentials()
    wallet = wdata["address"]

    # Check RHC balance
    rpc_payload = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_getBalance",
        "params": [wallet, "latest"]
    }).encode()
    rpc_req = urllib.request.Request(
        "https://rpc.mainnet.chain.robinhood.com",
        data=rpc_payload,
        headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
    )
    try:
        rpc_resp = json.loads(urllib.request.urlopen(rpc_req, timeout=10).read().decode())
        bal_wei = int(rpc_resp.get("result", "0x0"), 16)
        bal_eth = bal_wei / 1e18
    except Exception:
        bal_wei = 0
        bal_eth = 0.0

    print("=== MALPHA Token & Agent Wallet Status ===")
    print(f"Agent Wallet: {wallet}")
    print(f"RHC Native ETH Balance: {bal_eth:.6f} ETH")
    print(f"Bags Creation Fee: {state['meta']['creationFeeWei']} wei (FREE to launch)")
    print(f"Deposit Address: {state['meta']['depositAddress']}")
    return state

if __name__ == "__main__":
    check_token_status()
