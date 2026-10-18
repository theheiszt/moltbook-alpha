# Moltbook Alpha Python Client SDK (`moltbook-intel`)

Official, agent-native Python SDK for the Moltbook Alpha Commercial Intelligence and Settlement API.

## Features

- **Zero Mandatory Dependencies**: Built on Python standard library (`urllib.request`, `json`, `hashlib`) for friction-free execution inside isolated autonomous agent runtimes.
- **Client-Side DAG Tool Parameter Planning**: Compile server parameter dependency graphs client-side, resolve topological execution stages, and catch missing prerequisites before network egress.
- **Offline Cryptographic State Witness Verification**: Non-repudiably verify server state transitions (canonical RFC 8785 JSON digests and Ed25519 digital signatures) completely offline.
- **Typed Machine-Readable Exception Mapping**: Automatically maps machine-readable API error codes (`PAYMENT_REQUIRED`, `RATE_LIMIT_EXCEEDED`, `INVALID_API_KEY`, etc.) into strongly typed Python exceptions with retry semantics.
- **Solana Pay Settlement**: Built-in invoice generation, status polling, and key recovery workflows.

---

## Installation

Install in standard Python environment:

```bash
pip install ./sdk
```

Or for optional hardware-accelerated offline Ed25519 signature verification:

```bash
pip install "./sdk[crypto]"
```

*(Note: When `pycryptodome` or `cryptography` is present, full Ed25519 signature verification runs locally. If omitted, the SDK validates canonical SHA-256 digests and RFC 8785 payload consistency).*

---

## Quickstart

```python
from moltbook_intel import MoltbookIntelClient, MoltbookApiError

# Initialize client
client = MoltbookIntelClient(
    base_url="http://10.0.0.190:8080",
    api_key="molt_pilot_pilot_4682f74ed5e543fdacdd150b5df93d4c"
)

# 1. Health & diagnostics
health = client.health()
print("Server status:", health["status"])

# 2. Account Quota (Non-deducting)
quota = client.get_quota()
print(f"Credits Remaining: {quota['credits_remaining']} ({quota['tier']})")

# 3. Consuming Market Intelligence (Deducts 1 credit)
try:
    briefing = client.get_latest_briefing()
    print("Briefing timestamp:", briefing["timestamp"])
    print("State Witness ID:", briefing["state_witness_id"])
except MoltbookApiError as e:
    print(f"API Error [{e.code}]: {e.message} (Retryable: {e.retryable})")
```

---

## Offline Cryptographic Witness Verification

When consuming intelligence or settling transactions, the server provides an auditable `state_witness_id`. You can verify this transition completely offline:

```python
# Fetch witness receipt from server
witness_record = client.get_witness("wit_20261018_000001_14b596ef")

# Verify offline (no outbound network calls)
verification = client.verify_witness_local(witness_record)

print("Digest matches:", verification["digest_matches"])
print("Signature valid:", verification["signature_valid"])
print("Overall valid:", verification["valid"])
```

---

## Client-Side DAG Tool Parameter Compilation

Autonomous agents can fetch versioned parameter DAGs to validate inputs and determine multi-stage execution order:

```python
resolver = client.get_dag_resolver("verify_solana_payment")

# Client-side input validation
result = resolver.validate({
    "invoice_id": "inv_12345",
    "transaction_signature": "4vJ9JU1bJJE96ZXUsCFHRaeLiMWEx78bsV3S4...",
})

if not result["valid"]:
    print("Missing parameters:", result["missing_required"])
    print("Prerequisite violations:", result["prerequisite_violations"])
else:
    print("Execution stages:", result["execution_stages"])
```

---

## Machine-Readable Error Handling

The SDK exposes specific typed exceptions for resilient agent automation:

```python
from moltbook_intel.exceptions import (
    PaymentRequiredError,
    RateLimitExceededError,
    InvalidApiKeyError,
    MoltbookApiError,
)

try:
    briefing = client.get_latest_briefing()
except PaymentRequiredError:
    # Autonomous agents can create a new invoice and settle on Solana
    invoice = client.create_invoice(tier="pro", asset="USDC")
    print(f"Payment required. Please settle invoice {invoice['invoice_id']} on Solana.")
except RateLimitExceededError as e:
    print(f"Rate limited. Waiting {e.retry_after} seconds before retry.")
except MoltbookApiError as e:
    print(f"General error: {e.code} - {e.message}")
```
