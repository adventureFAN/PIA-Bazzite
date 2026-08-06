from __future__ import annotations

import unittest

from pia_bazzite.kill_switch_state import (
    KillSwitchMode,
    KillSwitchObservation,
    derive_kill_switch_view_state,
    sample_kill_switch_states,
    status_color_hex,
)


class KillSwitchStateTests(unittest.TestCase):
    def test_ready_means_feature_off_vpn_off_and_no_table(self) -> None:
        state = derive_kill_switch_view_state(
            KillSwitchObservation.create(
                feature_enabled=False,
                vpn_connected=False,
                table_present=False,
                table_verified=False,
            )
        )
        self.assertIs(state.mode, KillSwitchMode.READY)
        self.assertFalse(state.feature_enabled)
        self.assertFalse(state.firewall_active)
        self.assertFalse(state.protection_guaranteed)
        self.assertEqual(state.icon_state, "ready")

    def test_armed_means_enabled_but_intentionally_disconnected(self) -> None:
        state = derive_kill_switch_view_state(
            KillSwitchObservation.create(
                feature_enabled=True,
                vpn_connected=False,
                table_present=False,
                table_verified=True,
            )
        )
        self.assertIs(state.mode, KillSwitchMode.ARMED)
        self.assertTrue(state.feature_enabled)
        self.assertFalse(state.firewall_active)
        self.assertFalse(state.protection_guaranteed)

    def test_vpn_only_is_not_misreported_as_full_kill_switch_protection(self) -> None:
        state = derive_kill_switch_view_state(
            KillSwitchObservation.create(
                feature_enabled=False,
                vpn_connected=True,
                table_present=False,
                table_verified=False,
            )
        )
        self.assertIs(state.mode, KillSwitchMode.VPN_ONLY)
        self.assertFalse(state.feature_enabled)
        self.assertFalse(state.protection_guaranteed)
        self.assertEqual(state.icon_state, "vpn_only")

    def test_active_requires_connected_vpn_and_verified_table(self) -> None:
        state = derive_kill_switch_view_state(
            KillSwitchObservation.create(
                feature_enabled=True,
                vpn_connected=True,
                table_present=True,
                table_verified=True,
            )
        )
        self.assertIs(state.mode, KillSwitchMode.ACTIVE)
        self.assertTrue(state.firewall_active)
        self.assertTrue(state.protection_guaranteed)

    def test_blocking_requires_verified_table_without_vpn(self) -> None:
        state = derive_kill_switch_view_state(
            KillSwitchObservation.create(
                feature_enabled=True,
                vpn_connected=False,
                table_present=True,
                table_verified=True,
            )
        )
        self.assertIs(state.mode, KillSwitchMode.BLOCKING)
        self.assertTrue(state.firewall_active)
        self.assertTrue(state.protection_guaranteed)

    def test_connected_vpn_without_verified_table_is_error_when_enabled(self) -> None:
        state = derive_kill_switch_view_state(
            KillSwitchObservation.create(
                feature_enabled=True,
                vpn_connected=True,
                table_present=False,
                table_verified=False,
            )
        )
        self.assertIs(state.mode, KillSwitchMode.ERROR)
        self.assertTrue(state.diagnostic)
        self.assertFalse(state.protection_guaranteed)

    def test_present_table_is_error_when_feature_is_disabled(self) -> None:
        state = derive_kill_switch_view_state(
            KillSwitchObservation.create(
                feature_enabled=False,
                vpn_connected=False,
                table_present=True,
                table_verified=True,
            )
        )
        self.assertIs(state.mode, KillSwitchMode.ERROR)
        self.assertIn("disabled", state.diagnostic)

    def test_present_unverified_table_is_error(self) -> None:
        state = derive_kill_switch_view_state(
            KillSwitchObservation.create(
                feature_enabled=True,
                vpn_connected=False,
                table_present=True,
                table_verified=False,
            )
        )
        self.assertIs(state.mode, KillSwitchMode.ERROR)
        self.assertIn("not verified", state.diagnostic)

    def test_helper_problem_forces_error_even_when_table_looks_active(self) -> None:
        state = derive_kill_switch_view_state(
            KillSwitchObservation.create(
                feature_enabled=True,
                vpn_connected=True,
                table_present=True,
                table_verified=True,
                problems=("missing final block rule",),
            )
        )
        self.assertIs(state.mode, KillSwitchMode.ERROR)
        self.assertEqual(state.diagnostic, "missing final block rule")

    def test_explicit_error_is_not_hidden(self) -> None:
        state = derive_kill_switch_view_state(
            KillSwitchObservation.create(
                feature_enabled=True,
                vpn_connected=False,
                table_present=False,
                table_verified=False,
                error="helper unavailable",
            )
        )
        self.assertIs(state.mode, KillSwitchMode.ERROR)
        self.assertEqual(state.diagnostic, "helper unavailable")

    def test_problem_strings_are_normalized(self) -> None:
        observation = KillSwitchObservation.create(
            feature_enabled=True,
            vpn_connected=False,
            table_present=True,
            table_verified=True,
            problems=("  first  ", "", "second"),
        )
        self.assertEqual(observation.problems, ("first", "second"))

    def test_sample_states_cover_all_optional_modes_in_order(self) -> None:
        self.assertEqual(
            tuple(state.mode for state in sample_kill_switch_states()),
            (
                KillSwitchMode.READY,
                KillSwitchMode.ARMED,
                KillSwitchMode.VPN_ONLY,
                KillSwitchMode.ACTIVE,
                KillSwitchMode.BLOCKING,
                KillSwitchMode.ERROR,
            ),
        )

    def test_each_state_has_stable_translation_and_log_metadata(self) -> None:
        for state in sample_kill_switch_states():
            self.assertTrue(state.title_key.startswith("kill_switch.state."))
            self.assertTrue(state.summary_key.startswith("kill_switch.summary."))
            self.assertTrue(state.detail_key.startswith("kill_switch.detail."))
            self.assertTrue(state.tray_status_key.startswith("tray.kill_switch_status."))
            self.assertTrue(state.tray_tooltip_key.startswith("tray.kill_switch_tooltip."))
            self.assertTrue(state.log_key.startswith("log.kill_switch."))
            self.assertIn(state.log_level, {"info", "ok", "warning", "error"})


class KillSwitchColorTests(unittest.TestCase):
    def test_ready_is_light_gray_on_dark_background(self) -> None:
        self.assertEqual(status_color_hex("ready", dark_mode=True), "#b0bec5")

    def test_ready_is_dark_gray_on_light_background(self) -> None:
        self.assertEqual(status_color_hex("ready", dark_mode=False), "#546e7a")

    def test_armed_remains_neutral(self) -> None:
        self.assertEqual(status_color_hex("armed", dark_mode=True), "#cfd8dc")
        self.assertEqual(status_color_hex("armed", dark_mode=False), "#78909c")

    def test_vpn_only_has_distinct_blue_status(self) -> None:
        self.assertEqual(status_color_hex("vpn_only", dark_mode=True), "#64b5f6")
        self.assertEqual(status_color_hex("vpn_only", dark_mode=False), "#1565c0")

    def test_fixed_security_colors(self) -> None:
        self.assertEqual(status_color_hex("active", dark_mode=False), "#2e7d32")
        self.assertEqual(status_color_hex("blocking", dark_mode=False), "#ef6c00")
        self.assertEqual(status_color_hex("error", dark_mode=False), "#c62828")

    def test_legacy_icon_names_map_to_stage4_states(self) -> None:
        self.assertEqual(
            status_color_hex("connected", dark_mode=False),
            status_color_hex("active", dark_mode=False),
        )
        self.assertEqual(
            status_color_hex("disconnected", dark_mode=True),
            status_color_hex("ready", dark_mode=True),
        )
        self.assertEqual(
            status_color_hex("busy", dark_mode=False),
            status_color_hex("blocking", dark_mode=False),
        )


if __name__ == "__main__":
    unittest.main()
