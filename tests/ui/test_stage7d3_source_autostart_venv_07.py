from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from pia_bazzite.autostart import AUTOSTART_ARGUMENT, current_autostart_command


ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "main.py"


class Stage7D3SourceAutostartVenvTests(unittest.TestCase):
    def test_source_autostart_preserves_virtualenv_python_launcher_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            real_python = root / "system" / "python3.14"
            real_python.parent.mkdir(parents=True)
            real_python.write_text("", encoding="utf-8")

            venv_python = root / ".venv" / "bin" / "python"
            venv_python.parent.mkdir(parents=True)
            venv_python.symlink_to(real_python)

            with (
                patch.dict(os.environ, {"APPIMAGE": ""}, clear=False),
                patch.object(sys, "executable", str(venv_python)),
                patch.object(sys, "argv", [str(MAIN)]),
                patch.object(sys, "frozen", False, create=True),
            ):
                command = current_autostart_command()

            self.assertEqual(command[0], str(venv_python))
            self.assertNotEqual(command[0], str(real_python))
            self.assertEqual(command[1], str(MAIN.resolve()))
            self.assertEqual(command[2], AUTOSTART_ARGUMENT)

    def test_source_autostart_keeps_absolute_main_path_and_internal_flag(self) -> None:
        with (
            patch.dict(os.environ, {"APPIMAGE": ""}, clear=False),
            patch.object(sys, "executable", "/home/tester/PIA-Bazzite/.venv/bin/python"),
            patch.object(sys, "argv", [str(MAIN)]),
            patch.object(sys, "frozen", False, create=True),
        ):
            self.assertEqual(
                current_autostart_command(),
                (
                    "/home/tester/PIA-Bazzite/.venv/bin/python",
                    str(MAIN.resolve()),
                    AUTOSTART_ARGUMENT,
                ),
            )


if __name__ == "__main__":
    unittest.main()
