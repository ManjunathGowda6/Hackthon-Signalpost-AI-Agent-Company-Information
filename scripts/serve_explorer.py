#!/usr/bin/env python3
"""scripts/serve_explorer.py — Entrypoint to launch the Signalpost Web Explorer."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from run import main

if __name__ == "__main__":
    main()
