from __future__ import annotations

import os
import shutil
import subprocess


def sanitized_host_environment() -> dict[str, str]:
    """Return an environment safe for launching host desktop programs.

    PyInstaller prepends bundled libraries to LD_LIBRARY_PATH. Host KDE tools
    must not inherit those bundled Qt/libstdc++ libraries.
    """

    env = dict(os.environ)
    original = env.get("LD_LIBRARY_PATH_ORIG")
    if original is not None:
        env["LD_LIBRARY_PATH"] = original
    else:
        env.pop("LD_LIBRARY_PATH", None)

    for key in (
        "PYTHONHOME",
        "PYTHONPATH",
        "QT_PLUGIN_PATH",
        "QT_QPA_PLATFORM_PLUGIN_PATH",
        "QML2_IMPORT_PATH",
        "QML_IMPORT_PATH",
    ):
        env.pop(key, None)
    return env


def open_host_target(target: str) -> bool:
    """Open a URL/path with the host desktop without AppImage library leakage."""

    opener = shutil.which("xdg-open", path="/usr/local/bin:/usr/bin:/bin")
    if not opener:
        return False
    try:
        subprocess.Popen(
            [opener, target],
            env=sanitized_host_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
    except OSError:
        return False
    return True
