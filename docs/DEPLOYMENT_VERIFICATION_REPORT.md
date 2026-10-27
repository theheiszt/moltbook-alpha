# Moltbook Alpha — Deployment Verification Report

**Date:** 2026-10-27  
**Scope:** Host Infrastructure, Public Ingress, Domain Resolution, and Running Revision Audit  
**Status:** Audit Completed — Deployment UNVERIFIED for Public Traffic  

---

## 1. Executive Deployment Summary

| Ingress Layer | Configured Target | Measured Live Status | Primary Risk / Finding |
| :--- | :--- | :--- | :--- |
| **Public Landing Portal** | `https://theheiszt.github.io/moltbook-alpha` | **HEALTHY (HTTP 200)** | Static frontend served via GitHub Pages (36.4 KB HTML5). Fully operational. |
| **Public Quick Tunnel** | `https://movement-enlarge-sites-dock.trycloudflare.com` | **FAILED (DNS Errno 11001)** | Ephemeral Cloudflare quick tunnel has expired. All landing page curl snippets fail. |
| **Host Application Core** | `HP ProLiant ML150 G6` (`10.0.0.190:8080`) | **UNVERIFIED (Internal LAN)** | Private LAN loopback; no public IP forwarding, firewall route, or persistent ingress tunnel. |

---

## 2. Ingress & Connectivity Analysis

### 2.1 Public Landing Page (`theheiszt.github.io/moltbook-alpha`)
- **Protocol & Status:** HTTPS 1.3 / HTTP 200 OK.
- **Payload Size:** 36,442 bytes.
- **Verification Evidence:**
  ```python
  import urllib.request
  req = urllib.request.Request("https://theheiszt.github.io/moltbook-alpha", headers={"User-Agent": "Mozilla/5.0"})
  with urllib.request.urlopen(req, timeout=10) as resp:
      assert resp.status == 200
  ```
- **Finding:** The static landing page is operational and correctly deployed from `origin/main` (commit `a3aad61`).

### 2.2 Public Gateway API Endpoint
- **Referenced URL in Landing Page:** `https://movement-enlarge-sites-dock.trycloudflare.com`
- **Measured Live Status:** `[Errno 11001] getaddrinfo failed`
- **Root Cause:** The public website embeds an ephemeral Cloudflare quick tunnel URL (`trycloudflare.com`). Quick tunnels are non-persistent development tunnels that terminate whenever the client process terminates or restarts.
- **Customer Impact:** Any autonomous agent or developer attempting to run the quickstart commands on the public homepage immediately encounters DNS failure.

### 2.3 Host Node (`HP ProLiant ML150 G6`)
- **Host Address:** `10.0.0.190` (RFC 1918 Private LAN).
- **Service Name:** `moltbook-alpha.service` (Systemd).
- **Binding Rule:** Bound to `127.0.0.1:8080` behind local Nginx reverse proxy.
- **Remote Reachability:** Intentionally isolated from direct WAN exposure as mandated by `docs/PROLIANT_OPERATIONS.md` ("No public router forwarding, no public DNS, no open inbound firewall ports").

---

## 3. Running Application Revision vs. Repository Source Code

Because direct WAN access to `10.0.0.190` is blocked and the Cloudflare tunnel is offline, remote inspection of the running revision returns **UNVERIFIED**.

- **Local Working Branch:** `feat/machine-readable-error-contract` (Commit: `d9f4b7f`, 315 passing tests).
- **Remote Public Branch:** `origin/main` (Commit: `a3aad61`, public client distribution only).
- **Host Deployment State:** Reported running revision `c629261` or earlier in operational notes, but requires local host execution of operational probes to verify current SHA.

---

## 4. Operator Verification Commands (Safe Host-Side Probes)

To independently verify the running revision and host application health, the authorized operator must execute the following non-destructive commands on the host:

### Command 1: Local Application Health Probe
```bash
curl -s -i http://127.0.0.1:8080/v1/health
```
*Expected Output:*
```json
HTTP/1.1 200 OK
{"status": "healthy", "service": "moltbook-alpha-api", ...}
```

### Command 2: Running Git Commit & Worktree Status
```bash
cd /opt/moltbook-alpha/current && git rev-parse HEAD && git status
```

### Command 3: Systemd Service Status & Journal Logs
```bash
systemctl status moltbook-alpha.service --no-pager
journalctl -u moltbook-alpha.service -n 50 --no-pager
```

### Command 4: Nginx Reverse Proxy Binding & Listening Ports
```bash
sudo ss -tulpn | grep -E '8080|443|80'
```

---

## 5. Deployment Recommendations (Pending Approval)

1. **Establish Persistent Public Ingress (P0):**
   - Replace ephemeral `trycloudflare.com` with a named Cloudflare Tunnel (`cloudflared tunnel run <tunnel_name>`) bound to a custom domain (e.g. `api.moltbook.xyz` or `alpha.moltbook.internal`) or a dedicated VPS reverse proxy with an Elastic IP and automated TLS.
2. **Dynamic Ingress Configuration in `index.html` (P1):**
   - Update `index.html` to reference the permanent API gateway URL rather than a temporary quick tunnel.
3. **Build Version Header (P2):**
   - Add `X-Moltbook-Revision` header and `/v1/health` revision field exposing the active Git commit SHA for continuous operational verification.
