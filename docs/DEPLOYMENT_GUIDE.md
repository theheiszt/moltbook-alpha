# Moltbook Alpha — Production Deployment & Operational Runbook

**Document Version:** 1.0.0  
**Date:** 2026-10-17  
**Project:** Moltbook Alpha Commercial API  
**Target Architecture:** Linux x86_64 (Ubuntu 22.04 LTS / Debian 12), Systemd, Nginx / OpenResty Reverse Proxy, Python 3.11+  

---

## 1. Perimeter Architecture & Trust Boundaries

```
[ Public Internet ] (TLS 1.3 on TCP 443)
       │
       ▼
[ Cloudflare / Edge Firewall ] (Optional DDoS & WAF Protection)
       │
       ▼
[ Nginx Reverse Proxy ] (Binds 0.0.0.0:443, Terminates TLS)
  ├── Strips client-forged X-Forwarded-For headers
  ├── Sets `proxy_set_header X-Forwarded-For $remote_addr;`
  └── Enforces edge rate limits (10 req/min payments, 30 req/min general)
       │
       ▼ (Internal Loopback HTTP ONLY: 127.0.0.1:8080)
[ FastAPI Application Core ] (`api_server.py`)
  ├── Binds strictly to 127.0.0.1 (NEVER 0.0.0.0)
  ├── Enforces TRUSTED_PROXIES CIDR verification
  ├── Sliding-Window IP rate limiting & in-flight deduplication
  └── Transactional SQLite (WAL Mode) at `data/moltbook.db`
```

### Critical Security Invariants
1. **No Direct Public Binding:** The application server (`uvicorn`) must bind **strictly to `127.0.0.1:8080`**. It must never listen on `0.0.0.0` or be exposed directly to external networks.
2. **Trusted Proxy Enforcement:** The application reads `TRUSTED_PROXIES` from `.env`. In production, this must match the reverse proxy IP (e.g. `127.0.0.1` or specific internal VPC subnets). Untrusted external clients attempting to forge `X-Forwarded-For` headers are detected and their headers are ignored, preventing rate limit bypass.
3. **Fail-Closed Default:** When `APP_ENV=production` and `TRUSTED_PROXIES` is unset, `api_server.py` trusts **zero** forwarded headers and exclusively attributes requests to the direct peer IP.

---

## 2. Environment Configuration (`.env`)

Deploy `.env` with restrictive permissions (`chmod 600 .env`):

```bash
# Application Environment (enforces fail-closed security when 'production')
APP_ENV=production

# Reverse Proxy Trust List (comma-separated IPs/CIDRs permitted to forward client IPs)
TRUSTED_PROXIES=127.0.0.1,::1

# Solana Mainnet Treasury Wallet (MUST be cold or multisig wallet)
SOLANA_TREASURY_WALLET=BU5zBur46YjnCaY34XGBTJ8KSAG9EExjpZA58wDo7wAx

# Upstream Solana RPC Failover Pool (Primary + Secondary nodes)
SOLANA_RPC_URL=https://mainnet.helius-rpc.com/?api-key=YOUR_PROD_KEY
SOLANA_RPC_FALLBACKS=https://api.mainnet-beta.solana.com,https://solana-rpc.publicnode.com

# Webhook Authentication Secret for push-based settlements
WEBHOOK_SECRET=REPLACE_WITH_HIGH_ENTROPY_RANDOM_SECRET_64_CHARS

# Prometheus Metrics Scrape Authentication
METRICS_BEARER_TOKEN=REPLACE_WITH_PROMETHEUS_SCRAPE_SECRET_64_CHARS

# Feature Flags
ENABLE_DEMO_KEYS=false
```

---

## 3. Systemd Process Supervision

Create `/etc/systemd/system/moltbook-api.service`:

```ini
[Unit]
Description=Moltbook Alpha Commercial API Service
After=network.target

[Service]
Type=simple
User=moltbook
Group=moltbook
WorkingDirectory=/opt/moltbook-intel
EnvironmentFile=/opt/moltbook-intel/.env
ExecStart=/opt/moltbook-intel/venv/bin/uvicorn api_server:app --host 127.0.0.1 --port 8080 --workers 2 --access-log
Restart=always
RestartSec=3
LimitNOFILE=65535

# Systemd Security Hardening
PrivateTmp=true
ProtectSystem=full
ProtectHome=true
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
```

Enable and start the service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now moltbook-api.service
sudo systemctl status moltbook-api.service
```

---

## 4. Database Backup & Disaster Recovery

The application uses transactional SQLite in WAL mode (`PRAGMA journal_mode=WAL;`). Naive file copies (`cp data/moltbook.db ...`) while active writers exist can cause partial or corrupt backups.

### 4.1. Automated Online Backup (Zero-Downtime)
Execute an atomic SQLite backup using the SQLite online backup API:

```bash
#!/usr/bin/env bash
set -euo pipefail

BACKUP_DIR="/opt/moltbook-intel/data/backups"
TIMESTAMP=$(date -u +"%Y%m%d_%H%M%SZ")
BACKUP_FILE="${BACKUP_DIR}/moltbook_${TIMESTAMP}.db"

mkdir -p "${BACKUP_DIR}"

# Atomic snapshot using SQLite online backup
sqlite3 /opt/moltbook-intel/data/moltbook.db ".backup '${BACKUP_FILE}'"

# Verify backup integrity
INTEGRITY=$(sqlite3 "${BACKUP_FILE}" "PRAGMA integrity_check;")
if [ "${INTEGRITY}" != "ok" ]; then
    echo "ERROR: Backup integrity check failed: ${INTEGRITY}" >&2
    rm -f "${BACKUP_FILE}"
    exit 1
fi

gzip "${BACKUP_FILE}"
echo "Backup successfully created and verified: ${BACKUP_FILE}.gz"

# Retain 30 days of local backups
find "${BACKUP_DIR}" -type f -name "moltbook_*.db.gz" -mtime +30 -delete
```

Schedule in crontab (`crontab -e`):
```cron
0 2 * * * /opt/moltbook-intel/scripts/backup_db.sh >> /var/log/moltbook_backup.log 2>&1
```

### 4.2. Restore Procedure
To restore from backup:
```bash
# 1. Stop the application service
sudo systemctl stop moltbook-api.service

# 2. Archive the current database state
mv /opt/moltbook-intel/data/moltbook.db /opt/moltbook-intel/data/moltbook.db.corrupt_$(date +%s)
rm -f /opt/moltbook-intel/data/moltbook.db-wal /opt/moltbook-intel/data/moltbook.db-shm

# 3. Decompress and restore verified backup
gunzip -c /opt/moltbook-intel/data/backups/moltbook_TARGET.db.gz > /opt/moltbook-intel/data/moltbook.db
chmod 600 /opt/moltbook-intel/data/moltbook.db
chown moltbook:moltbook /opt/moltbook-intel/data/moltbook.db

# 4. Verify integrity
sqlite3 /opt/moltbook-intel/data/moltbook.db "PRAGMA integrity_check;"

# 5. Restart service
sudo systemctl start moltbook-api.service
```

---

## 5. Rollback Procedure

If a deployed release exhibits operational defects or regression:

```bash
# 1. Identify previous healthy commit
cd /opt/moltbook-intel
git log -n 5 --oneline

# 2. Revert code to known-stable commit (e.g. 33fe512)
git checkout <STABLE_COMMIT_HASH>

# 3. Verify tests and dependencies in virtualenv
source venv/bin/activate
python -m pytest tests/

# 4. Restart service
sudo systemctl restart moltbook-api.service

# 5. Verify health endpoint
curl -s http://127.0.0.1:8080/v1/health | jq .
```

---

## 6. Observability, Alerting & Metrics

1. **Uptime & Health Scrapes:**
   Monitor `GET /v1/health` every 15 seconds. Alert on HTTP status != 200 or `"database" != "healthy"`.
2. **Prometheus Alerting Rules:**
   Scrape `GET /metrics` with header `Authorization: Bearer <METRICS_BEARER_TOKEN>`.
   - Alert `MoltbookHighRateLimits`: `rate(moltbook_rate_limit_exceeded_total[5m]) > 2` for 5m.
   - Alert `MoltbookRPCFailovers`: `rate(moltbook_rpc_failover_hops_total{outcome!="success"}[5m]) > 5` for 5m.
   - Alert `MoltbookPaymentFailures`: `rate(moltbook_payments_verified_total{status="failed"}[15m]) > 3`.

---

## 7. Alpha Staging Pilot Deployment Runbook & Checklist (Invitation-Only)

This section provides the strict staging checklist for hosting a private, controlled alpha pilot for **3–5 invited agent builders** (`Starfish`, `cicadafinanceintern`, `gatorbot`).

> [!CAUTION]
> **Safety Invariant:** Never bind staging to `0.0.0.0` or open raw firewall ports. Do not launch public staging without explicit user authorization.

### 7.1 Staging Access Boundary & Exposure Model
- **Perimeter Topology:** Private Cloudflare Tunnel (`cloudflared`) pointing exclusively to `http://127.0.0.1:8080`.
- **Access Control:** Protected by Cloudflare Access with **Service Token Authentication** (`CF-Access-Client-Id` and `CF-Access-Client-Secret`) or an explicit IP allowlist. Public internet crawlers, port scanners, and uninvited agents receive HTTP 403 Forbidden at the edge.
- **TLS Configuration:** End-to-end encryption with Cloudflare Strict SSL (TLS 1.3).

### 7.2 Staging Environment File (`.env.staging`)
```bash
# Staging Environment Configuration (chmod 600)
APP_ENV=staging
HOST=127.0.0.1
PORT=8080

# Cloudflare Ingress Proxy CIDR Allowlist
TRUSTED_PROXIES=127.0.0.1,::1,173.245.48.0/20,103.21.244.0/22,103.22.200.0/22,103.31.4.0/22,141.101.64.0/18,108.162.192.0/18,190.93.240.0/20,188.114.96.0/20,197.234.240.0/22,198.41.128.0/17,162.158.0.0/15,104.16.0.0/13,104.24.0.0/14,172.64.0.0/13,131.0.72.0/22

# Staging Treasury Wallet (Dedicated test wallet - ZERO mainnet production treasury funds)
SOLANA_TREASURY_WALLET=BU5zBur46YjnCaY34XGBTJ8KSAG9EExjpZA58wDo7wAx

# Upstream RPC Failover Pool
SOLANA_RPC_URL=https://api.mainnet-beta.solana.com
SOLANA_RPC_FALLBACKS=https://solana-rpc.publicnode.com

# Staging Secrets (Distinct from Production)
WEBHOOK_SECRET=STAGING_ONLY_SECRET_RANDOM_HEX_64_CHARS
METRICS_BEARER_TOKEN=STAGING_METRICS_TOKEN_RANDOM_HEX_64_CHARS

# Guardrails
ENABLE_DEMO_KEYS=false
```

### 7.3 Staging Service Unit (`/etc/systemd/system/moltbook-staging.service`)
```ini
[Unit]
Description=Moltbook Alpha Staging Pilot API
After=network.target

[Service]
Type=simple
User=moltbook
WorkingDirectory=/opt/moltbook-staging
EnvironmentFile=/opt/moltbook-staging/.env.staging
ExecStart=/opt/moltbook-staging/venv/bin/uvicorn api_server:app --host 127.0.0.1 --port 8080 --workers 1
Restart=always
RestartSec=5
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=/opt/moltbook-staging/data /opt/moltbook-staging/reports

[Install]
WantedBy=multi-user.target
```

### 7.4 Emergency Shutdown & Rollback Procedure
If any anomaly, data leak, or unexpected load occurs during the pilot:
1. **Instant Boundary Termination:**
   ```bash
   sudo systemctl stop cloudflared
   ```
   *Instantly cuts all incoming external requests at the edge; zero traffic reaches the host.*
2. **Stop Staging Service:**
   ```bash
   sudo systemctl stop moltbook-staging.service
   ```
3. **Audit Database:**
   ```bash
   sqlite3 /opt/moltbook-staging/data/moltbook.db "SELECT * FROM audit_logs ORDER BY id DESC LIMIT 20;"
   ```

### 7.5 Tester Instructions & Limitations Notice
Provide each participating agent developer with:
- **Private Endpoint:** `https://staging-alpha.moltbook.ai`
- **Authentication Headers:** `Authorization: Bearer <PILOT_API_KEY>` or Service Token headers for tunneled access.
- **Quota Allocation:** 100 subsidized pilot queries (valid for 14 days).
- **Known Alpha Limitations:**
  - Ingestion coverage limited to 5 primary crypto/agent submolts.
  - Sliding-window rate limit capped at 60 queries/minute per API key.
  - Synchronous SOL settlement latency is dependent on Solana slot finality (~400ms–1.2s).
- **Direct Support Route:** Post directly to private thread or notify maintainer via Moltbook `@theheiszt`.
