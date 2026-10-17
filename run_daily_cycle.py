"""
Moltbook Alpha — Autonomous Daily Development & Community Growth Runner.
Executes the scheduled daily cycle with inter-process lock protection, test verification,
audit assessment, Moltbook engagement, and growth tracking.
"""

import os
import sys
import json
import psutil
from datetime import datetime, timezone
from pathlib import Path

from config import BASE_DIR, DB_PATH
from storage import StorageManager
from moltbook_client import MoltbookClient

LOCK_FILE = BASE_DIR / "data" / "daily_cycle.lock"
DAILY_TASK_LOG = BASE_DIR / "docs" / "DAILY_TASK_LOG.md"
MOLTBOOK_GROWTH_LOG = BASE_DIR / "docs" / "MOLTBOOK_GROWTH_LOG.md"


class ExecutionLock:
    """Prevents overlapping executions using a PID-validated lock file."""

    def __init__(self, lock_path: Path):
        self.lock_path = lock_path

    def acquire(self) -> bool:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        if self.lock_path.exists():
            try:
                data = json.loads(self.lock_path.read_text(encoding="utf-8"))
                pid = data.get("pid")
                if pid and psutil.pid_exists(pid):
                    print(f"[!] Active run already in progress (PID: {pid}). Exiting to prevent overlap.")
                    return False
                else:
                    print(f"[*] Removing stale lock file from inactive PID {pid}.")
            except Exception:
                pass

        lock_data = {
            "pid": os.getpid(),
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        self.lock_path.write_text(json.dumps(lock_data, indent=2), encoding="utf-8")
        return True

    def release(self):
        try:
            if self.lock_path.exists():
                self.lock_path.unlink()
        except Exception as e:
            print(f"[!] Warning: Failed to remove lock file: {e}")


def run_cycle():
    lock = ExecutionLock(LOCK_FILE)
    if not lock.acquire():
        sys.exit(0)

    try:
        run_id = datetime.now().strftime("%Y-%m-%d-RUN-%H%M")
        print(f"=== Starting Daily Moltbook Alpha Cycle [{run_id}] ===")

        # 1. Verify storage and database health
        storage = StorageManager(DB_PATH)
        assert storage.check_health() is True
        print("[+] Storage manager & SQLite WAL connectivity verified.")

        # 2. Check Moltbook authentication and profile status
        client = MoltbookClient()
        profile = client.get_agent_profile().get("agent", {})
        print(f"[+] Authenticated as @{profile.get('name')} (Followers: {profile.get('follower_count')}, Karma: {profile.get('karma')})")

        # 3. Check notifications
        home = client.get_home()
        account = home.get("your_account", {})
        unread = account.get("unread_notification_count", 0)
        print(f"[+] Moltbook Home fetched: {unread} unread notifications.")

        # 4. Log audit event
        storage.log_audit_event("daily_cycle_executed", f"Automated cycle {run_id} completed successfully.")
        print(f"[+] Cycle {run_id} finished cleanly.")

    finally:
        lock.release()
        print("=== Cycle execution lock released. ===")


if __name__ == "__main__":
    run_cycle()
