from __future__ import annotations

from pathlib import Path
import ast
import importlib
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
CRASH_STATE = ROOT / "pia_bazzite" / "kill_switch_crash_state.py"
GUI = ROOT / "pia_bazzite" / "gui.py"
DRIVER = ROOT / "tools" / "pia-bazzite-stage7d-adversarial-driver.py"
HOST_TEST = ROOT / "tools" / "kill-switch-crash-stage7d-host-test.sh"
RESET = ROOT / "tools" / "kill-switch-crash-stage7d-emergency-reset.sh"
SELF_TEST = ROOT / "tools" / "kill-switch-crash-stage7d-self-test.sh"
DOC = ROOT / "docs" / "kill-switch" / "KILL_SWITCH_CRASH_STAGE7D.md"
TESTING = ROOT / "TESTING.md"


class Stage7DStaticTests(unittest.TestCase):
    def test_verified_release_cleanup_unlinks_only_fixed_non_directory_entry(self) -> None:
        source = CRASH_STATE.read_text(encoding="utf-8")
        start = source.index("    def discard_untrusted_after_verified_release")
        end = source.index("\n\nclass CrashRecoveryDisposition", start)
        body = source[start:end]
        self.assertIn("_require_safe_parent(parent)", body)
        self.assertIn("self.path.lstat()", body)
        self.assertIn("stat.S_ISDIR", body)
        self.assertIn("stat.S_ISREG", body)
        self.assertIn("stat.S_ISLNK", body)
        self.assertIn("self.path.unlink()", body)
        self.assertNotIn("resolve(", body)
        self.assertNotIn("rmtree", body)

    def test_gui_uses_relaxed_path_cleanup_only_after_safe_release(self) -> None:
        source = GUI.read_text(encoding="utf-8")
        start = source.index("    def _clear_crash_recovery_record_after_safe_release")
        end = source.index("\n    def _protected_reconnect_context_available", start)
        body = source[start:end]
        self.assertIn("discard_untrusted_after_verified_release", body)
        startup = source[
            source.index("    def _reconcile_kill_switch_startup") :
            source.index("    def _recheck_kill_switch_status")
        ]
        self.assertIn("CrashRecoveryDisposition.CLEAR_STALE_RECORD", startup)
        self.assertIn("self._crash_recovery_journal.clear()", startup)
        self.assertNotIn("discard_untrusted_after_verified_release", startup)

    def test_dynamic_loader_executes_a_slotted_dataclass_module_on_current_python(self) -> None:
        source = DRIVER.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(DRIVER))
        loader_node = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_load_module"
        )
        isolated = ast.Module(body=[loader_node], type_ignores=[])
        ast.fix_missing_locations(isolated)
        namespace = {
            "importlib": importlib,
            "sys": sys,
            "Path": Path,
        }
        exec(compile(isolated, str(DRIVER), "exec"), namespace)
        load_module = namespace["_load_module"]

        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture = Path(temporary_directory) / "slotted_fixture.py"
            fixture.write_text(
                "from dataclasses import dataclass\n"
                "@dataclass(frozen=True, slots=True)\n"
                "class Fixture:\n"
                "    value: str\n",
                encoding="utf-8",
            )
            module_name = "pia_stage7d_dynamic_loader_fixture"
            previous = sys.modules.get(module_name)
            try:
                loaded = load_module(module_name, fixture)
                self.assertEqual(loaded.Fixture("ok").value, "ok")
                self.assertIs(sys.modules.get(module_name), loaded)
            finally:
                if previous is None:
                    sys.modules.pop(module_name, None)
                else:
                    sys.modules[module_name] = previous

    def test_dynamic_loader_registers_module_before_exec_and_cleans_failed_import(self) -> None:
        source = DRIVER.read_text(encoding="utf-8")
        start = source.index("def _load_module")
        end = source.index("\n\nstage7b =", start)
        body = source[start:end]
        register = body.index("sys.modules[name] = module")
        execute = body.index("spec.loader.exec_module(module)")
        self.assertLess(register, execute)
        self.assertIn("sys.modules.pop(name, None)", body)
        self.assertIn("sys.modules[name] = previous", body)

    def test_real_driver_covers_corrupt_record_unowned_lock_and_clean_restart(self) -> None:
        source = DRIVER.read_text(encoding="utf-8")
        self.assertIn("_write_corrupt_private_record", source)
        self.assertIn("_observe_corrupt_record_refusal", source)
        self.assertIn("_create_unowned_verified_lock", source)
        self.assertIn("_observe_unowned_lock_refusal", source)
        self.assertIn("CrashLeakSentinel", source)
        self.assertIn("discard_untrusted_after_verified_release", source)
        self.assertIn("_wait_for_clean_startup_reconciliation", source)
        self.assertIn("SYNTHETIC_ENDPOINT = \"192.0.2.1:1337\"", source)
        self.assertNotIn("shell=True", source)

    def test_unowned_lock_refusal_never_fabricates_recovery_record_or_vpn(self) -> None:
        source = DRIVER.read_text(encoding="utf-8")
        start = source.index("def _observe_unowned_lock_refusal")
        end = source.index("\ndef _run_verified_emergency_reset", start)
        body = source[start:end]
        self.assertIn("network_manager.connection_state().connected", body)
        self.assertIn("crash_recovery_path()", body)
        self.assertIn("_require_verified_lock", body)
        self.assertIn("sentinel.assert_running_and_clean", body)
        self.assertNotIn(".disable(", body)
        self.assertNotIn("emergency_reset(", body)

    def test_emergency_reset_verifies_host_absence_before_untrusted_record_cleanup(self) -> None:
        source = RESET.read_text(encoding="utf-8")
        vpn_down = source.index("nmcli connection down id 'PIA Bazzite'")
        table_destroy = source.index('destroy table inet "$TABLE"')
        table_verify = source.index('list table inet "$TABLE"', table_destroy)
        vpn_verify = source.index("connection show --active", table_verify)
        record_cleanup = source.index("discard_untrusted_after_verified_release", vpn_verify)
        self.assertLess(vpn_down, table_destroy)
        self.assertLess(table_destroy, table_verify)
        self.assertLess(table_verify, vpn_verify)
        self.assertLess(vpn_verify, record_cleanup)
        self.assertNotIn("rm -rf", source)

    def test_host_wrapper_arms_fail_safe_before_real_driver(self) -> None:
        source = HOST_TEST.read_text(encoding="utf-8")
        arm = source.index("systemd-run")
        driver = source.index("pia-bazzite-stage7d-adversarial-driver.py")
        self.assertLess(arm, driver)
        self.assertIn("FAIL-CLOSED STOP", source)
        self.assertIn("kill-switch-crash-stage7d-emergency-reset.sh", source)

    def test_old_process_proof_experiments_are_documented_as_superseded(self) -> None:
        doc = DOC.read_text(encoding="utf-8")
        testing = TESTING.read_text(encoding="utf-8")
        self.assertIn("7C.4", doc)
        self.assertIn("superseded", doc.casefold())
        self.assertIn("Stage 7D", testing)
        self.assertIn("7C.1", testing)
        self.assertIn("7C.3", testing)
        self.assertIn("superseded", testing.casefold())

    def test_self_test_is_unprivileged_and_does_not_run_real_host_tools(self) -> None:
        source = SELF_TEST.read_text(encoding="utf-8")
        self.assertNotIn("sudo ", source)
        self.assertNotIn("pkexec", source)
        self.assertNotIn("nmcli", source)
        self.assertNotIn("systemd-run", source)
        self.assertNotIn("stage7d-host-test.sh\"", source)
        self.assertIn("python3 -m unittest discover", source)
        self.assertIn("self_test.py", source)


if __name__ == "__main__":
    unittest.main()
