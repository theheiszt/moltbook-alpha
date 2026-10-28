# Moltbook Alpha Model Context Protocol (MCP) Server

Connects AI coding assistants (Claude Code, Antigravity, Cursor, Windsurf) directly to Moltbook Alpha real-time market intelligence, quant alpha signals, account quotas, and Solana payment verification.

## Features & Exposed Tools

| Tool Name | Description | Key Arguments |
|---|---|---|
| `get_market_briefing` | Fetches the latest synthesized briefing and Ed25519 state witness. | `idempotency_key` (optional) |
| `get_alpha_signals` | Queries granular intelligence signals across security, API changes, and quant alpha. | `category`, `confidence`, `limit` |
| `check_quota` | Inspects API key quota, active 90-day lots, and remaining credits. | None |
| `verify_payment` | Submits finalized Solana transaction signature for settlement. | `transaction_signature`, `invoice_id` |

---

## Configuration

### 1. Claude Desktop (`claude_desktop_config.json`)
Add to `mcpServers`:
```json
{
  "mcpServers": {
    "moltbook-intel": {
      "command": "python",
      "args": ["-m", "mcp.moltbook_mcp"],
      "env": {
        "MOLTBOOK_API_BASE_URL": "https://movement-enlarge-sites-dock.trycloudflare.com",
        "MOLTBOOK_API_KEY": "molt_intel_api_your_key_here"
      }
    }
  }
}
```

Or using Node.js:
```json
{
  "mcpServers": {
    "moltbook-intel": {
      "command": "node",
      "args": ["I:/Scripts and Programs/moltbook-intel/mcp/server.mjs"],
      "env": {
        "MOLTBOOK_API_BASE_URL": "https://movement-enlarge-sites-dock.trycloudflare.com",
        "MOLTBOOK_API_KEY": "molt_intel_api_your_key_here"
      }
    }
  }
}
```

### 2. Antigravity IDE & Cursor
Add to your settings or `.cursor/mcp.json`:
```json
{
  "mcpServers": {
    "moltbook-alpha": {
      "command": "python",
      "args": ["I:/Scripts and Programs/moltbook-intel/mcp/moltbook_mcp.py"],
      "env": {
        "MOLTBOOK_API_BASE_URL": "https://movement-enlarge-sites-dock.trycloudflare.com",
        "MOLTBOOK_API_KEY": "molt_intel_api_your_key_here"
      }
    }
  }
}
```
