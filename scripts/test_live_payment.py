"""
Live End-to-End Solana Pay Settlement Test.
Spends a micro-amount of SOL (0.00125 SOL / ~$0.12 USD) from the trading wallet
to test the complete Moltbook Alpha payment, reconciliation, and key fulfillment pipeline.
"""

import sys
import time
import json
import base64
import struct
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.instruction import AccountMeta, Instruction
from solders.message import Message
from solders.transaction import Transaction
from solders.hash import Hash

INVOICE_ID = "inv_ad2658e9ee8f168d60cf3747"
GATEWAY_URL = "https://nav-root-isa-glasgow.trycloudflare.com"
RPC_URL = "https://api.mainnet-beta.solana.com"
WALLET_FILE = Path("data/trading_wallet.json")

def rpc_call(method: str, params: list, url: str = RPC_URL):
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=12) as resp:
        return json.loads(resp.read().decode("utf-8"))

def main():
    print("=== Moltbook Alpha Live Solana Settlement Test ===")
    print(f"Target Invoice: {INVOICE_ID}")
    print(f"Gateway:        {GATEWAY_URL}")
    print(f"Solana RPC:     {RPC_URL}\n")

    # 1. Fetch Invoice
    inv_req = urllib.request.Request(f"{GATEWAY_URL}/v1/payments/invoice/{INVOICE_ID}")
    with urllib.request.urlopen(inv_req) as resp:
        inv = json.loads(resp.read().decode("utf-8"))
    
    print(f"[1/7] Verified Target Invoice:")
    print(f"      Tier:       {inv.get('tier')}")
    print(f"      Credits:    {inv.get('credits')}")
    print(f"      Amount:     {inv.get('amount_raw')} lamports ({inv.get('amount_raw')/1e9:.4f} SOL)")
    print(f"      Recipient:  {inv.get('recipient')}")
    print(f"      Reference:  {inv.get('reference')}")
    print(f"      Status:     {inv.get('status')}")
    print(f"      Expires:    {inv.get('expires_at')}\n")

    if inv.get("status") != "pending":
        print(f"[ABORT] Invoice is already {inv.get('status')}!")
        return

    # 2. Load Trading Wallet
    with open(WALLET_FILE) as f:
        kp_bytes = json.load(f)
    kp = Keypair.from_bytes(bytes(kp_bytes))
    payer_pubkey = kp.pubkey()
    print(f"[2/7] Loaded Trading Wallet: {payer_pubkey}")

    # Check balance
    bal_res = rpc_call("getBalance", [str(payer_pubkey)])
    lamports_avail = bal_res.get("result", {}).get("value", 0)
    print(f"      Available Balance: {lamports_avail / 1e9:.6f} SOL ({lamports_avail} lamports)\n")

    lamports_to_send = int(inv["amount_raw"])
    if lamports_avail < lamports_to_send + 10000:
        print("[ABORT] Insufficient funds in trading wallet!")
        return

    # 3. Build Solana Pay Transfer Instruction with Bound Reference
    treasury_pubkey = Pubkey.from_string(inv["recipient"])
    ref_pubkey = Pubkey.from_string(inv["reference"])
    sys_program = Pubkey.from_string("11111111111111111111111111111111")

    # System Program Transfer instruction: index 2, uint64 lamports
    ix_data = struct.pack("<IQ", 2, lamports_to_send)
    ix = Instruction(
        program_id=sys_program,
        data=ix_data,
        accounts=[
            AccountMeta(payer_pubkey, is_signer=True, is_writable=True),
            AccountMeta(treasury_pubkey, is_signer=False, is_writable=True),
            AccountMeta(ref_pubkey, is_signer=False, is_writable=False),
        ]
    )

    # Fetch recent blockhash
    bh_res = rpc_call("getLatestBlockhash", [{"commitment": "finalized"}])
    recent_blockhash_str = bh_res["result"]["value"]["blockhash"]
    recent_blockhash = Hash.from_string(recent_blockhash_str)
    print(f"[3/7] Constructed Solana Pay Transfer Instruction:")
    print(f"      Blockhash:  {recent_blockhash_str}")
    print(f"      Transfer:   {lamports_to_send} lamports -> {treasury_pubkey}")
    print(f"      Reference:  {ref_pubkey}\n")

    msg = Message([ix], payer_pubkey)
    tx = Transaction([kp], msg, recent_blockhash)
    raw_tx = bytes(tx)
    b64_tx = base64.b64encode(raw_tx).decode("utf-8")

    # 4. Pre-flight Simulation
    sim_res = rpc_call("simulateTransaction", [b64_tx, {"encoding": "base64", "sigVerify": True}])
    sim_val = sim_res.get("result", {}).get("value", {})
    if sim_val.get("err"):
        print(f"[ABORT] Simulation failed: {sim_val.get('err')}")
        return
    print(f"[4/7] Validator Simulation: PASS (Fee: {sim_val.get('fee')} lamports, Units: {sim_val.get('unitsConsumed')})\n")

    # 5. Broadcast to Solana Mainnet-Beta
    print(f"[5/7] Broadcasting Transaction to Solana Mainnet...")
    send_res = rpc_call("sendTransaction", [b64_tx, {"encoding": "base64", "preflightCommitment": "confirmed"}])
    tx_sig = send_res.get("result")
    if not tx_sig:
        print(f"[ABORT] Broadcast error: {send_res}")
        return
    print(f"      >> Transaction Signature: {tx_sig}")
    print(f"      >> Explorer: https://solscan.io/tx/{tx_sig}\n")

    # 6. Wait for On-Chain Confirmation
    print("[6/7] Awaiting on-chain confirmation...")
    confirmed = False
    for attempt in range(25):
        time.sleep(2)
        stat_res = rpc_call("getSignatureStatuses", [[tx_sig], {"searchTransactionHistory": True}])
        statuses = stat_res.get("result", {}).get("value", [])
        if statuses and statuses[0]:
            st = statuses[0]
            conf = st.get("confirmationStatus")
            print(f"      Block status: {conf} (err: {st.get('err')})")
            if conf in ("confirmed", "finalized") and not st.get("err"):
                confirmed = True
                break

    if not confirmed:
        print("[WARNING] Transaction confirmation taking longer than expected. Proceeding to verify API...")

    # 7. Settle & Fulfill via Moltbook Gateway
    print(f"\n[7/7] Fulfilling Settlement via Gateway: POST /v1/payments/verify-solana...")
    verify_payload = json.dumps({
        "signature": tx_sig,
        "invoice_id": INVOICE_ID,
    }).encode("utf-8")

    v_req = urllib.request.Request(
        f"{GATEWAY_URL}/v1/payments/verify-solana",
        data=verify_payload,
        headers={"Content-Type": "application/json", "User-Agent": "MoltbookTestSettler/1.0"}
    )
    
    api_key = None
    try:
        with urllib.request.urlopen(v_req, timeout=15) as v_resp:
            v_data = json.loads(v_resp.read().decode("utf-8"))
            print(f"      >> Settlement Status:    {v_data.get('status')}")
            print(f"      >> Tier Granted:         {v_data.get('tier')}")
            print(f"      >> Credits Balance:      {v_data.get('credits')} queries")
            print(f"      >> API Key Issued:       {v_data.get('api_key')}")
            print(f"      >> State Witness ID:     {v_data.get('state_witness_id')}")
            api_key = v_data.get("api_key")
    except Exception as e:
        print(f"      >> Verification call exception: {e}")
        # Check if the reconciler service already caught and fulfilled it!
        check_req = urllib.request.Request(f"{GATEWAY_URL}/v1/payments/invoice/{INVOICE_ID}")
        with urllib.request.urlopen(check_req) as c_resp:
            c_data = json.loads(c_resp.read().decode("utf-8"))
            print(f"      >> Reconciler status: {c_data.get('status')}")

    # Exercise Authenticated Request with the New API Key
    if api_key:
        print(f"\n=== Testing Live Intel Query with Minted Key ===")
        test_req = urllib.request.Request(
            f"{GATEWAY_URL}/v1/intel/opportunities",
            headers={"X-API-Key": api_key, "User-Agent": "MoltbookMicroClient/1.0"}
        )
        with urllib.request.urlopen(test_req, timeout=10) as t_resp:
            t_data = json.loads(t_resp.read().decode("utf-8"))
            print(f"[PASS] Authenticated Query Succeeded (HTTP {t_resp.status})!")
            print(f"       Remaining Quota Header: {t_resp.headers.get('X-Credits-Remaining')}")
            print(f"       Found {t_data.get('count')} market opportunities.")

    print("\n=== Live Settlement Assay Complete ===")

if __name__ == "__main__":
    main()
