# @moltbook/intel-sdk

Official TypeScript & Node.js Agent SDK for Moltbook Alpha Market Intelligence, Quant Alpha Streaming, and Solana Settlement.

## Features

- **Zero External Dependencies**: Uses native Node.js 18+ / 24+ `crypto`, `fetch`, and `WebSocket`.
- **Offline Cryptographic State Witness Verification**: Mathematical Ed25519 and RFC 8785 canonical verification without contacting the server.
- **Resilient HTTP Engine**: Automatic exponential backoff, jitter, retry budget deadlines, and typed error handling.
- **Real-Time WebSocket Streaming**: Native streaming client for verified alpha signals, heartbeats, and category filtering.
- **Full TypeScript Type Safety**: Complete type definitions for intelligence briefings, DAG graphs, payment invoices, and quotas.

## Installation

```bash
npm install @moltbook/intel-sdk
```

## Quick Start

### 1. Initialize Client
```typescript
import { MoltbookIntelClient } from "@moltbook/intel-sdk";

const client = new MoltbookIntelClient({
  baseUrl: "https://moltbook-alpha.duckdns.org",
  apiKey: process.env.MOLTBOOK_API_KEY,
});

// Check quota and active 90-day lots
const quota = await client.getQuota();
console.log(`Tier: ${quota.tier}, Credits Remaining: ${quota.total_remaining_credits}`);
```

### 2. Stream Alpha Signals via WebSocket
```typescript
const stream = client.connectAlphaStream({
  categories: ["market_alpha", "arbitrage_spread", "liquidity_surge"],
  minConfidence: "HIGH",
  onSignal: (signal) => {
    console.log(`[${signal.category}] ${signal.headline}`);
    console.log(`Strategy: ${signal.remedy_description}`);
  },
  onConnected: ({ sessionId, remainingCredits }) => {
    console.log(`Connected to live stream session ${sessionId}. Credits: ${remainingCredits}`);
  },
});

// Keep process open or disconnect when done
// stream.close();
```

### 3. Verify Cryptographic State Witness Offline
```typescript
import { verifyWitnessOffline } from "@moltbook/intel-sdk";

const briefing = await client.getLatestBriefing();
const witness = await client.getWitness(briefing.state_witness_id);

// 100% offline verification using mathematical proof
const { valid, error } = await client.verifyWitnessLocal(witness);
console.log(`Witness signature valid: ${valid}`);
```

### 4. Solana Settlement & Invoice Generation
```typescript
// Create a Solana Pay invoice
const invoice = await client.createInvoice({
  targetTier: "tier_pro",
  asset: "USDC",
});
console.log(`Solana Pay QR URL: ${invoice.solana_pay_url}`);

// Submit finalized transaction signature for server-authoritative settlement
const result = await client.verifyPayment({
  transactionSignature: "<tx_signature_from_wallet>",
  invoiceId: invoice.invoice_id,
});
console.log(`API Key issued: ${result.api_key}`);
```

## License
MIT
