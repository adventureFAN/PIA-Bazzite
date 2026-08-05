#!/usr/bin/python3 -I
from __future__ import annotations

import os
from pathlib import Path
import stat
import sys

SHIM_PATH = Path("/usr/local/libexec/pia-bazzite/pia-bazzite-stage3-process-shim")
ALLOWED_HELPERS = {
    Path("/usr/local/libexec/pia-bazzite/pia-bazzite-stage3-invalid-response-probe"),
    Path("/usr/local/libexec/pia-bazzite/pia-bazzite-stage3-timeout-probe"),
}


def verify_root_owned(path: Path, mode: int) -> Path:
    resolved = path.resolve(strict=True)
    metadata = resolved.lstat()
    if not stat.S_ISREG(metadata.st_mode) or resolved.is_symlink():
        raise RuntimeError("expected a regular file")
    if (metadata.st_uid, metadata.st_gid, stat.S_IMODE(metadata.st_mode), metadata.st_nlink) != (0, 0, mode, 1):
        raise RuntimeError("unsafe test file ownership or mode")
    return resolved


def main() -> int:
    actual_shim = verify_root_owned(Path(sys.argv[0]), 0o755)
    if actual_shim != SHIM_PATH.resolve(strict=True):
        raise RuntimeError("shim is outside its fixed path")
    if len(sys.argv) != 4 or sys.argv[1] != "--disable-internal-agent" or sys.argv[3] != "status":
        raise RuntimeError("shim accepts only one fixed client argv shape")
    requested = Path(sys.argv[2])
    if requested not in ALLOWED_HELPERS:
        raise RuntimeError("helper is outside fixed stage-3 probe scope")
    helper = verify_root_owned(requested, 0o755)
    os.execve(str(helper), [str(helper), "status"], {"PATH": "/usr/bin:/bin", "LC_ALL": "C"})
    return 4


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"stage3 process shim refused execution: {exc}", file=sys.stderr)
        raise SystemExit(4)
