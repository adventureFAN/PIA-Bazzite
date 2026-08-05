from __future__ import annotations

import concurrent.futures
import http.client
import json
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import time
from typing import Iterable
from urllib.parse import urlencode

import requests

from .app_errors import AppError
from .credentials import Credentials
from .models import PublicNetworkInfo, Region


SERVER_LIST_URL = "https://serverlist.piaservers.net/vpninfo/servers/v6"
TOKEN_URL = "https://www.privateinternetaccess.com/api/client/v2/token"
PUBLIC_NETWORK_URL = "https://api.country.is/"
WIREGUARD_PORT = 1337


class PiaError(AppError):
    pass


def _resource_path(filename: str) -> Path:
    return Path(__file__).resolve().parent / "resources" / filename


def fetch_regions(timeout: float = 15.0) -> list[Region]:
    try:
        response = requests.get(SERVER_LIST_URL, timeout=timeout)
    except requests.Timeout as exc:
        raise PiaError(
            "error.pia_timeout.title",
            "error.pia_timeout.message",
            details=str(exc),
        ) from exc
    except requests.ConnectionError as exc:
        raise PiaError(
            "error.no_internet.title",
            "error.no_internet.message",
            details=str(exc),
        ) from exc
    except requests.RequestException as exc:
        raise PiaError(
            "error.server_list.title",
            "error.server_list.message",
            details=str(exc),
        ) from exc

    if response.status_code != 200:
        raise PiaError(
            "error.server_list.title",
            "error.server_list_http.message",
            details=f"HTTP {response.status_code}: {response.text[:500]}",
        )

    first_line = response.text.splitlines()[0] if response.text else ""
    if not first_line:
        raise PiaError(
            "error.pia_empty.title",
            "error.pia_empty.message",
        )

    try:
        payload = json.loads(first_line)
    except json.JSONDecodeError as exc:
        raise PiaError(
            "error.pia_format.title",
            "error.pia_format.message",
            details=str(exc),
        ) from exc

    regions: list[Region] = []
    malformed_entries = 0
    for item in payload.get("regions", []):
        try:
            meta = item["servers"]["meta"][0]
            wireguard = item["servers"]["wg"][0]
            regions.append(
                Region(
                    region_id=str(item["id"]),
                    name=str(item["name"]),
                    meta_ip=str(meta["ip"]),
                    wireguard_ip=str(wireguard["ip"]),
                    wireguard_hostname=str(wireguard["cn"]),
                    geo=bool(item.get("geo", False)),
                )
            )
        except (KeyError, IndexError, TypeError):
            malformed_entries += 1

    if not regions:
        raise PiaError(
            "error.no_regions.title",
            "error.no_regions.message",
            details=f"Malformed entries: {malformed_entries}",
        )
    return regions


def _measure_tcp_latency(region: Region, timeout: float) -> Region:
    started = time.perf_counter()
    try:
        with socket.create_connection((region.meta_ip, 443), timeout=timeout):
            elapsed_ms = (time.perf_counter() - started) * 1000
            return region.with_ping(elapsed_ms)
    except OSError:
        return region.with_ping(None)


def measure_latencies(
    regions: Iterable[Region],
    *,
    timeout: float = 1.2,
    max_workers: int = 24,
) -> list[Region]:
    region_list = list(regions)
    if not region_list:
        return []

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        measured = list(
            executor.map(
                lambda region: _measure_tcp_latency(region, timeout),
                region_list,
            )
        )

    measured.sort(
        key=lambda region: (
            region.ping_ms is None,
            region.ping_ms if region.ping_ms is not None else float("inf"),
            region.name.casefold(),
        )
    )
    return measured


def authenticate(credentials: Credentials, timeout: float = 20.0) -> str:
    try:
        response = requests.post(
            TOKEN_URL,
            files={
                "username": (None, credentials.username),
                "password": (None, credentials.password),
            },
            timeout=timeout,
        )
    except requests.Timeout as exc:
        raise PiaError(
            "error.auth_timeout.title",
            "error.auth_timeout.message",
            details=str(exc),
        ) from exc
    except requests.ConnectionError as exc:
        raise PiaError(
            "error.auth_unreachable.title",
            "error.auth_unreachable.message",
            details=str(exc),
        ) from exc
    except requests.RequestException as exc:
        raise PiaError(
            "error.auth_failed.title",
            "error.auth_failed.message",
            details=str(exc),
        ) from exc

    if response.status_code == 401:
        raise PiaError(
            "error.credentials_rejected.title",
            "error.credentials_rejected.message",
        )
    if response.status_code != 200:
        raise PiaError(
            "error.auth_token.title",
            "error.auth_token.message",
            details=f"HTTP {response.status_code}: {response.text[:500]}",
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise PiaError(
            "error.pia_format.title",
            "error.pia_format.message",
            details=str(exc),
        ) from exc

    token = str(payload.get("token", "")).strip()
    if not token:
        raise PiaError(
            "error.no_token.title",
            "error.no_token.message",
            details=json.dumps(payload, ensure_ascii=False)[:1000],
        )
    return token


def _generate_wireguard_keys() -> tuple[str, str]:
    wg_path = shutil.which("wg")
    if not wg_path:
        raise PiaError(
            "error.wg_missing.title",
            "error.wg_missing.message",
        )

    try:
        private_result = subprocess.run(
            [wg_path, "genkey"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PiaError(
            "error.wg_private.title",
            "error.wg_private.message",
            details=str(exc),
        ) from exc

    private_key = private_result.stdout.strip()
    if private_result.returncode != 0 or not private_key:
        raise PiaError(
            "error.wg_private.title",
            "error.wg_private.message",
            details=(private_result.stderr or private_result.stdout).strip(),
        )

    try:
        public_result = subprocess.run(
            [wg_path, "pubkey"],
            input=private_key + "\n",
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PiaError(
            "error.wg_public.title",
            "error.wg_public.message",
            details=str(exc),
        ) from exc

    public_key = public_result.stdout.strip()
    if public_result.returncode != 0 or not public_key:
        raise PiaError(
            "error.wg_public.title",
            "error.wg_public.message",
            details=(public_result.stderr or public_result.stdout).strip(),
        )
    return private_key, public_key


def _request_wireguard_data(
    *,
    hostname: str,
    server_ip: str,
    token: str,
    public_key: str,
    timeout: float = 20.0,
) -> dict[str, object]:
    ca_path = _resource_path("pia-ca.rsa.4096.crt")
    if not ca_path.is_file():
        raise PiaError(
            "error.ca_missing.title",
            "error.ca_missing.message",
            details=str(ca_path),
        )

    query = urlencode({"pt": token, "pubkey": public_key})
    try:
        context = ssl.create_default_context(cafile=str(ca_path))
        if (
            hasattr(ssl, "VERIFY_X509_STRICT")
            and context.verify_flags & ssl.VERIFY_X509_STRICT
        ):
            context.verify_flags &= ~ssl.VERIFY_X509_STRICT

        with socket.create_connection(
            (server_ip, WIREGUARD_PORT),
            timeout=timeout,
        ) as raw_socket:
            with context.wrap_socket(
                raw_socket,
                server_hostname=hostname,
            ) as tls_socket:
                request = (
                    f"GET /addKey?{query} HTTP/1.1\r\n"
                    f"Host: {hostname}:{WIREGUARD_PORT}\r\n"
                    "Accept: application/json\r\n"
                    "User-Agent: PIA-Bazzite/0.4\r\n"
                    "Connection: close\r\n\r\n"
                )
                tls_socket.sendall(request.encode("ascii"))
                response = http.client.HTTPResponse(tls_socket)
                response.begin()
                body = response.read()
    except ssl.SSLCertVerificationError as exc:
        raise PiaError(
            "error.ca_invalid.title",
            "error.ca_invalid.message",
            details=str(exc),
        ) from exc
    except (TimeoutError, socket.timeout) as exc:
        raise PiaError(
            "error.wg_server_timeout.title",
            "error.wg_server_timeout.message",
            details=str(exc),
        ) from exc
    except OSError as exc:
        raise PiaError(
            "error.wg_server_unreachable.title",
            "error.wg_server_unreachable.message",
            details=str(exc),
        ) from exc

    if response.status != 200:
        raise PiaError(
            "error.wg_registration.title",
            "error.wg_registration.message",
            details=f"HTTP {response.status}: {body[:500]!r}",
        )

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PiaError(
            "error.pia_format.title",
            "error.pia_format.message",
            details=str(exc),
        ) from exc

    if payload.get("status") != "OK":
        raise PiaError(
            "error.wg_rejected.title",
            "error.wg_rejected.message",
            details=str(payload.get("message", "Unknown PIA error")),
        )

    required_fields = ("peer_ip", "server_key", "server_port", "dns_servers")
    missing = [field for field in required_fields if not payload.get(field)]
    if missing:
        raise PiaError(
            "error.wg_incomplete.title",
            "error.wg_incomplete.message",
            details="Missing fields: " + ", ".join(missing),
        )
    return payload


def create_wireguard_config(
    *,
    config_path: Path,
    credentials: Credentials,
    region: Region,
) -> None:
    token = authenticate(credentials)
    private_key, public_key = _generate_wireguard_keys()
    payload = _request_wireguard_data(
        hostname=region.wireguard_hostname,
        server_ip=region.wireguard_ip,
        token=token,
        public_key=public_key,
    )

    dns_servers = payload["dns_servers"]
    if not isinstance(dns_servers, list) or not dns_servers:
        raise PiaError(
            "error.dns_missing.title",
            "error.dns_missing.message",
        )

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config = (
        "[Interface]\n"
        f"Address = {payload['peer_ip']}\n"
        f"PrivateKey = {private_key}\n"
        f"DNS = {dns_servers[0]}\n\n"
        "[Peer]\n"
        "PersistentKeepalive = 25\n"
        f"PublicKey = {payload['server_key']}\n"
        "AllowedIPs = 0.0.0.0/0\n"
        f"Endpoint = {region.wireguard_ip}:{payload['server_port']}\n"
    )

    try:
        config_path.write_text(config, encoding="utf-8")
        config_path.chmod(0o600)
    except OSError as exc:
        raise PiaError(
            "error.config_write.title",
            "error.config_write.message",
            details=str(exc),
        ) from exc


def fetch_public_network_info(timeout: float = 10.0) -> PublicNetworkInfo:
    try:
        response = requests.get(PUBLIC_NETWORK_URL, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
    except requests.Timeout as exc:
        raise PiaError(
            "error.public_ip.title",
            "error.public_ip.message",
            details=str(exc),
        ) from exc
    except (requests.RequestException, ValueError) as exc:
        raise PiaError(
            "error.public_ip.title",
            "error.public_ip.message",
            details=str(exc),
        ) from exc

    ip_address = str(payload.get("ip", "")).strip()
    country_code = str(payload.get("country", "")).strip().upper()
    if not ip_address:
        raise PiaError(
            "error.public_ip.title",
            "error.public_ip.message",
            details=json.dumps(payload, ensure_ascii=False)[:500],
        )
    return PublicNetworkInfo(ip_address=ip_address, country_code=country_code)
