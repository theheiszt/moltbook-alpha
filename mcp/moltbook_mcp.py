#!/usr/bin/env python3
"""
Moltbook Alpha — Model Context Protocol (MCP) Server.
Standard JSON-RPC 2.0 stdio server providing AI coding assistants (Claude Code, Antigravity,
Cursor, Windsurf) with real-time access to verified Moltbook Alpha market intelligence,
quant signals, account quotas, and Solana payment verification.
"""

import sys
import json
import os
from typing import Dict, Any

# Ensure repository root is on Python path
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from sdk.moltbook_intel import MoltbookIntelClient  # noqa: E402


SERVER_NAME = "moltbook-alpha-mcp"
SERVER_VERSION = "2.0.0"
PROTOCOL_VERSION = "2024-11-05"

TOOLS_DEFINITION = [
    {
        "name": "get_market_briefing",
        "description": "Fetches the latest synthesized Moltbook Alpha market intelligence briefing, breakout findings, security notices, and cryptographic Ed25519 state witness.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "idempotency_key": {
                    "type": "string",
                    "description": "Optional unique client token to prevent duplicate credit charges on retries.",
                }
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_alpha_signals",
        "description": "Queries granular intelligence signals across security advisories, operational alerts, API protocol mutations, cross-pool arbitrage, and liquidity surges.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": [
                        "security_advisory",
                        "operational_failure",
                        "api_change",
                        "architecture_pattern",
                        "market_alpha",
                        "liquidity_surge",
                        "volatility_expansion",
                        "arbitrage_spread",
                    ],
                    "description": "Optional category filter.",
                },
                "confidence": {
                    "type": "string",
                    "enum": ["LOW", "MODERATE", "HIGH", "VERIFIED"],
                    "description": "Minimum confidence threshold.",
                },
                "limit": {
                    "type": "integer",
                    "default": 15,
                    "description": "Maximum number of signals to return (1-50).",
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "check_quota",
        "description": "Inspects the client API key account tier, active 90-day credit lots, and remaining credit balance without spending credits.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "verify_payment",
        "description": "Submits a finalized Solana transaction signature for server-authoritative settlement, granting 90-day top-up credits or recurring API entitlements.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "transaction_signature": {
                    "type": "string",
                    "description": "Base58-encoded Solana transaction signature (80-90 characters).",
                },
                "invoice_id": {
                    "type": "string",
                    "description": "Optional invoice ID associated with the payment request.",
                },
                "asset": {
                    "type": "string",
                    "default": "USDC",
                    "enum": ["USDC", "SOL"],
                    "description": "Payment asset used.",
                },
            },
            "required": ["transaction_signature"],
            "additionalProperties": False,
        },
    },
]


class MoltbookMCPServer:
    def __init__(self):
        base_url = os.getenv("MOLTBOOK_API_BASE_URL", "http://127.0.0.1:8080")
        api_key = os.getenv("MOLTBOOK_API_KEY")
        self.client = MoltbookIntelClient(base_url=base_url, api_key=api_key)

    def handle_request(self, req: Dict[str, Any]) -> Dict[str, Any]:
        msg_id = req.get("id")
        method = req.get("method")
        params = req.get("params", {})

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {
                        "name": SERVER_NAME,
                        "version": SERVER_VERSION,
                    },
                },
            }

        elif method == "notifications/initialized":
            return None

        elif method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {"tools": TOOLS_DEFINITION},
            }

        elif method == "tools/call":
            tool_name = params.get("name")
            args = params.get("arguments", {})
            return self._call_tool(msg_id, tool_name, args)

        else:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {
                    "code": -32601,
                    "message": f"Method not found: {method}",
                },
            }

    def _call_tool(self, msg_id: Any, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        try:
            if tool_name == "get_market_briefing":
                res = self.client.get_latest_briefing(idempotency_key=args.get("idempotency_key"))
                text = json.dumps(res, indent=2)
            elif tool_name == "get_alpha_signals":
                signals = self.client.get_signals(
                    category=args.get("category"),
                    confidence=args.get("confidence"),
                    limit=min(int(args.get("limit", 15)), 50),
                )
                text = json.dumps({"count": len(signals), "signals": signals}, indent=2)
            elif tool_name == "check_quota":
                quota = self.client.get_quota()
                text = json.dumps(quota, indent=2)
            elif tool_name == "verify_payment":
                res = self.client.verify_payment(
                    transaction_signature=args["transaction_signature"],
                    invoice_id=args.get("invoice_id"),
                    asset=args.get("asset", "USDC"),
                )
                text = json.dumps(res, indent=2)
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {
                        "code": -32602,
                        "message": f"Unknown tool: {tool_name}",
                    },
                }

            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [{"type": "text", "text": text}],
                },
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "isError": True,
                    "content": [{"type": "text", "text": f"Tool execution error: {e!s}"}],
                },
            }

    def run(self):
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
                resp = self.handle_request(req)
                if resp is not None:
                    sys.stdout.write(json.dumps(resp) + "\n")
                    sys.stdout.flush()
            except Exception as e:
                err_resp = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"Parse error: {e!s}"},
                }
                sys.stdout.write(json.dumps(err_resp) + "\n")
                sys.stdout.flush()


if __name__ == "__main__":
    server = MoltbookMCPServer()
    server.run()
