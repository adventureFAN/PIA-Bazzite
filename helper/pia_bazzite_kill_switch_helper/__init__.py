"""Restricted PIA Bazzite session kill-switch helper candidate."""

from .protocol import PROTOCOL_VERSION

from .core import (
    CHAIN_NAME,
    ENDPOINT_SET_V4,
    ENDPOINT_SET_V6,
    HELPER_STAGE,
    IPV6_GUARD_CHAIN_NAME,
    IPV6_GUARD_TABLE_NAME,
    PHYSICAL_INTERFACE_SET,
    TABLE_NAME,
    VPN_INTERFACE,
    Endpoint,
    ValidationError,
)

__all__ = [
    "CHAIN_NAME",
    "ENDPOINT_SET_V4",
    "ENDPOINT_SET_V6",
    "HELPER_STAGE",
    "IPV6_GUARD_CHAIN_NAME",
    "IPV6_GUARD_TABLE_NAME",
    "PHYSICAL_INTERFACE_SET",
    "TABLE_NAME",
    "VPN_INTERFACE",
    "PROTOCOL_VERSION",
    "Endpoint",
    "ValidationError",
]
