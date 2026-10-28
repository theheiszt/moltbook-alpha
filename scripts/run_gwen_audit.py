"""
Direct Gwen Autonomous Coding Agent Runner for Moltbook Alpha Feature Audit.
Executes Gwen locally using the Qwen3-8B engine on the Intel Arc A770 GPU.
"""

import sys
import time
from pathlib import Path

# Add Gwen to path
sys.path.insert(0, "F:/LocalAI/agents/gwen")
from gwen.task_manager import TaskManager  # noqa: E402

PROJECT_PATH = r"I:\Scripts and Programs\moltbook-intel"

TASK_DESCRIPTION = (
    "Conduct a comprehensive architectural and feature audit of Moltbook Alpha and generate a detailed "
    "report in docs/GWEN_FEATURE_AUDIT_AND_ROADMAP.md. "
    "Identify all missing capabilities and provide concrete code specifications to make Moltbook Alpha "
    "the most featured and complete autonomous agent intelligence platform: "
    "1) Solana DEX microstructure engine (CLMM orderbook depth, tick bounds, pool spoofing detection); "
    "2) Multi-rail payment adapters (Nano-invoice zero-fee microquery adapter, devnet/mainnet toggle, explicit RECEIVED_UNMATCHED automated refunding); "
    "3) Real-time websocket alert streams and webhook subscriptions; "
    "4) Quant bot SDK upgrades for high-frequency algorithmic traders."
)

ACCEPTANCE_CRITERIA = [
    "Generate docs/GWEN_FEATURE_AUDIT_AND_ROADMAP.md containing detailed feature gap analysis, component architecture, and implementation specifications.",
    "Ensure all existing test suite requirements continue passing."
]

def main():
    sys.stdout.reconfigure(encoding="utf-8")
    print("=" * 70)
    print("STARTING GWEN (QWEN3-8B) AUTONOMOUS CODING AGENT AUDIT")
    print("=" * 70)

    tm = TaskManager()

    print("\n[1/3] Submitting audit task to Gwen TaskManager...")
    submission = tm.submit_task(
        task_description=TASK_DESCRIPTION,
        project_path_str=PROJECT_PATH,
        base_ref="HEAD",
        acceptance_criteria=ACCEPTANCE_CRITERIA,
        timeout_seconds=300
    )

    task_id = submission.get("task_id")
    print(f"Task ID: {task_id} | Status: {submission.get('status')} | Phase: {submission.get('phase')}")

    if not task_id:
        print("Failed to submit task:", submission)
        return

    print("\n[2/3] Streaming live execution progress...")
    last_phase = None
    last_log_count = 0

    while True:
        status_info = tm.get_status(task_id)
        status = status_info.get("status")
        phase = status_info.get("phase")
        elapsed = status_info.get("elapsed_seconds", 0)
        logs = status_info.get("logs", [])

        if phase != last_phase:
            print(f"[{elapsed:5.1f}s] Phase transitioned to -> {phase} (Status: {status})")
            last_phase = phase

        if len(logs) > last_log_count:
            for log_line in logs[last_log_count:]:
                print(f"  {log_line}")
            last_log_count = len(logs)

        if status in ["COMPLETED", "FAILED", "CANCELLED"]:
            print(f"\n[3/3] Task reached terminal state: {status}")
            break

        time.sleep(3)

    print("=" * 70)
    print("TASK SUMMARY & RESULT INSPECTION")
    print("=" * 70)

    result = tm.get_result(task_id)
    print("Status:", result.get("status"))
    print("Message:", result.get("message"))
    print("Modified Files:", result.get("modified_files", []))
    print("Unified Diff Length:", len(result.get("git_diff", "")))

    # If Gwen created or modified files in worktree, inspect them
    workspace_path = result.get("workspace_path")
    if workspace_path:
        report_path = Path(workspace_path) / "docs" / "GWEN_FEATURE_AUDIT_AND_ROADMAP.md"
        if report_path.exists():
            print(f"\nAudit report successfully created in worktree at: {report_path}")
            target_report = Path(PROJECT_PATH) / "docs" / "GWEN_FEATURE_AUDIT_AND_ROADMAP.md"
            target_report.parent.mkdir(parents=True, exist_ok=True)
            target_report.write_text(report_path.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"Copied audit report to active project docs: {target_report}")
        else:
            print("Audit report file not found in worktree docs directory.")

if __name__ == "__main__":
    main()
