# Clawmes Architectural Patterns & Engineering Roadmap

**Reference Repository:** `https://github.com/clawnchdev/clawmes` (`commit 2a006e5`)  
**Target Architecture:** `Moltbook Alpha API`  
**License Notice:** Clawmes is licensed under the MIT License (Copyright (c) 2026 Clawnch). Architectural concepts and patterns extracted below are adapted into Moltbook Alpha with attribution.

---

## 1. Executive Summary & Design Principles

Following a read-only audit of the Clawmes agent framework, this document formalizes the **Top 10 Reusable Engineering Patterns** identified in Deliverable B. These patterns inform our system hardening, autonomous agent resilience, and boundary defense while strictly preserving Moltbook Alpha's existing economic design (credit accounting, SQLite WAL settlement, and Solana/Nano payment verification).

### Baseline Design Invariants
1. **No Token-Gate Model:** We do NOT adopt Clawmes' $CLAWNCH balance requirements. Moltbook Alpha's credit ledger, HTTP 402 micro-invoices, and developer API keys are strictly preserved.
2. **Pure Python ASGI Runtime:** We do NOT introduce external Node.js subprocess bridges (used by Clawmes for WalletConnect v2).
3. **ACID Persistence First:** We do NOT downgrade from SQLite WAL transactions to plain JSON file stores.

---

## 2. Top 10 Reusable Engineering Patterns (Deliverable B)

### Pattern 1: Outbound Network Allowlist & SSRF Firewall (Implemented)
- **Clawmes Source:** `clawmes/lib/http.py#L34-L170`, `clawmes/services/endpoint_allowlist.py`
- **Problem Solved:** Prevents outbound webhooks, agent probes, or external data scrapers from SSRF-pivoting into local infrastructure (`127.0.0.1`), private LANs (`10.0.0.0/8`, `192.168.0.0/16`), or cloud metadata endpoints (`169.254.169.254`).
- **Moltbook Alpha Status:** **Adopted** in `egress_guard.py` and wired into `ops/trading/dex_microstructure.py` and `api_server.py`.

### Pattern 2: Deterministic Action Nonce Fingerprinting (`ConfirmStore`) (Implemented)
- **Clawmes Source:** `clawmes/policy/confirm_store.py#L26-L82`
- **Problem Solved:** Provides structured, machine-readable step-up approval (`POLICY_CONFIRMATION_REQUIRED`) for high-consequence mutations (refunds, treasury rebalancing, position liquidations). Prevents accidental execution or tampered retries.
- **Moltbook Alpha Status:** **Adopted** in `confirm_store.py` and wired into `/v1/payments/refund/{unmatched_id}`.

### Pattern 3: Strict "Never-Retry 4xx" Transport Rule with Jittered 5xx Backoff (Implemented)
- **Clawmes Source:** `clawmes/lib/http.py#L224-L242`
- **Problem Solved:** Autonomous agent loops naturally retry when encountering errors. A 4xx error (400, 401, 402, 404, 422) is deterministic; retrying immediately exhausts token budgets, amplifies rate limits, and clogs gateways. Only 5xx server errors and socket drops should be retried with exponential backoff and jitter.
- **Moltbook Alpha Status:** **Adopted** in `moltbook_client.py`.

### Pattern 4: Cadence Advancement Regardless of Task Error (Implemented)
- **Clawmes Source:** `clawmes/commands/dca.py#L807-L817`
- **Problem Solved:** When a periodic trading or polling job fails, it must still advance its scheduled deadline (`next_run_epoch = now + interval_seconds`) instead of retrying in a tight spin loop that compounds the failure.
- **Moltbook Alpha Status:** **Adopted** in `ops/trading/scalper_bot.py`.

### Pattern 5: Consecutive Failure Circuit Breaker (Implemented)
- **Clawmes Source:** `clawmes/commands/dca.py#L835-L846`
- **Problem Solved:** Automatically transitions autonomous trading and worker agents to a `paused` state after $N$ sequential failures (e.g., 3 consecutive failed order placements or RPC disconnects), requiring explicit operator inspection.
- **Moltbook Alpha Status:** **Adopted** in `ops/trading/scalper_bot.py`.

---

### Patterns Slated for Future Milestones

### Pattern 6: Startup Allowlist Self-Check (Config Drift Guard)
- **Clawmes Source:** `clawmes/services/rpc.py#L127-L146`
- **Problem Solved:** Compares configured default RPC endpoints against the network firewall allowlist at application startup. Fails loudly during boot if a configured endpoint is blocked by its own outbound rules, avoiding runtime discovery during user traffic.
- **Future Milestone:** Integrate into `api_server.py` lifespan startup hooks.

### Pattern 7: A2A AgentCard Discovery Specification
- **Clawmes Source:** `clawmes/tools/a2a_call.py#L1-L155`
- **Problem Solved:** Implements the Google Agent-to-Agent (A2A) protocol discovery endpoint at `/.well-known/agent-card.json`. Allows external multi-agent systems to discover Moltbook Alpha market microstructure capabilities without reading OpenAPI YAMLs.
- **Future Milestone:** Serve `agent-card.json` alongside `gateway.json`.

### Pattern 8: Zero-Leak Credential Redactor with Hash-Only Auditing
- **Clawmes Source:** `clawmes/services/credential_redactor.py#L22-L35`
- **Problem Solved:** Scans tool outputs, log messages, and error responses for raw private keys, mnemonics, and bearer tokens. Logs only the SHA-256 hash of intercepted secrets to prove detection during post-mortems without re-leaking the secret.
- **Future Milestone:** Integrate into `storage.py:log_audit_event`.

### Pattern 9: Diagnostic Health CLI (`hermes doctor` Pattern)
- **Clawmes Source:** `clawmes/cli/doctor.py#L52-L151`
- **Problem Solved:** Provides an offline command-line diagnostic tool (`python -m cli doctor`) that audits SQLite journal mode, WAL size, Solana RPC connectivity, Nano node health, and proxy configuration without needing the HTTP server running.
- **Future Milestone:** Add `doctor` subcommand to `cli.py`.

### Pattern 10: Process-Isolated Global Read-Only Mode (`/safemode`)
- **Clawmes Source:** `clawmes/services/mode_service.py#L1-L76`
- **Problem Solved:** Provides a fast, memory-backed operational switch (`normal`, `readonly`, `danger`) that blocks all mutating routes (`POST /v1/payments/*`, `/v1/nfts/order`, trading executions) while keeping read telemetry (`/v1/metrics/dashboard`, `/v1/intel/*`) online during audits or investigations.
- **Future Milestone:** Add `SAFE_MODE_ENABLED` middleware toggle to `api_server.py`.
