from __future__ import annotations

import unittest
from unittest import mock

import requests

from pia_bazzite.models import PublicNetworkInfo
from pia_bazzite import public_network


class FakeResponse:
    def __init__(self, *, payload=None, text: str = "", status_error: Exception | None = None):
        self._payload = payload
        self.text = text
        self._status_error = status_error

    def raise_for_status(self) -> None:
        if self._status_error is not None:
            raise self._status_error

    def json(self):
        if isinstance(self._payload, BaseException):
            raise self._payload
        return self._payload


class PublicNetworkProviderTests(unittest.TestCase):
    def _fetch_with(self, provider: str, response: FakeResponse) -> PublicNetworkInfo:
        with mock.patch.object(public_network.requests, "get", return_value=response) as get:
            result = public_network.fetch_public_network_info(provider_id=provider, timeout=4.5)
        get.assert_called_once()
        self.assertEqual(get.call_args.kwargs["timeout"], 4.5)
        return result

    def test_country_is_adapter_preserves_current_production_shape(self) -> None:
        result = self._fetch_with(
            public_network.COUNTRY_IS_PROVIDER,
            FakeResponse(payload={"ip": "194.33.46.16", "country": "nl"}),
        )
        self.assertEqual(result, PublicNetworkInfo("194.33.46.16", "NL"))

    def test_cloudflare_trace_adapter_reads_ip_and_loc(self) -> None:
        result = self._fetch_with(
            public_network.CLOUDFLARE_PROVIDER,
            FakeResponse(text="fl=123\nip=194.33.46.16\nloc=MT\ncolo=FCO\n"),
        )
        self.assertEqual(result, PublicNetworkInfo("194.33.46.16", "MT"))

    def test_ipwhois_adapter_reads_ip_and_country(self) -> None:
        result = self._fetch_with(
            public_network.IPWHOIS_PROVIDER,
            FakeResponse(
                payload={
                    "success": True,
                    "ip": "194.33.46.16",
                    "country_code": "MT",
                }
            ),
        )
        self.assertEqual(result, PublicNetworkInfo("194.33.46.16", "MT"))

    def test_freeipapi_adapter_reads_ip_and_country(self) -> None:
        result = self._fetch_with(
            public_network.FREEIPAPI_PROVIDER,
            FakeResponse(payload={"ipAddress": "194.33.46.16", "countryCode": "MT"}),
        )
        self.assertEqual(result, PublicNetworkInfo("194.33.46.16", "MT"))

    def test_geojs_adapter_reads_ip_and_country(self) -> None:
        result = self._fetch_with(
            public_network.GEOJS_PROVIDER,
            FakeResponse(payload={"ip": "194.33.46.16", "country_code": "MT"}),
        )
        self.assertEqual(result, PublicNetworkInfo("194.33.46.16", "MT"))

    def test_amazon_is_ip_only_and_kept_separate_from_geolocation(self) -> None:
        with mock.patch.object(
            public_network.requests,
            "get",
            return_value=FakeResponse(text="194.33.46.16\n"),
        ):
            self.assertEqual(public_network.fetch_public_ip_amazon(), "194.33.46.16")
        self.assertNotIn("amazon", public_network.PUBLIC_NETWORK_PROVIDER_IDS)

    def test_invalid_country_code_is_rejected(self) -> None:
        with mock.patch.object(
            public_network.requests,
            "get",
            return_value=FakeResponse(payload={"ip": "194.33.46.16", "country": "NLD"}),
        ):
            with self.assertRaises(public_network.PublicNetworkError):
                public_network.fetch_public_network_info()

    def test_invalid_public_ip_is_rejected(self) -> None:
        with mock.patch.object(
            public_network.requests,
            "get",
            return_value=FakeResponse(payload={"ip": "not-an-ip", "country": "MT"}),
        ):
            with self.assertRaises(public_network.PublicNetworkError):
                public_network.fetch_public_network_info()

    def test_cloudflare_duplicate_security_relevant_fields_are_rejected(self) -> None:
        with mock.patch.object(
            public_network.requests,
            "get",
            return_value=FakeResponse(text="ip=194.33.46.16\nip=203.0.113.5\nloc=MT\n"),
        ):
            with self.assertRaises(public_network.PublicNetworkError):
                public_network.fetch_public_network_info(
                    provider_id=public_network.CLOUDFLARE_PROVIDER
                )

    def test_ipwhois_explicit_failure_is_rejected(self) -> None:
        with mock.patch.object(
            public_network.requests,
            "get",
            return_value=FakeResponse(payload={"success": False, "message": "rate limited"}),
        ):
            with self.assertRaises(public_network.PublicNetworkError) as ctx:
                public_network.fetch_public_network_info(
                    provider_id=public_network.IPWHOIS_PROVIDER
                )
        self.assertIn("rate limited", ctx.exception.details)

    def test_http_and_timeout_failures_become_clean_app_errors(self) -> None:
        for error in (requests.Timeout("timeout"), requests.ConnectionError("offline")):
            with self.subTest(error=type(error).__name__), mock.patch.object(
                public_network.requests,
                "get",
                side_effect=error,
            ):
                with self.assertRaises(public_network.PublicNetworkError):
                    public_network.fetch_public_network_info()

    def test_unknown_provider_is_rejected_without_network_access(self) -> None:
        with mock.patch.object(public_network.requests, "get") as get:
            with self.assertRaises(public_network.PublicNetworkError):
                public_network.fetch_public_network_info(provider_id="nope")
        get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
