#!/usr/bin/env python3
"""
PoA Automated Bounty Runner CLI Script.
Delegates to ops.poa_runner.
"""
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from ops.poa_runner import main

if __name__ == "__main__":
    main()
