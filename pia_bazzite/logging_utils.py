from __future__ import annotations

import ipaddress
import re


SECRET_PATTERNS = (
    (re.compile(r"(?i)(password\s*[=:]\s*)\S+"), r"\1<redacted>"),
    (re.compile(r"(?i)(privatekey\s*[=:]\s*)\S+"), r"\1<redacted>"),
    (re.compile(r"(?i)(\bpt=)[^&\s]+"), r"\1<redacted>"),
    (re.compile(r"\b[A-Za-z0-9]{80,}\b"), "<redacted-token>"),
)
IPV4_PATTERN = re.compile(
    r"(?<![\d.])(?:25[0-5]|2[0-4]\d|1?\d?\d)"
    r"(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}(?![\d.])"
)
IPV6_CANDIDATE_PATTERN = re.compile(r"(?<![0-9A-Fa-f:])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?![0-9A-Fa-f:])")


def mask_ip_address(value: str) -> str:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return value
    if address.version == 4:
        parts = value.split(".")
        return ".".join(parts[:3] + ["xxx"])
    exploded = address.exploded.split(":")
    return ":".join(exploded[:3] + ["xxxx", "xxxx", "xxxx", "xxxx", "xxxx"])


def redact_secrets(text: str) -> str:
    result = text
    for pattern, replacement in SECRET_PATTERNS:
        result = pattern.sub(replacement, result)
    result = IPV4_PATTERN.sub(lambda match: mask_ip_address(match.group(0)), result)

    def mask_ipv6(match: re.Match[str]) -> str:
        candidate = match.group(0)
        return mask_ip_address(candidate)

    return IPV6_CANDIDATE_PATTERN.sub(mask_ipv6, result)
