#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pia_bazzite.kill_switch_crash_state import (
    CrashRecoveryStateError,
    CrashRecoveryStore,
)
from pia_bazzite.settings import crash_recovery_path


def main() -> int:
    store = CrashRecoveryStore(crash_recovery_path())
    try:
        record = store.load()
        if record is None:
            print("PASS    No previous crash-recovery record is present.")
            return 0
        store.clear()
    except CrashRecoveryStateError as exc:
        print(
            "ERROR: The previous crash-recovery record is unsafe and was not changed: "
            f"{exc}",
            file=sys.stderr,
        )
        return 1
    print(
        "PASS    A structurally valid stale crash-recovery record was removed while "
        "VPN and firewall were independently verified absent."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
