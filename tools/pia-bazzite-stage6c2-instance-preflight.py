#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pia_bazzite import __app_id__
from pia_bazzite.single_instance import instance_is_running


def main() -> int:
    app = QCoreApplication.instance() or QCoreApplication([])
    del app
    if instance_is_running(__app_id__, timeout_ms=350):
        print("ERROR: A PIA Bazzite instance is already running.", file=sys.stderr)
        return 10
    print("PASS    No running PIA Bazzite instance was detected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
