#!/usr/bin/env node
/**
 * Moltbook Alpha — Model Context Protocol (MCP) Node.js Server.
 */

import readline from "node:readline";
import { MoltbookIntelClient } from "../sdk-ts/dist/index.js";

const SERVER_NAME = "moltbook-alpha-mcp-node";
const SERVER_VERSION = "2.0.0";
const PROTOCOL_VERSION = "2024-11-05";

const client = new MoltbookIntelClient({
  baseUrl: process.env.MOLTBOOK_API_BASE_URL || "http://127.0.0.1:8080",
  apiKey: process.env.MOLTBOOK_API_KEY,
});

const TOOLS = [
  {
    name: "get_market_briefing",
    description: "Fetches the latest synthesized Moltbook Alpha market intelligence briefing and Ed25519 state witness.",
    inputSchema: {
      type: "object",
      properties: {
        idempotency_key: { type: "string", description: "Optional idempotency key." },
      },
    },
  },
  {
    name: "get_alpha_signals",
    description: "Queries granular intelligence signals across security advisories, operational alerts, arbitrage, and volume surges.",
    inputSchema: {
      type: "object",
      properties: {
        category: { type: "string" },
        confidence: { type: "string" },
        limit: { type: "integer", default: 15 },
      },
    },
  },
  {
    name: "check_quota",
    description: "Inspects API key quota, active 90-day lots, and remaining credits.",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "verify_payment",
    description: "Submits a Solana transaction signature for settlement.",
    inputSchema: {
      type: "object",
      properties: {
        transaction_signature: { type: "string" },
        invoice_id: { type: "string" },
        asset: { type: "string", default: "USDC" },
      },
      required: ["transaction_signature"],
    },
  },
];

async function handleRequest(req) {
  const { id, method, params } = req;

  if (method === "initialize") {
    return {
      jsonrpc: "2.0",
      id,
      result: {
        protocolVersion: PROTOCOL_VERSION,
        capabilities: { tools: {} },
        serverInfo: { name: SERVER_NAME, version: SERVER_VERSION },
      },
    };
  }

  if (method === "notifications/initialized") {
    return null;
  }

  if (method === "tools/list") {
    return {
      jsonrpc: "2.0",
      id,
      result: { tools: TOOLS },
    };
  }

  if (method === "tools/call") {
    const { name, arguments: args } = params || {};
    try {
      let result;
      if (name === "get_market_briefing") {
        result = await client.getLatestBriefing(args?.idempotency_key);
      } else if (name === "get_alpha_signals") {
        result = await client.getSignals(args || {});
      } else if (name === "check_quota") {
        result = await client.getQuota();
      } else if (name === "verify_payment") {
        result = await client.verifyPayment({
          transactionSignature: args.transaction_signature,
          invoiceId: args.invoice_id,
          asset: args.asset || "USDC",
        });
      } else {
        return {
          jsonrpc: "2.0",
          id,
          error: { code: -32602, message: `Unknown tool: ${name}` },
        };
      }

      return {
        jsonrpc: "2.0",
        id,
        result: {
          content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
        },
      };
    } catch (err) {
      return {
        jsonrpc: "2.0",
        id,
        result: {
          isError: true,
          content: [{ type: "text", text: `Tool error: ${err.message}` }],
        },
      };
    }
  }

  return {
    jsonrpc: "2.0",
    id,
    error: { code: -32601, message: `Method not found: ${method}` },
  };
}

const rl = readline.createInterface({ input: process.stdin, output: process.stdout, terminal: false });

rl.on("line", async (line) => {
  const trimmed = line.trim();
  if (!trimmed) return;
  try {
    const req = JSON.parse(trimmed);
    const res = await handleRequest(req);
    if (res) {
      process.stdout.write(JSON.stringify(res) + "\n");
    }
  } catch (err) {
    process.stdout.write(JSON.stringify({
      jsonrpc: "2.0",
      id: null,
      error: { code: -32700, message: `Parse error: ${err.message}` },
    }) + "\n");
  }
});
