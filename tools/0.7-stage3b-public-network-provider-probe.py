#!/usr/bin/env python3
from __future__ import annotations

from pia_bazzite.public_network import (
    CLOUDFLARE_PROVIDER,
    COUNTRY_IS_PROVIDER,
    FREEIPAPI_PROVIDER,
    GEOJS_PROVIDER,
    IPWHOIS_PROVIDER,
    PublicNetworkError,
    fetch_public_ip_amazon,
    fetch_public_network_info,
)


PROVIDERS = (
    ("country.is (legacy production behavior)", COUNTRY_IS_PROVIDER),
    ("Cloudflare trace", CLOUDFLARE_PROVIDER),
    ("ipwho.is", IPWHOIS_PROVIDER),
    ("FreeIPAPI", FREEIPAPI_PROVIDER),
    ("GeoJS (MaxMind GeoLite)", GEOJS_PROVIDER),
)


def main() -> int:
    print("PIA Bazzite 0.7 Stage 3B - public-network provider probe")
    print("This performs live HTTPS lookups through the CURRENT network/VPN path.")
    print()

    try:
        amazon_ip = fetch_public_ip_amazon(timeout=10.0)
    except PublicNetworkError as exc:
        print(f"Amazon check-IP : ERROR  {exc.details}")
    else:
        print(f"Amazon check-IP : {amazon_ip}  (IP only)")

    for label, provider_id in PROVIDERS:
        try:
            info = fetch_public_network_info(timeout=10.0, provider_id=provider_id)
        except PublicNetworkError as exc:
            print(f"{label:<44}: ERROR  {exc.details}")
        else:
            print(f"{label:<44}: {info.ip_address:<39} {info.country_code}")

    print()
    print("Compare every returned IP with the VPN public IP and note which")
    print("country providers match the PIA server/location you selected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
