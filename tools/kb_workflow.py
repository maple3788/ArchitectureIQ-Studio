#!/usr/bin/env python3
"""Run the repository's bounded KB workflow CLI from this checkout."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from architecture_iq.kb.cli import main  # noqa: E402 — use this checkout after path setup

if __name__ == "__main__":
    raise SystemExit(main())
