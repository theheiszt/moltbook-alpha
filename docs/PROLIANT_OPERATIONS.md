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

