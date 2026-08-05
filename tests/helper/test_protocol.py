from __future__ import annotations

import unittest

from helper.pia_bazzite_kill_switch_helper.protocol import (
    PROTOCOL_VERSION,
    ProtocolError,
    error_payload,
    infer_action,
    success_payload,
    validate_payload,
)


class ProtocolEnvelopeTests(unittest.TestCase):
    def test_success_payload_has_stable_envelope(self) -> None:
        payload = success_payload(
            action="status",
            helper_stage=1,
            fields={"state": "disabled", "present": False, "verified": True},
        )
        self.assertEqual(payload["protocol_version"], PROTOCOL_VERSION)
        self.assertEqual(payload["action"], "status")
        self.assertTrue(payload["ok"])
        validate_payload(payload)

    def test_error_payload_has_stable_envelope(self) -> None:
        payload = error_payload(
            action="enable",
            helper_stage=1,
            kind="validation",
            message="bad request",
        )
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["action"], "enable")
        self.assertEqual(payload["error"], "validation")
        validate_payload(payload)

    def test_unknown_action_is_reported_without_echoing_arbitrary_text(self) -> None:
        payload = error_payload(
            action="$(touch /tmp/nope)",
            helper_stage=1,
            kind="validation",
            message="unsupported action",
        )
        self.assertEqual(payload["action"], "unknown")
        validate_payload(payload)

    def test_infer_action_uses_only_known_action_tokens(self) -> None:
        self.assertEqual(infer_action(["enable", "--interface", "wlo1"]).action, "enable")
        self.assertEqual(infer_action(["totally-unknown"]).response_action, "unknown")
        self.assertEqual(infer_action([]).response_action, "unknown")

    def test_conflicting_envelope_fields_are_rejected(self) -> None:
        with self.assertRaises(ProtocolError):
            success_payload(
                action="status",
                helper_stage=1,
                fields={"protocol_version": 999},
            )

    def test_invalid_payload_shape_is_rejected(self) -> None:
        with self.assertRaises(ProtocolError):
            validate_payload({"ok": True})


if __name__ == "__main__":
    unittest.main()
