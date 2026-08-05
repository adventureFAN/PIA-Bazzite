from __future__ import annotations

import json
import unittest

from helper.pia_bazzite_kill_switch_helper.core import (
    CHAIN_COMMENT,
    CHAIN_NAME,
    ENDPOINT_SET_V4,
    ENDPOINT_SET_V6,
    PHYSICAL_INTERFACE_SET,
    TABLE_COMMENT,
    TABLE_NAME,
    ValidationError,
    disabled_status,
    normalize_endpoints,
    normalize_interfaces,
    parse_endpoint,
    parse_status_json,
    render_add_endpoint,
    render_disable_ruleset,
    render_enable_ruleset,
    render_remove_endpoint,
    render_set_endpoints,
    render_set_interfaces,
    validate_interface,
)


class InterfaceValidationTests(unittest.TestCase):
    def test_accepts_common_linux_interface_names(self) -> None:
        self.assertEqual(validate_interface("wlo1"), "wlo1")
        self.assertEqual(validate_interface("enp5s0"), "enp5s0")
        self.assertEqual(validate_interface("wlx00:11"), "wlx00:11")

    def test_rejects_shell_metacharacters_and_whitespace(self) -> None:
        for value in ("wlo1;id", "wlo1 $(id)", " wlo1", "wlo1\n", 'wlo1"'):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                validate_interface(value)

    def test_rejects_loopback_vpn_and_too_long_names(self) -> None:
        for value in ("lo", "piabazzite", "abcdefghijklmnop"):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                validate_interface(value)

    def test_normalizes_deduplicates_and_sorts(self) -> None:
        self.assertEqual(normalize_interfaces(["wlo1", "enp5s0", "wlo1"]), ("enp5s0", "wlo1"))

    def test_requires_at_least_one_interface(self) -> None:
        with self.assertRaises(ValidationError):
            normalize_interfaces([])


class EndpointValidationTests(unittest.TestCase):
    def test_parses_ipv4_and_ipv6(self) -> None:
        ipv4 = parse_endpoint("198.51.100.1:1337")
        ipv6 = parse_endpoint("[2001:db8::1]:51820")
        self.assertEqual(ipv4.canonical, "198.51.100.1:1337")
        self.assertEqual(ipv6.canonical, "[2001:db8::1]:51820")

    def test_rejects_hostnames_and_ambiguous_ipv6(self) -> None:
        for value in ("vpn.example.test:1337", "2001:db8::1:1337", "[2001:db8::1]1337"):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                parse_endpoint(value)

    def test_rejects_bad_ports_and_special_addresses(self) -> None:
        for value in (
            "198.51.100.1:0",
            "198.51.100.1:65536",
            "198.51.100.1:https",
            "127.0.0.1:1337",
            "0.0.0.0:1337",
            "224.0.0.1:1337",
            "[::1]:1337",
            "[::]:1337",
            "[ff02::1]:1337",
            "169.254.1.1:1337",
            "[fe80::1]:1337",
        ):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                parse_endpoint(value)

    def test_normalizes_mixed_families_without_cross_family_comparison(self) -> None:
        endpoints = normalize_endpoints(
            ["[2001:db8::1]:1337", "198.51.100.1:1337", "198.51.100.1:1337"]
        )
        self.assertEqual([item.canonical for item in endpoints], [
            "198.51.100.1:1337",
            "[2001:db8::1]:1337",
        ])


class RulesetRenderingTests(unittest.TestCase):
    def test_enable_uses_final_set_based_structure(self) -> None:
        ruleset = render_enable_ruleset(
            ["wlo1", "enp5s0"],
            ["198.51.100.1:1337", "[2001:db8::1]:51820"],
        )
        self.assertTrue(ruleset.startswith(f"destroy table inet {TABLE_NAME}\n"))
        self.assertIn(f"table inet {TABLE_NAME}", ruleset)
        self.assertIn(f"set {PHYSICAL_INTERFACE_SET}", ruleset)
        self.assertIn("type ifname", ruleset)
        self.assertIn('elements = { "enp5s0", "wlo1" }', ruleset)
        self.assertIn(f"set {ENDPOINT_SET_V4}", ruleset)
        self.assertIn(f"set {ENDPOINT_SET_V6}", ruleset)
        self.assertIn("198.51.100.1 . 1337", ruleset)
        self.assertIn("2001:db8::1 . 51820", ruleset)
        self.assertIn(f"oifname @{PHYSICAL_INTERFACE_SET}", ruleset)
        self.assertIn('oifname "piabazzite"', ruleset)
        self.assertIn("reject with icmpx type admin-prohibited", ruleset)
        self.assertNotIn("flush ruleset", ruleset)
        self.assertNotIn("delete table inet firewalld", ruleset)

    def test_interface_order_does_not_change_ruleset(self) -> None:
        first = render_enable_ruleset(["wlo1", "enp5s0"], ["198.51.100.1:1337"])
        second = render_enable_ruleset(["enp5s0", "wlo1"], ["198.51.100.1:1337"])
        self.assertEqual(first, second)

    def test_set_interfaces_is_one_atomic_nft_batch(self) -> None:
        script = render_set_interfaces(["wlo1", "enp5s0", "wlo1"])
        self.assertEqual(script, (
            f"flush set inet {TABLE_NAME} {PHYSICAL_INTERFACE_SET}\n"
            f"add element inet {TABLE_NAME} {PHYSICAL_INTERFACE_SET} "
            '{ "enp5s0", "wlo1" }\n'
        ))
        self.assertNotIn("table inet", script)

    def test_set_endpoints_replaces_both_families_atomically(self) -> None:
        script = render_set_endpoints([
            "198.51.100.2:1443",
            "[2001:db8::2]:1443",
        ])
        self.assertTrue(script.startswith(
            f"flush set inet {TABLE_NAME} {ENDPOINT_SET_V4}\n"
            f"flush set inet {TABLE_NAME} {ENDPOINT_SET_V6}\n"
        ))
        self.assertIn("198.51.100.2 . 1443", script)
        self.assertIn("2001:db8::2 . 1443", script)

    def test_endpoint_actions_never_accept_arbitrary_table_names(self) -> None:
        self.assertEqual(
            render_add_endpoint("198.51.100.1:1337"),
            f"add element inet {TABLE_NAME} {ENDPOINT_SET_V4} {{ 198.51.100.1 . 1337 }}\n",
        )
        self.assertEqual(
            render_remove_endpoint("[2001:db8::1]:51820"),
            f"destroy element inet {TABLE_NAME} {ENDPOINT_SET_V6} {{ 2001:db8::1 . 51820 }}\n",
        )
        self.assertEqual(render_disable_ruleset(), f"destroy table inet {TABLE_NAME}\n")


class StatusParsingTests(unittest.TestCase):
    def _payload(self, *, table_comment: str = TABLE_COMMENT, include_block: bool = True) -> str:
        comments = [
            "pia-bazzite:v1:loopback",
            "pia-bazzite:v1:dhcp4",
            "pia-bazzite:v1:dhcp6",
            "pia-bazzite:v1:ipv6-link",
            "pia-bazzite:v1:endpoint4",
            "pia-bazzite:v1:endpoint6",
            "pia-bazzite:v1:vpn-tunnel",
        ]
        if include_block:
            comments.append("pia-bazzite:v1:block-outside-vpn")
        rules = [
            {"rule": {"family": "inet", "table": TABLE_NAME, "chain": CHAIN_NAME,
                      "comment": comment, "expr": []}}
            for comment in comments
        ]
        return json.dumps({"nftables": [
            {"metainfo": {"json_schema_version": 1}},
            {"table": {"family": "inet", "name": TABLE_NAME, "comment": table_comment}},
            {"set": {"family": "inet", "table": TABLE_NAME,
                     "name": PHYSICAL_INTERFACE_SET, "type": "ifname"}},
            {"set": {"family": "inet", "table": TABLE_NAME, "name": ENDPOINT_SET_V4,
                     "type": ["ipv4_addr", "inet_service"]}},
            {"set": {"family": "inet", "table": TABLE_NAME, "name": ENDPOINT_SET_V6,
                     "type": ["ipv6_addr", "inet_service"]}},
            {"chain": {"family": "inet", "table": TABLE_NAME, "name": CHAIN_NAME,
                       "type": "filter", "hook": "output", "prio": -100,
                       "policy": "accept", "comment": CHAIN_COMMENT}},
            *rules,
        ]})

    def test_valid_table_is_verified(self) -> None:
        status = parse_status_json(self._payload())
        self.assertTrue(status["present"])
        self.assertTrue(status["verified"])
        self.assertEqual(status["state"], "active")
        self.assertEqual(status["problems"], [])
        self.assertIn("set-endpoints", status["capabilities"])
        self.assertEqual(status["table_generation"], 1)

    def test_missing_ownership_or_block_rule_is_error(self) -> None:
        status = parse_status_json(self._payload(table_comment="foreign", include_block=False))
        self.assertTrue(status["present"])
        self.assertFalse(status["verified"])
        self.assertEqual(status["state"], "error")
        self.assertTrue(any("ownership" in problem for problem in status["problems"]))
        self.assertTrue(any("block-outside-vpn" in problem for problem in status["problems"]))

    def test_missing_physical_interface_set_is_error(self) -> None:
        payload = json.loads(self._payload())
        payload["nftables"] = [
            item for item in payload["nftables"]
            if item.get("set", {}).get("name") != PHYSICAL_INTERFACE_SET
        ]
        status = parse_status_json(json.dumps(payload))
        self.assertFalse(status["verified"])
        self.assertTrue(any(PHYSICAL_INTERFACE_SET in problem for problem in status["problems"]))

    def test_disabled_status_is_verified_but_not_present(self) -> None:
        status = disabled_status()
        self.assertFalse(status["present"])
        self.assertTrue(status["verified"])
        self.assertEqual(status["state"], "disabled")

    def test_invalid_json_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            parse_status_json("not-json")


if __name__ == "__main__":
    unittest.main()
