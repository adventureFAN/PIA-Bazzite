from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import json
import re
from typing import Any, Iterable, Sequence

HELPER_STAGE = 1
SCHEMA_VERSION = 1
TABLE_NAME = "pia_bazzite_killswitch_helper_test"
CHAIN_NAME = "output"
ENDPOINT_SET_V4 = "allowed_endpoints_v4"
ENDPOINT_SET_V6 = "allowed_endpoints_v6"
VPN_INTERFACE = "piabazzite"
TABLE_COMMENT = "PIA Bazzite helper stage 1 test table"
CHAIN_COMMENT = "PIA Bazzite helper stage 1 output chain"

MAX_INTERFACES = 8
MAX_ENDPOINTS = 32
_INTERFACE_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,15}$")

CORE_RULE_COMMENTS = {
    "pia-bazzite:test:loopback",
    "pia-bazzite:test:vpn-tunnel",
    "pia-bazzite:test:block-outside-vpn",
}


class ValidationError(ValueError):
    """Raised when untrusted helper input fails strict validation."""


@dataclass(frozen=True, slots=True)
class Endpoint:
    address: ipaddress.IPv4Address | ipaddress.IPv6Address
    port: int

    @property
    def family(self) -> int:
        return self.address.version

    @property
    def canonical(self) -> str:
        if self.family == 6:
            return f"[{self.address.compressed}]:{self.port}"
        return f"{self.address.compressed}:{self.port}"

    @property
    def nft_element(self) -> str:
        return f"{self.address.compressed} . {self.port}"


def validate_interface(value: str) -> str:
    if not isinstance(value, str):
        raise ValidationError("Interface names must be strings.")
    if value != value.strip() or not _INTERFACE_PATTERN.fullmatch(value):
        raise ValidationError(
            "Invalid interface name. Use 1-15 characters from A-Z, a-z, 0-9, _, ., :, or -."
        )
    if value in {"lo", VPN_INTERFACE}:
        raise ValidationError(f"Interface {value!r} cannot be used as a physical interface.")
    return value


def normalize_interfaces(values: Iterable[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = validate_interface(raw)
        if value not in seen:
            seen.add(value)
            normalized.append(value)
    if not normalized:
        raise ValidationError("At least one physical interface is required.")
    if len(normalized) > MAX_INTERFACES:
        raise ValidationError(f"At most {MAX_INTERFACES} physical interfaces are allowed.")
    return tuple(sorted(normalized))


def parse_endpoint(value: str) -> Endpoint:
    if not isinstance(value, str):
        raise ValidationError("Endpoints must be strings.")
    if value != value.strip() or not value:
        raise ValidationError("Endpoint must not be empty or contain surrounding whitespace.")

    host: str
    port_text: str
    if value.startswith("["):
        close = value.find("]")
        if close <= 1 or close + 1 >= len(value) or value[close + 1] != ":":
            raise ValidationError("IPv6 endpoints must use [address]:port syntax.")
        host = value[1:close]
        port_text = value[close + 2 :]
    else:
        if value.count(":") != 1:
            raise ValidationError("IPv4 endpoints must use address:port syntax.")
        host, port_text = value.rsplit(":", 1)

    if not port_text.isascii() or not port_text.isdecimal():
        raise ValidationError("Endpoint port must be a decimal integer.")
    port = int(port_text, 10)
    if not 1 <= port <= 65535:
        raise ValidationError("Endpoint port must be between 1 and 65535.")

    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ValidationError("Endpoint address must be a numeric IPv4 or IPv6 address.") from exc

    if address.is_unspecified or address.is_loopback or address.is_multicast or address.is_link_local:
        raise ValidationError(
            "Unspecified, loopback, multicast, and link-local endpoints are not allowed."
        )
    if isinstance(address, ipaddress.IPv6Address) and address.scope_id is not None:
        raise ValidationError("Scoped IPv6 endpoints are not allowed.")

    return Endpoint(address=address, port=port)


def normalize_endpoints(values: Iterable[str | Endpoint]) -> tuple[Endpoint, ...]:
    normalized: list[Endpoint] = []
    seen: set[Endpoint] = set()
    for raw in values:
        endpoint = raw if isinstance(raw, Endpoint) else parse_endpoint(raw)
        if endpoint not in seen:
            seen.add(endpoint)
            normalized.append(endpoint)
    if not normalized:
        raise ValidationError("At least one WireGuard endpoint is required.")
    if len(normalized) > MAX_ENDPOINTS:
        raise ValidationError(f"At most {MAX_ENDPOINTS} endpoints are allowed.")
    return tuple(sorted(normalized, key=lambda item: (item.family, int(item.address), item.port)))


def _quote_nft_string(value: str) -> str:
    # All callers validate against a strict interface-name allowlist. Keeping the
    # quoting function explicit makes the trust boundary visible.
    if not _INTERFACE_PATTERN.fullmatch(value):
        raise ValidationError("Unsafe nftables string.")
    return f'"{value}"'


def _set_block(name: str, nft_type: str, elements: Sequence[Endpoint]) -> list[str]:
    lines = [f"  set {name} {{", f"    type {nft_type}", "    size 32"]
    if elements:
        joined = ", ".join(endpoint.nft_element for endpoint in elements)
        lines.append(f"    elements = {{ {joined} }}")
    lines.append("  }")
    return lines


def render_enable_ruleset(
    interfaces: Iterable[str],
    endpoints: Iterable[str | Endpoint],
) -> str:
    physical_interfaces = normalize_interfaces(interfaces)
    normalized_endpoints = normalize_endpoints(endpoints)
    endpoints_v4 = [endpoint for endpoint in normalized_endpoints if endpoint.family == 4]
    endpoints_v6 = [endpoint for endpoint in normalized_endpoints if endpoint.family == 6]

    lines = [
        f"destroy table inet {TABLE_NAME}",
        f"table inet {TABLE_NAME} {{",
        f'  comment "{TABLE_COMMENT}"',
    ]
    lines.extend(_set_block(ENDPOINT_SET_V4, "ipv4_addr . inet_service", endpoints_v4))
    lines.extend(_set_block(ENDPOINT_SET_V6, "ipv6_addr . inet_service", endpoints_v6))
    lines.extend(
        [
            f"  chain {CHAIN_NAME} {{",
            "    type filter hook output priority -100; policy accept;",
            f'    comment "{CHAIN_COMMENT}"',
            '    oifname "lo" counter accept comment "pia-bazzite:test:loopback"',
        ]
    )

    for interface in physical_interfaces:
        quoted = _quote_nft_string(interface)
        lines.extend(
            [
                f"    ip protocol udp udp sport 68 udp dport 67 oifname {quoted} "
                f'counter accept comment "pia-bazzite:test:dhcp4:{interface}"',
                f"    ip6 nexthdr udp udp sport 546 udp dport 547 oifname {quoted} "
                f'counter accept comment "pia-bazzite:test:dhcp6:{interface}"',
                "    ip6 nexthdr icmpv6 icmpv6 type { nd-router-solicit, "
                "nd-neighbor-solicit, nd-neighbor-advert } "
                f"oifname {quoted} counter accept "
                f'comment "pia-bazzite:test:ipv6-link:{interface}"',
                f"    ip daddr . udp dport @{ENDPOINT_SET_V4} oifname {quoted} "
                f'counter accept comment "pia-bazzite:test:endpoint4:{interface}"',
                f"    ip6 daddr . udp dport @{ENDPOINT_SET_V6} oifname {quoted} "
                f'counter accept comment "pia-bazzite:test:endpoint6:{interface}"',
            ]
        )

    lines.extend(
        [
            f'    oifname "{VPN_INTERFACE}" counter accept comment "pia-bazzite:test:vpn-tunnel"',
            "    counter reject with icmpx type admin-prohibited "
            'comment "pia-bazzite:test:block-outside-vpn"',
            "  }",
            "}",
            "",
        ]
    )
    return "\n".join(lines)


def render_add_endpoint(endpoint: str | Endpoint) -> str:
    parsed = endpoint if isinstance(endpoint, Endpoint) else parse_endpoint(endpoint)
    set_name = ENDPOINT_SET_V4 if parsed.family == 4 else ENDPOINT_SET_V6
    return (
        f"add element inet {TABLE_NAME} {set_name} "
        f"{{ {parsed.nft_element} }}\n"
    )


def render_remove_endpoint(endpoint: str | Endpoint) -> str:
    parsed = endpoint if isinstance(endpoint, Endpoint) else parse_endpoint(endpoint)
    set_name = ENDPOINT_SET_V4 if parsed.family == 4 else ENDPOINT_SET_V6
    return (
        f"destroy element inet {TABLE_NAME} {set_name} "
        f"{{ {parsed.nft_element} }}\n"
    )


def render_disable_ruleset() -> str:
    return f"destroy table inet {TABLE_NAME}\n"


def parse_status_json(payload: str) -> dict[str, Any]:
    try:
        document = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"nftables returned invalid JSON: {exc}") from exc

    objects = document.get("nftables")
    if not isinstance(objects, list):
        raise ValidationError("nftables JSON does not contain an object list.")

    table_found = False
    table_comment = ""
    sets: dict[str, Any] = {}
    chain: dict[str, Any] | None = None
    rule_comments: set[str] = set()

    for item in objects:
        if not isinstance(item, dict):
            continue
        table_obj = item.get("table")
        if isinstance(table_obj, dict) and table_obj.get("family") == "inet" \
                and table_obj.get("name") == TABLE_NAME:
            table_found = True
            table_comment = str(table_obj.get("comment", ""))

        set_obj = item.get("set")
        if isinstance(set_obj, dict) and set_obj.get("family") == "inet" \
                and set_obj.get("table") == TABLE_NAME:
            name = set_obj.get("name")
            if isinstance(name, str):
                sets[name] = set_obj.get("type")

        chain_obj = item.get("chain")
        if isinstance(chain_obj, dict) and chain_obj.get("family") == "inet" \
                and chain_obj.get("table") == TABLE_NAME \
                and chain_obj.get("name") == CHAIN_NAME:
            chain = chain_obj

        rule_obj = item.get("rule")
        if isinstance(rule_obj, dict) and rule_obj.get("family") == "inet" \
                and rule_obj.get("table") == TABLE_NAME \
                and rule_obj.get("chain") == CHAIN_NAME:
            comment = rule_obj.get("comment")
            if isinstance(comment, str):
                rule_comments.add(comment)

    problems: list[str] = []
    if not table_found:
        problems.append("test table is missing")
    if table_found and table_comment != TABLE_COMMENT:
        problems.append("table ownership marker is missing or incorrect")

    expected_set_types = {
        ENDPOINT_SET_V4: ["ipv4_addr", "inet_service"],
        ENDPOINT_SET_V6: ["ipv6_addr", "inet_service"],
    }
    for name, expected_type in expected_set_types.items():
        actual_type = sets.get(name)
        # Older nft JSON sometimes serializes a concatenated type as a string.
        valid_types = {tuple(expected_type), tuple([" . ".join(expected_type)])}
        normalized_type = tuple(actual_type) if isinstance(actual_type, list) else (actual_type,)
        if normalized_type not in valid_types:
            problems.append(f"set {name} is missing or has the wrong type")

    if chain is None:
        problems.append("output base chain is missing")
    else:
        if chain.get("type") != "filter":
            problems.append("output chain is not a filter chain")
        if chain.get("hook") != "output":
            problems.append("output chain has the wrong hook")
        if chain.get("policy") != "accept":
            problems.append("output chain has the wrong policy")
        priority = chain.get("prio", chain.get("priority"))
        if priority not in (-100, "-100", "dstnat"):
            problems.append("output chain has the wrong priority")
        if chain.get("comment", "") != CHAIN_COMMENT:
            problems.append("output chain ownership marker is missing or incorrect")

    for comment in sorted(CORE_RULE_COMMENTS - rule_comments):
        problems.append(f"required rule marker is missing: {comment}")

    interface_categories = ("dhcp4", "dhcp6", "ipv6-link", "endpoint4", "endpoint6")
    interfaces_by_category: dict[str, set[str]] = {}
    for category in interface_categories:
        prefix = f"pia-bazzite:test:{category}:"
        interfaces: set[str] = set()
        for comment in rule_comments:
            if comment.startswith(prefix):
                candidate = comment[len(prefix):]
                try:
                    interfaces.add(validate_interface(candidate))
                except ValidationError:
                    problems.append(f"invalid interface marker in rule comment: {comment}")
        interfaces_by_category[category] = interfaces
        if not interfaces:
            problems.append(f"no {category} interface rule was found")

    reference_interfaces = interfaces_by_category["dhcp4"]
    for category in interface_categories[1:]:
        if interfaces_by_category[category] != reference_interfaces:
            problems.append(f"interface rule markers are inconsistent for {category}")

    return {
        "schema_version": SCHEMA_VERSION,
        "helper_stage": HELPER_STAGE,
        "table": TABLE_NAME,
        "present": table_found,
        "verified": table_found and not problems,
        "state": "active" if table_found and not problems else "error",
        "problems": problems,
    }


def disabled_status() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "helper_stage": HELPER_STAGE,
        "table": TABLE_NAME,
        "present": False,
        "verified": True,
        "state": "disabled",
        "problems": [],
    }
