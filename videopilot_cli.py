"""Console-script entrypoint for `videopilot`.

Re-exports `main()` from videopilot.py so `pip install -e .` exposes a
`videopilot` command on PATH instead of `python videopilot.py ...`.
"""

from __future__ import annotations

import runpy
from pathlib import Path


def main() -> int:
    here = Path(__file__).resolve().parent
    ns = runpy.run_path(str(here / "videopilot.py"), run_name="videopilot_loaded")
    return int(ns["main"]() or 0)


if __name__ == "__main__":
    raise SystemExit(main())
