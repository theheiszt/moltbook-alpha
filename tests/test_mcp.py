"""
Tests for Moltbook Alpha Model Context Protocol (MCP) Server.
Verifies JSON-RPC 2.0 handshake, tool schema discovery, and tool execution.
"""

from mcp.moltbook_mcp import MoltbookMCPServer


def test_mcp_initialize_handshake():
    server = MoltbookMCPServer()
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-suite", "version": "1.0"},
        },
    }
    resp = server.handle_request(req)
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 1
    result = resp["result"]
    assert result["protocolVersion"] == "2024-11-05"
    assert "tools" in result["capabilities"]
    assert result["serverInfo"]["name"] == "moltbook-alpha-mcp"


def test_mcp_tools_list():
    server = MoltbookMCPServer()
    req = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/list",
        "params": {},
    }
    resp = server.handle_request(req)
    assert resp["id"] == 2
    tools = resp["result"]["tools"]
    tool_names = {t["name"] for t in tools}
    assert "get_market_briefing" in tool_names
    assert "get_alpha_signals" in tool_names
    assert "check_quota" in tool_names
    assert "verify_payment" in tool_names


def test_mcp_tools_call_signals(monkeypatch):
    server = MoltbookMCPServer()

    # Mock client.get_signals
    def mock_get_signals(category=None, confidence=None, limit=15):
        return [
            {
                "signal_id": "sig_mock_1",
                "category": "arbitrage_spread",
                "headline": "SOL/USDC DEX spread 0.45%",
                "confidence": "VERIFIED",
            }
        ]

    monkeypatch.setattr(server.client, "get_signals", mock_get_signals)

    req = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "get_alpha_signals",
            "arguments": {"category": "arbitrage_spread", "limit": 5},
        },
    }
    resp = server.handle_request(req)
    assert resp["id"] == 3
    content = resp["result"]["content"]
    assert len(content) == 1
    assert content[0]["type"] == "text"
    assert "sig_mock_1" in content[0]["text"]


def test_mcp_unknown_tool_and_method():
    server = MoltbookMCPServer()

    # Unknown tool
    req_tool = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {"name": "non_existent_tool", "arguments": {}},
    }
    resp_tool = server.handle_request(req_tool)
    assert "error" in resp_tool
    assert resp_tool["error"]["code"] == -32602

    # Unknown method
    req_method = {
        "jsonrpc": "2.0",
        "id": 5,
        "method": "unknown/method",
        "params": {},
    }
    resp_method = server.handle_request(req_method)
    assert "error" in resp_method
    assert resp_method["error"]["code"] == -32601
