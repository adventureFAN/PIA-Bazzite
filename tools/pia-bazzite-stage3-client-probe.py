#!/usr/bin/python3 -I
from __future__ import annotations

import os
from pathlib import Path
import stat
import sys
import time

INVALID_PATH = Path(
    "/usr/local/libexec/pia-bazzite/pia-bazzite-stage3-invalid-response-probe"
)
TIMEOUT_PATH = Path(
    "/usr/local/libexec/pia-bazzite/pia-bazzite-stage3-timeout-probe"
)


def safe_boundary() -> Path:
    actual = Path(sys.argv[0]).resolve(strict=True)
    expected = {INVALID_PATH.resolve(strict=True), TIMEOUT_PATH.resolve(strict=True)}
    if actual not in expected:
        raise RuntimeError("probe path is outside fixed stage-3 scope")
    metadata = actual.lstat()
    if not stat.S_ISREG(metadata.st_mode) or actual.is_symlink():
        raise RuntimeError("probe is not a regular file")
    if (metadata.st_uid, metadata.st_gid, stat.S_IMODE(metadata.st_mode), metadata.st_nlink) != (0, 0, 0o755, 1):
        raise RuntimeError("probe ownership or mode is unsafe")
    if sys.argv[1:] != ["status"]:
        raise RuntimeError("probe accepts only status")
    return actual


def main() -> int:
    actual = safe_boundary()
    if actual == INVALID_PATH:
        print("not-a-json-helper-response")
        return 0
    time.sleep(5.0)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"stage3 probe refused execution: {exc}", file=sys.stderr)
        raise SystemExit(4)
