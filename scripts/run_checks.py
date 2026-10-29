#!/usr/bin/env python3
"""
Moltbook Alpha — Local CI Pre-Flight Validation Harness.
Runs the authoritative test and lint battery locally without requiring GitHub Actions minutes.

Steps executed:
  1. System & storage health diagnostics (ops.doctor)
  2. Formatting and static analysis (ruff check .)
  3. Full unit and integration test suite (pytest -q)
"""

import subprocess
import sys
import time

def run_step(step_name: str, cmd: list[str]) -> bool:
    print("\n=================================================================")
    print(f"  STEP: {step_name}")
    print(f"  COMMAND: {' '.join(cmd)}")
    print("=================================================================")
    start = time.time()
    res = subprocess.run(cmd)
    elapsed = time.time() - start
    if res.returncode == 0:
        print(f"\n  [ PASS ] {step_name} completed in {elapsed:.2f}s")
        return True
    else:
        print(f"\n  [ FAIL ] {step_name} exited with code {res.returncode} in {elapsed:.2f}s")
        return False

def main():
    print("\nStarting Moltbook Alpha Local Pre-Flight CI Suite...")
    steps = [
        ("Offline Doctor & Health Diagnostics", [sys.executable, "-m", "ops.doctor"]),
        ("Ruff Static Analysis & Lint Checks", [sys.executable, "-m", "ruff", "check", "."]),
        ("Full Unit & Integration Test Suite", [sys.executable, "-m", "pytest", "-q"]),
    ]

    all_passed = True
    for name, cmd in steps:
        if not run_step(name, cmd):
            all_passed = False
            break

    print("\n" + "=" * 65)
    if all_passed:
        print("  ALL LOCAL CI CHECKS PASSED (100% OPERATIONAL & VERIFIED)")
        print("=" * 65 + "\n")
        sys.exit(0)
    else:
        print("  LOCAL CI CHECKS FAILED — Review errors above.")
        print("=" * 65 + "\n")
        sys.exit(1)

if __name__ == "__main__":
    main()
