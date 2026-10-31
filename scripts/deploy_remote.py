import os
import shlex
import sys
import time

import paramiko

HOST = os.environ.get("MOLTBOOK_DEPLOY_HOST", "10.0.0.190")
USER = os.environ.get("MOLTBOOK_DEPLOY_USER", "user")
# SSH/sudo password must come from the environment; never commit it.
PASS = os.environ.get("MOLTBOOK_DEPLOY_PASSWORD")


def main():
    if not PASS:
        sys.exit("MOLTBOOK_DEPLOY_PASSWORD is not set; refusing to deploy.")

    print(f"Connecting to {HOST}...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PASS)

    # 1. Check venv httpx
    cmd = "/opt/moltbook-alpha/current/venv/bin/python3 -c 'import httpx; print(httpx.__version__)'"
    stdin, stdout, stderr = ssh.exec_command(cmd)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    print("Remote httpx check:", out if out else f"ERROR: {err}")

    # 2. Upload release.tar.gz via SFTP
    print("Uploading release.tar.gz via SFTP...")
    sftp = ssh.open_sftp()
    sftp.put("release.tar.gz", "/tmp/release.tar.gz")
    sftp.close()
    print("Upload complete.")

    # 3. Create release directory and unpack
    import subprocess
    commit_sha = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    release_dir = f"/opt/moltbook-alpha/releases/{timestamp}_{commit_sha}"
    print(f"Target release directory: {release_dir}")

    deploy_commands = [
        f"sudo mkdir -p {release_dir}",
        f"sudo tar -xzf /tmp/release.tar.gz -C {release_dir}",
        f"sudo ln -s /opt/moltbook-alpha/releases/20261028_030659_b0b6a63/venv {release_dir}/venv",
        f"sudo chown -R moltbook-api:moltbook-api {release_dir}",
        f"sudo ln -sfn {release_dir} /opt/moltbook-alpha/current",
        "sudo systemctl restart moltbook-alpha.service",
        "sleep 1",
        "systemctl status moltbook-alpha.service --no-pager",
    ]

    for c in deploy_commands:
        print(f"Executing: {c}")
        # sudo -S reads the password from stdin; it is never placed on the command line.
        stdin, stdout, stderr = ssh.exec_command(f"sudo -S -p '' bash -c {shlex.quote(c)}")
        stdin.write(PASS + "\n")
        stdin.flush()
        out = stdout.read().decode()
        err = stderr.read().decode()
        if out.strip():
            print("  STDOUT:", out.strip().encode("ascii", "replace").decode("ascii"))
        if err.strip():
            print("  STDERR:", err.strip().encode("ascii", "replace").decode("ascii"))

    ssh.close()
    print("Deployment finished.")

if __name__ == "__main__":
    main()
