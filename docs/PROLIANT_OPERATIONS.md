# ProLiant Ubuntu Production Operations Guide

This runbook documents the standard administration workflow, remote SSH access, operational commands, and disaster recovery procedures for Moltbook Alpha API deployed on the HP ProLiant ML150 G6 host (`10.0.0.190`).

---

## 1. Host Information & Access Boundary

- **Host IP:** `10.0.0.190` (Private LAN)
- **Architecture:** x86_64, HP ProLiant ML150 G6
- **Operating System:** Ubuntu 24.04.4 LTS
- **Administrative User:** `user`
- **Application Service Account:** `moltbook-api` (unprivileged, `/usr/sbin/nologin`)
- **SSH Authentication:** Dedicated Ed25519 keypair
  - Windows Identity Path: `C:\Users\Andrew\.ssh\moltbook_proliant`
  - Linux Target: `~/.ssh/authorized_keys`
  - Host Key Verification: Strictly enforced via `~/.ssh/known_hosts` (ED25519)
- **External Network Exposure:** Strictly blocked. No public router forwarding, no public DNS, no open inbound firewall ports.

---

## 2. Verified SSH Commands

### Connect to ProLiant Host
```bash
ssh -i "$env:USERPROFILE\.ssh\moltbook_proliant" user@10.0.0.190
```

### Run Remote Operational Commands from Windows
```powershell
# Check live system & application status
ssh -i "$env:USERPROFILE\.ssh\moltbook_proliant" user@10.0.0.190 "sudo /opt/moltbook-alpha/current/ops/server/status.sh"

# Run read-only server audit
ssh -i "$env:USERPROFILE\.ssh\moltbook_proliant" user@10.0.0.190 "sudo /opt/moltbook-alpha/current/ops/server/audit_server.sh"

# Execute health check probe
ssh -i "$env:USERPROFILE\.ssh\moltbook_proliant" user@10.0.0.190 "sudo /opt/moltbook-alpha/current/ops/server/health_check.sh"

# Trigger on-demand consistent SQLite database backup
ssh -i "$env:USERPROFILE\.ssh\moltbook_proliant" user@10.0.0.190 "sudo /opt/moltbook-alpha/current/ops/server/backup.sh"

# Run isolated disaster recovery restore test
ssh -i "$env:USERPROFILE\.ssh\moltbook_proliant" user@10.0.0.190 "sudo /opt/moltbook-alpha/current/ops/server/restore_test.sh"

# Inspect journald service logs
ssh -i "$env:USERPROFILE\.ssh\moltbook_proliant" user@10.0.0.190 "journalctl -u moltbook-alpha -n 50 --no-pager"
```

---

## 3. Standard Operational Workflow

Antigravity and human operators must follow this discipline when administering the server:

```
[1. Connect & Verify Host Identity]
               │
               ▼
[2. Run Read-Only Status & Audit]
               │
               ▼
[3. Inspect Logs, Headroom & Backup Age]
               │
               ▼
[4. Diagnose Root Cause Before Modifying]
               │
               ▼
[5. Request Explicit Approval for Material Changes]
               │
               ▼
[6. Apply Authorized Actions & Verify Health]
               │
               ▼
[7. Record Verification Evidence & Exit Cleanly]
```

---

## 4. Operational Playbooks

### A. Deploy a New Release
1. On Windows dev machine, build a release archive:
   ```powershell
   git archive --format=tar.gz -o release.tar.gz HEAD
   ```
2. Securely transfer to ProLiant:
   ```powershell
   scp -i "$env:USERPROFILE\.ssh\moltbook_proliant" release.tar.gz user@10.0.0.190:/tmp/
   ```
3. Execute deployment script:
   ```powershell
   ssh -i "$env:USERPROFILE\.ssh\moltbook_proliant" user@10.0.0.190 "sudo /opt/moltbook-alpha/current/ops/server/deploy.sh --tar /tmp/release.tar.gz"
   ```

### B. Rollback to Previous Release
If an issue occurs after deployment, atomically revert to the previous release without touching SQLite state:
```powershell
ssh -i "$env:USERPROFILE\.ssh\moltbook_proliant" user@10.0.0.190 "sudo /opt/moltbook-alpha/current/ops/server/rollback.sh"
```

### C. Safe Ubuntu Package Updates
1. Review pending updates (read-only):
   ```powershell
   ssh -i "$env:USERPROFILE\.ssh\moltbook_proliant" user@10.0.0.190 "sudo /opt/moltbook-alpha/current/ops/server/update_ubuntu.sh --audit"
   ```
2. Apply pending updates (preserves configuration files):
   ```powershell
   ssh -i "$env:USERPROFILE\.ssh\moltbook_proliant" user@10.0.0.190 "sudo /opt/moltbook-alpha/current/ops/server/update_ubuntu.sh --apply"
   ```
3. If a reboot is required, schedule during maintenance window:
   ```powershell
   ssh -i "$env:USERPROFILE\.ssh\moltbook_proliant" user@10.0.0.190 "sudo reboot"
   ```

---

## 5. Security & Emergency Boundaries

1. **Payment Restrictions:** Production live payments remain **strictly disabled** (`ENABLE_DEMO_KEYS=false`, mock payment settlement active for alpha testing).
2. **Network Isolation:** API binds exclusively to `127.0.0.1:8080`. External traffic routes only via authenticated private tunnel (e.g. Cloudflare Access).
3. **Secret Hygiene:** Database passwords, webhook secrets, and private keys are never stored in git or logs. All environment variables reside in `/etc/moltbook-alpha/api.env` (permissions `0640`, owned by `root:moltbook-api`).

---

## 6. Active Systemd Timers & Automated Operations

The following unattended systemd timers are active and managed independently by systemd on the ProLiant:

| Timer Unit | Service Unit | Schedule / Cadence | Running User | Description |
| :--- | :--- | :--- | :--- | :--- |
| `moltbook-health.timer` | `moltbook-health.service` | Every 5 minutes | `moltbook-api` | Probes `/v1/health`, verifies SQLite integrity, checks disk space, logs to journald. |
| `moltbook-backup.timer` | `moltbook-backup.service` | Daily at 03:00 UTC | `moltbook-api` | Creates consistent online SQLite backup, generates SHA256 checksum, prunes >14 days. |
| `moltbook-restore-test.timer` | `moltbook-restore-test.service` | Weekly (Sun 04:00 UTC) | `moltbook-api` | Restores latest snapshot into isolated `/tmp` sandbox; verifies checksum and table schemas. |
| `moltbook-update-audit.timer` | `moltbook-update-audit.service` | Daily at 05:00 UTC | `root` | Scans for pending Ubuntu security packages without rebooting; logs status to journald. |
| `moltbook-report.timer` | `moltbook-report.service` | Daily at 06:00 UTC | `moltbook-api` | Generates concise system and service health report to journald. |

### Check Active Timer Schedules
```powershell
ssh -i "$env:USERPROFILE\.ssh\moltbook_proliant" user@10.0.0.190 "systemctl list-timers 'moltbook*'"
```



---

## 7. Cloudflare Named Tunnel Ingress Configuration (`cloudflared`)

To provide persistent, enterprise-grade public ingress to the private ProLiant host (`10.0.0.190:8080`) without opening inbound router ports or using ephemeral quick tunnels (`trycloudflare.com`), a named Cloudflare Tunnel is deployed as a managed systemd service.

### 7.1 Architecture & Security Properties
- **Origin Service:** `http://127.0.0.1:8080` (Moltbook Alpha FastAPI backend).
- **Outbound Only:** The daemon establishes outbound multiplexed QUIC/HTTP2 tunnels to Cloudflare edge edge servers. No inbound firewall rules, port forwarding, or public IPs required on the host.
- **Edge Termination:** SSL/TLS is terminated at Cloudflare edge with automatic certificate rotation and DDoS/rate-limit shielding.
- **Reconnection Resilience:** Automatic backoff and reconnection across network hiccups or host reboots.

### 7.2 Installation & Setup Runbook

#### Step 1: Install official `cloudflared` package on ProLiant
```bash
# Add Cloudflare GPG key and repository
sudo mkdir -p --mode=0755 /usr/share/keyrings
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared bookworm main' | sudo tee /etc/apt/sources.list.d/cloudflared.list
sudo apt-get update && sudo apt-get install -y cloudflared
```

#### Step 2: Authenticate and Create Named Tunnel
```bash
# Authorize against Cloudflare account
cloudflared tunnel login

# Create persistent named tunnel
cloudflared tunnel create moltbook-alpha
# Note the returned Tunnel-UUID
```

#### Step 3: Configure Ingress Rules (`/etc/cloudflared/config.yml`)
```yaml
tunnel: <TUNNEL_UUID>
credentials-file: /etc/cloudflared/<TUNNEL_UUID>.json

ingress:
  - hostname: api.moltbook.xyz
    service: http://127.0.0.1:8080
    originRequest:
      connectTimeout: 10s
      noTLSVerify: false
  - service: http_status:404
```

#### Step 4: Route DNS to Tunnel
```bash
cloudflared tunnel route dns moltbook-alpha api.moltbook.xyz
```

#### Step 5: Install & Start Systemd Service
```bash
# Register cloudflared as unattended systemd service
sudo cloudflared service install

# Enable and start service
sudo systemctl daemon-reload
sudo systemctl enable --now cloudflared
```

### 7.3 Remote Verification & Diagnostic Commands
Run from operator workstation via SSH:

```powershell
# 1. Verify cloudflared systemd service status
ssh -i "$env:USERPROFILE\.ssh\moltbook_proliant" user@10.0.0.190 "systemctl status cloudflared"

# 2. Inspect tunnel connection logs
ssh -i "$env:USERPROFILE\.ssh\moltbook_proliant" user@10.0.0.190 "journalctl -u cloudflared -n 30 --no-pager"

# 3. Test local origin responsiveness
ssh -i "$env:USERPROFILE\.ssh\moltbook_proliant" user@10.0.0.190 "curl -s http://127.0.0.1:8080/v1/health | jq ."

# 4. Verify public ingress through Cloudflare edge
curl -s https://api.moltbook.xyz/v1/health | jq .
curl -s https://api.moltbook.xyz/v1/intel/sample | jq .
```
