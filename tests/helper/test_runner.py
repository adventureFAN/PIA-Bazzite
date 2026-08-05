from __future__ import annotations

from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from helper.pia_bazzite_kill_switch_helper.runner import NftError, NftRunner


class RunnerSecurityTests(unittest.TestCase):
    def test_rejects_unapproved_binary_path(self) -> None:
        with self.assertRaises(NftError):
            NftRunner(Path("/tmp/nft"))

    @patch("helper.pia_bazzite_kill_switch_helper.runner.subprocess.run")
    def test_uses_argument_array_sanitized_environment_and_no_shell(self, run_mock) -> None:
        run_mock.return_value = subprocess.CompletedProcess([], 0, "", "")
        runner = NftRunner(Path("/usr/sbin/nft"))
        runner.apply_script("destroy table inet example\n")
        args, kwargs = run_mock.call_args
        self.assertEqual(args[0], ["/usr/sbin/nft", "-f", "-"])
        self.assertFalse(kwargs["shell"])
        self.assertEqual(kwargs["env"]["PATH"], "/usr/sbin:/usr/bin:/sbin:/bin")
        self.assertEqual(kwargs["env"]["LC_ALL"], "C")

    @patch("helper.pia_bazzite_kill_switch_helper.runner.subprocess.run")
    def test_nft_failure_does_not_get_hidden(self, run_mock) -> None:
        run_mock.return_value = subprocess.CompletedProcess([], 1, "", "synthetic failure")
        runner = NftRunner(Path("/usr/sbin/nft"))
        with self.assertRaisesRegex(NftError, "synthetic failure"):
            runner.check_script("bad input\n")

    @patch("helper.pia_bazzite_kill_switch_helper.runner.subprocess.run")
    def test_table_probe_distinguishes_absence_from_other_failures(self, run_mock) -> None:
        runner = NftRunner(Path("/usr/sbin/nft"))
        run_mock.return_value = subprocess.CompletedProcess([], 1, "", "No such file or directory")
        self.assertFalse(runner.table_exists())
        run_mock.return_value = subprocess.CompletedProcess([], 1, "", "Operation not permitted")
        with self.assertRaisesRegex(NftError, "Operation not permitted"):
            runner.table_exists()


if __name__ == "__main__":
    unittest.main()
