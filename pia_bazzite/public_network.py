from __future__ import annotations

import ipaddress
import re
from typing import Final

import requests

from .app_errors import AppError
from .models import PublicNetworkInfo


COUNTRY_IS_PROVIDER: Final = "country_is"
CLOUDFLARE_PROVIDER: Final = "cloudflare"
IPWHOIS_PROVIDER: Final = "ipwhois"
FREEIPAPI_PROVIDER: Final = "freeipapi"
GEOJS_PROVIDER: Final = "geojs"

PUBLIC_NETWORK_PROVIDER_IDS: Final[tuple[str, ...]] = (
    COUNTRY_IS_PROVIDER,
    CLOUDFLARE_PROVIDER,
    IPWHOIS_PROVIDER,
    FREEIPAPI_PROVIDER,
    GEOJS_PROVIDER,
)

COUNTRY_IS_URL: Final = "https://api.country.is/"
CLOUDFLARE_TRACE_URL: Final = "https://cloudflare.com/cdn-cgi/trace"
IPWHOIS_URL: Final = "https://ipwho.is/"
FREEIPAPI_URL: Final = "https://free.freeipapi.com/api/json/"
GEOJS_URL: Final = "https://get.geojs.io/v1/ip/geo.json"
AMAZON_CHECK_IP_URL: Final = "https://checkip.amazonaws.com/"


class PublicNetworkError(AppError):
    pass


def _public_network_error(details: str) -> PublicNetworkError:
    return PublicNetworkError(
        "error.public_ip.title",
        "error.public_ip.message",
        details=details,
    )


def _validate_ip(value: object) -> str:
    if not isinstance(value, str):
        raise _public_network_error("Public-IP service returned a non-text IP address.")
    text = value.strip()
    if not text or len(text) > 64 or any(
        ord(char) < 0x20 or ord(char) == 0x7F for char in text
    ):
        raise _public_network_error("Public-IP service returned an invalid IP address.")
    try:
        address = ipaddress.ip_address(text)
    except ValueError as exc:
        raise _public_network_error(
            "Public-IP service returned a non-numeric IP address."
        ) from exc
    if address.is_unspecified or address.is_loopback or address.is_multicast:
        raise _public_network_error("Public-IP service returned a disallowed IP address.")
    return address.compressed


def _validate_country_code(value: object) -> str:
    if not isinstance(value, str):
        raise _public_network_error("Geolocation service returned a non-text country code.")
    country_code = value.strip().upper()
    if not re.fullmatch(r"[A-Z]{2}", country_code):
        raise _public_network_error("Geolocation service returned an invalid country code.")
    return country_code


def _get(url: str, *, timeout: float) -> requests.Response:
    try:
        response = requests.get(
            url,
            timeout=timeout,
            headers={"Accept": "application/json, text/plain;q=0.9"},
        )
        response.raise_for_status()
        return response
    except requests.Timeout as exc:
        raise _public_network_error(str(exc)) from exc
    except requests.RequestException as exc:
        raise _public_network_error(str(exc)) from exc


def _json_object(response: requests.Response, provider_name: str) -> dict[str, object]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise _public_network_error(
            f"{provider_name} returned invalid JSON."
        ) from exc
    if not isinstance(payload, dict):
        raise _public_network_error(f"{provider_name} returned a non-object response.")
    return payload


def _fetch_country_is(*, timeout: float) -> PublicNetworkInfo:
    payload = _json_object(_get(COUNTRY_IS_URL, timeout=timeout), "country.is")
    return PublicNetworkInfo(
        ip_address=_validate_ip(payload.get("ip")),
        country_code=_validate_country_code(payload.get("country")),
    )


def _fetch_cloudflare(*, timeout: float) -> PublicNetworkInfo:
    response = _get(CLOUDFLARE_TRACE_URL, timeout=timeout)
    text = response.text
    if not isinstance(text, str) or len(text) > 16_384:
        raise _public_network_error("Cloudflare trace response is invalid or too large.")
    fields: dict[str, str] = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key in fields:
            raise _public_network_error("Cloudflare trace returned duplicate fields.")
        fields[key] = value
    return PublicNetworkInfo(
        ip_address=_validate_ip(fields.get("ip")),
        country_code=_validate_country_code(fields.get("loc")),
    )


def _fetch_ipwhois(*, timeout: float) -> PublicNetworkInfo:
    payload = _json_object(_get(IPWHOIS_URL, timeout=timeout), "ipwho.is")
    if payload.get("success") is False:
        message = payload.get("message")
        details = message.strip() if isinstance(message, str) and message.strip() else "lookup failed"
        raise _public_network_error(f"ipwho.is lookup failed: {details}")
    return PublicNetworkInfo(
        ip_address=_validate_ip(payload.get("ip")),
        country_code=_validate_country_code(payload.get("country_code")),
    )


def _fetch_freeipapi(*, timeout: float) -> PublicNetworkInfo:
    payload = _json_object(_get(FREEIPAPI_URL, timeout=timeout), "FreeIPAPI")
    return PublicNetworkInfo(
        ip_address=_validate_ip(payload.get("ipAddress")),
        country_code=_validate_country_code(payload.get("countryCode")),
    )


def _fetch_geojs(*, timeout: float) -> PublicNetworkInfo:
    payload = _json_object(_get(GEOJS_URL, timeout=timeout), "GeoJS")
    return PublicNetworkInfo(
        ip_address=_validate_ip(payload.get("ip")),
        country_code=_validate_country_code(payload.get("country_code")),
    )


def fetch_public_network_info(
    timeout: float = 10.0,
    *,
    provider_id: str = COUNTRY_IS_PROVIDER,
) -> PublicNetworkInfo:
    """Return the public egress IP and country from one complete provider.

    Stage 3B introduces provider adapters without changing the production
    default yet.  `country.is` remains the default until the later Options and
    Automatic-provider stages are verified on real PIA virtual locations.
    """

    providers = {
        COUNTRY_IS_PROVIDER: _fetch_country_is,
        CLOUDFLARE_PROVIDER: _fetch_cloudflare,
        IPWHOIS_PROVIDER: _fetch_ipwhois,
        FREEIPAPI_PROVIDER: _fetch_freeipapi,
        GEOJS_PROVIDER: _fetch_geojs,
    }
    provider = providers.get(provider_id)
    if provider is None:
        raise _public_network_error(f"Unknown public-network provider: {provider_id}")
    return provider(timeout=timeout)


def fetch_public_ip_amazon(timeout: float = 10.0) -> str:
    """Return only the public egress IP from Amazon's check-IP endpoint.

    This is intentionally separate from the complete providers above.  The
    future Automatic mode will pair it with a local country database instead
    of pretending that Amazon itself provides geolocation data.
    """

    response = _get(AMAZON_CHECK_IP_URL, timeout=timeout)
    text = response.text
    if not isinstance(text, str) or len(text) > 256:
        raise _public_network_error("Amazon check-IP response is invalid or too large.")
    return _validate_ip(text)
