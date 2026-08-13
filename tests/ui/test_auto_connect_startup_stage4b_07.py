from __future__ import annotations

import json
from pathlib import Path
import unittest

from pia_bazzite.auto_connect import (
    AUTO_CONNECT_FASTEST,
    AUTO_CONNECT_LAST,
    AUTO_CONNECT_OFF,
    region_auto_connect_target,
    resolve_auto_connect_region_id,
)


ROOT = Path(__file__).resolve().parents[2]
GUI = ROOT / "pia_bazzite" / "gui.py"
DE = ROOT / "pia_bazzite" / "resources" / "i18n" / "de.json"
EN = ROOT / "pia_bazzite" / "resources" / "i18n" / "en.json"


class Stage4BAutoConnectStartupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.gui = GUI.read_text(encoding="utf-8")
        cls.de = json.loads(DE.read_text(encoding="utf-8"))
        cls.en = json.loads(EN.read_text(encoding="utf-8"))

    def test_target_resolution_never_invents_fixed_fallback(self) -> None:
        self.assertIsNone(
            resolve_auto_connect_region_id(
                AUTO_CONNECT_OFF,
                last_selected_region_id="de-frankfurt",
                fastest_region_id="nl-amsterdam",
                fastest_selection_id="__fastest__",
            )
        )
        self.assertEqual(
            resolve_auto_connect_region_id(
                AUTO_CONNECT_FASTEST,
                last_selected_region_id="de-frankfurt",
                fastest_region_id="nl-amsterdam",
                fastest_selection_id="__fastest__",
            ),
            "nl-amsterdam",
        )
        self.assertEqual(
            resolve_auto_connect_region_id(
                AUTO_CONNECT_LAST,
                last_selected_region_id="de-frankfurt",
                fastest_region_id="nl-amsterdam",
                fastest_selection_id="__fastest__",
            ),
            "de-frankfurt",
        )
        self.assertEqual(
            resolve_auto_connect_region_id(
                AUTO_CONNECT_LAST,
                last_selected_region_id="__fastest__",
                fastest_region_id="nl-amsterdam",
                fastest_selection_id="__fastest__",
            ),
            "nl-amsterdam",
        )
        self.assertEqual(
            resolve_auto_connect_region_id(
                region_auto_connect_target("ng-lagos"),
                last_selected_region_id="de-frankfurt",
                fastest_region_id="nl-amsterdam",
                fastest_selection_id="__fastest__",
            ),
            "ng-lagos",
        )

    def test_startup_auto_connect_has_explicit_one_shot_and_readiness_gates(self) -> None:
        start = self.gui.index("    def _maybe_startup_auto_connect")
        end = self.gui.index("    # ------------------------------------------------------------------\n    # Worker helpers", start)
        block = self.gui[start:end]
        self.assertIn("self._startup_auto_connect_attempted", block)
        self.assertIn("self._startup_first_run_flow_complete", block)
        self.assertIn("self._initial_region_refresh_complete", block)
        self.assertIn("self._startup_kill_switch_reconciliation_complete", block)
        self.assertIn("self._startup_ipv6_guard_reconciliation_complete", block)
        self.assertIn("self._connection_busy", block)

    def test_off_path_finishes_without_opening_helper_or_connecting(self) -> None:
        start = self.gui.index("    def _maybe_startup_auto_connect")
        end = self.gui.index("        if not self._initial_setup_done", start)
        block = self.gui[start:end]
        self.assertIn("if target == AUTO_CONNECT_OFF", block)
        self.assertIn("self._startup_auto_connect_attempted = True", block)
        self.assertNotIn("connect_region", block)
        self.assertNotIn("_ensure_packaged_kill_switch_helper", block)

    def test_first_run_modal_must_finish_before_credential_gate_can_skip(self) -> None:
        init = self.gui[self.gui.index("class MainWindow"):self.gui.index("    @staticmethod\n    def _set_demi_bold")]
        self.assertIn("self._startup_first_run_flow_complete = False", init)
        first_start = self.gui[self.gui.index("    def _first_start"):self.gui.index("    def edit_credentials", self.gui.index("    def _first_start"))]
        self.assertIn("self._startup_first_run_flow_complete = True", first_start)
        auto = self.gui[self.gui.index("    def _maybe_startup_auto_connect"):self.gui.index("    # ------------------------------------------------------------------\n    # Worker helpers", self.gui.index("    def _maybe_startup_auto_connect"))]
        self.assertIn("not self._startup_first_run_flow_complete", auto)

    def test_initial_region_refresh_success_triggers_and_failure_suppresses(self) -> None:
        start = self.gui.index("    def refresh_regions")
        end = self.gui.index("    def refresh_pings", start)
        block = self.gui[start:end]
        self.assertIn("self._initial_region_refresh_complete = True", block)
        self.assertIn("self._initial_region_refresh_failed = False", block)
        self.assertIn("self._initial_region_refresh_failed = True", block)
        self.assertGreaterEqual(block.count("self._maybe_startup_auto_connect()"), 2)

    def test_existing_vpn_and_protected_recovery_take_priority(self) -> None:
        start = self.gui.index("    def _maybe_startup_auto_connect")
        end = self.gui.index("    # ------------------------------------------------------------------\n    # Worker helpers", start)
        block = self.gui[start:end]
        self.assertIn("if connected:", block)
        self.assertIn('"log.auto_connect.already_connected"', block)
        self.assertIn("self._disconnected_kill_switch_may_block(connected=False)", block)
        self.assertIn('"log.auto_connect.recovery_priority"', block)

    def test_fastest_requires_a_reachable_ping(self) -> None:
        start = self.gui.index("    def _startup_fastest_region")
        end = self.gui.index("    def _resolve_startup_auto_connect_region", start)
        block = self.gui[start:end]
        self.assertIn("region.ping_ms is not None", block)
        self.assertIn("None", block)

    def test_missing_fixed_or_last_target_is_logged_and_never_falls_back(self) -> None:
        resolver_start = self.gui.index("    def _resolve_startup_auto_connect_region")
        resolver_end = self.gui.index("    def _maybe_startup_auto_connect", resolver_start)
        resolver = self.gui[resolver_start:resolver_end]
        self.assertIn("return self._region_by_id(region_id)", resolver)
        self.assertNotIn("or self._startup_fastest_region", resolver)

        auto = self.gui[self.gui.index("    def _maybe_startup_auto_connect"):self.gui.index("    # ------------------------------------------------------------------\n    # Worker helpers", self.gui.index("    def _maybe_startup_auto_connect"))]
        self.assertIn('"log.auto_connect.target_unavailable"', auto)

    def test_actual_connection_reuses_existing_connect_region_path_once(self) -> None:
        start = self.gui.index("    def _maybe_startup_auto_connect")
        end = self.gui.index("    # ------------------------------------------------------------------\n    # Worker helpers", start)
        block = self.gui[start:end]
        self.assertEqual(block.count("self.connect_region(region)"), 1)
        self.assertLess(
            block.index("self._startup_auto_connect_attempted = True", block.index("region =")),
            block.index("self.connect_region(region)"),
        )
        self.assertNotIn("create_wireguard_config", block)
        self.assertNotIn("network_manager.connect", block)

    def test_startup_reconciliation_completes_gates_only_on_safe_paths(self) -> None:
        kill = self.gui[self.gui.index("    def _reconcile_kill_switch_startup"):self.gui.index("    def _recheck_kill_switch_status")]
        self.assertIn("self._startup_kill_switch_reconciliation_complete = True", kill)
        self.assertIn("CrashRecoveryDisposition.NO_RECOVERY", kill)
        self.assertIn("CrashRecoveryDisposition.CLEAR_STALE_RECORD", kill)

        ipv6 = self.gui[self.gui.index("    def _reconcile_ipv6_guard_startup"):self.gui.index("    def _log_connection_events")]
        self.assertIn("self._startup_ipv6_guard_reconciliation_complete = True", ipv6)
        failure = ipv6[ipv6.index("        def failure") :]
        self.assertNotIn("self._startup_ipv6_guard_reconciliation_complete = True", failure)

    def test_auto_connect_copy_is_active_and_bilingual(self) -> None:
        self.assertNotIn("folgenden 0.7-Etappe", self.de["options.auto_connect_tooltip"])
        self.assertNotIn("following 0.7 stage", self.en["options.auto_connect_tooltip"].lower())
        self.assertIn("Startprüfungen", self.de["options.auto_connect_tooltip"])
        self.assertIn("startup checks", self.en["options.auto_connect_tooltip"])
        for key in (
            "log.auto_connect.starting",
            "log.auto_connect.already_connected",
            "log.auto_connect.recovery_priority",
            "log.auto_connect.target_unavailable",
            "log.auto_connect.regions_unavailable",
            "log.auto_connect.credentials_missing",
            "log.auto_connect.skipped_busy",
            "log.auto_connect.state_unknown",
        ):
            self.assertIn(key, self.de)
            self.assertIn(key, self.en)
        self.assertEqual(set(self.de), set(self.en))


if __name__ == "__main__":
    unittest.main()
