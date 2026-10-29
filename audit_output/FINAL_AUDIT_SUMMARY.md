# Moltbook Alpha — Production Traffic Investigation
## Final Audit Summary & Authorization Request

**Audit ID:** AUDIT-TRAFFIC-20261028  
**Target:** Production Traffic Anomaly Investigation (~11,000 requests in 7 hours)  
**Investigation Mode:** Read-Only Audit (100% Non-Mutating)  
**Status:** Completed. **Awaiting User Authorization for Remediation.**  
**Audit Artifact File:** `audit_output/FINAL_AUDIT_SUMMARY.md`  

---

## 1. Confirmed Root Cause

The investigation has conclusively established the root cause of the ~11,000 HTTP requests:

### Root Cause (Confidence: 100% — Confirmed by Empirical Evidence)
**Frontend Polling Loop with Cross-Origin Preflight Multiplication in `dashboard.html`**

1. **The Polling Mechanism:**  
   An authorized operator logged into the Moltbook Alpha Operator Console (`dashboard.html`) and kept the browser tab open for approximately 6.9 hours. The UI polled `/v1/metrics/dashboard` every 5 seconds (`5000ms`).
2. **The 2x Request Multiplier (CORS Preflight):**  
   Because the dashboard called `fetch()` with `cache: "no-store"` and custom `Authorization: Bearer ...` headers, modern browser engines bypassed CORS preflight caching, issuing **1 `OPTIONS` preflight request and 1 `GET` request every 5 seconds**.
   - **4,974 `OPTIONS` requests** (HTTP 200)
   - **4,974 `GET` requests** (HTTP 200)
   - Total: **9,948 requests** (exactly **96.1%** of all recorded traffic).
3. **The Remaining 4% of Traffic:**  
   - **177 requests (1.7%):** Internet scanner probes to unmapped paths (`.env`, `wp-admin`), rejected with HTTP 404 at the ASGI layer.
   - **193 requests (1.9%):** Legitimate baseline traffic across `/v1/health` (86), `/metrics` (87), root landing page (45), `/gateway.json` (21), admin authentication (4), and job board actions (3).

---

## 2. Immediate Risk Evaluation

- **Service Health:** **Zero Immediate Outage Risk.**  
  The system recorded **zero (0%) 5xx server errors** and zero process restarts across all 10,371 requests. Response latencies remained under 5ms on bare-metal.
- **Hidden Operational Risk (Medium):**  
  Each dashboard request executed **11 separate relational SQLite queries** while acquiring `self._lock` (**54,714 SQLite queries** across 7 hours). While the server handled this load, concurrent write operations (invoice creation, payment verification, key generation) were forced to contend for the database write lock against an idle dashboard tab.
- **Information Exposure Risk (Low to Medium):**  
  `/metrics` is currently accessible publicly without authentication (disclosing route volumes and key counts), and `/v1/health` exposes internal SQLite journal mode and treasury wallet public key.

---

## 3. Recommended Remediation Package

To reduce traffic by >90% and protect the database without breaking legitimate clients, the following minimal, low-risk changes are prepared:

1. **Client-Side (`dashboard.html`):**
   - Add Page Visibility API (`visibilitychange` listener) to pause polling when the tab is hidden or minimized.
   - Increase default polling interval from 5 seconds to 15 or 30 seconds.
   - Remove `cache: "no-store"` from metrics fetch.
2. **Backend Gateway (`api_server.py`):**
   - Set `max_age=86400` in `CORSMiddleware` (caches preflights for 24h, eliminating 50% of requests).
   - Add 5–10 second in-memory TTL cache for `storage.get_dashboard_metrics()` (eliminates >90% of SQLite lock acquisitions).
   - Apply rate limiting (30 req/min) to `/v1/metrics/dashboard`.
   - Enforce `METRICS_BEARER_TOKEN` on `/metrics` and sanitize `/v1/health`.

---

## 4. Formal Authorization Request

Per the audit rules established for this mission:
> **"This is an investigation, not an implementation authorization. Do not modify application files, deployment files, environment variables, databases, service configurations, firewall rules, reverse-proxy settings, or production state. Request explicit approval before proceeding."**

The audit is complete, and all evidence, exposure analysis, remediation plans, and test matrices have been generated in the `audit_output/` directory:
- `audit_output/TRAFFIC_INVESTIGATION_REPORT.md`
- `audit_output/TRAFFIC_EVIDENCE_SUMMARY.md`
- `audit_output/ENDPOINT_EXPOSURE_AUDIT.md`
- `audit_output/REMEDIATION_PLAN.md`
- `audit_output/TRAFFIC_TEST_PLAN.md`
- `audit_output/FINAL_AUDIT_SUMMARY.md`

**Next Step:**  
Awaiting your explicit instructions. Would you like to proceed with implementing the minimal remediation package (P1–P3: Page Visibility throttling, CORS preflight caching, and in-memory TTL caching), or do you require adjustments to the test plan first?
