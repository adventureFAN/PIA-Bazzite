from __future__ import annotations

import base64
import binascii
import concurrent.futures
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import ssl
import stat
import subprocess
import time
from typing import Iterable, TYPE_CHECKING
from urllib.parse import urlencode

import requests

from . import __version__
from .app_errors import AppError
from .models import Region
from .public_network import fetch_public_network_info

if TYPE_CHECKING:
    from .credentials import Credentials


SERVER_LIST_URL = "https://serverlist.piaservers.net/vpninfo/servers/v6"
TOKEN_URL = "https://www.privateinternetaccess.com/api/client/v2/token"
WIREGUARD_PORT = 1337


class PiaError(AppError):
    pass


def _pia_validation_error(details: str) -> PiaError:
    return PiaError(
        "error.pia_format.title",
        "error.pia_format.message",
        details=details,
    )


def _reject_control_text(value: object, field: str, *, max_length: int = 512) -> str:
    if not isinstance(value, str):
        raise _pia_validation_error(f"{field} is not text.")
    text = value.strip()
    if not text or len(text) > max_length:
        raise _pia_validation_error(f"{field} is empty or too long.")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in text):
        raise _pia_validation_error(f"{field} contains control characters.")
    return text


def _validate_ip(value: object, field: str) -> str:
    text = _reject_control_text(value, field, max_length=64)
    try:
        address = ipaddress.ip_address(text)
    except ValueError as exc:
        raise _pia_validation_error(f"{field} is not a numeric IP address.") from exc
    if address.is_unspecified or address.is_loopback or address.is_multicast:
        raise _pia_validation_error(f"{field} is not an allowed IP address.")
    return address.compressed


def _validate_interface_address(value: object, field: str) -> str:
    text = _reject_control_text(value, field, max_length=96)
    try:
        interface = ipaddress.ip_interface(text)
    except ValueError as exc:
        raise _pia_validation_error(f"{field} is not a valid interface address.") from exc
    if interface.ip.is_unspecified or interface.ip.is_loopback or interface.ip.is_multicast:
        raise _pia_validation_error(f"{field} is not an allowed interface address.")
    return str(interface)


def _validate_hostname(value: object, field: str) -> str:
    text = _reject_control_text(value, field, max_length=253).lower().rstrip(".")
    labels = text.split(".")
    # PIA's server-list `cn` values are certificate names and may be either
    # fully-qualified DNS names or a single RFC-style hostname label such as
    # "helsinki403".  Both forms are valid TLS server names for the pinned
    # PIA CA; control characters and invalid label syntax remain rejected.
    if any(
        not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
        for label in labels
    ):
        raise _pia_validation_error(f"{field} is not a valid DNS hostname.")
    return text


def _validate_port(value: object, field: str) -> int:
    if isinstance(value, bool):
        raise _pia_validation_error(f"{field} is not a valid port.")
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise _pia_validation_error(f"{field} is not a valid port.") from exc
    if str(port) != str(value).strip() and not isinstance(value, int):
        raise _pia_validation_error(f"{field} is not a canonical port value.")
    if port < 1 or port > 65535:
        raise _pia_validation_error(f"{field} is outside the valid port range.")
    return port


def _validate_wireguard_key(value: object, field: str) -> str:
    text = _reject_control_text(value, field, max_length=64)
    try:
        decoded = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise _pia_validation_error(f"{field} is not valid base64.") from exc
    if len(decoded) != 32:
        raise _pia_validation_error(f"{field} is not a 32-byte WireGuard key.")
    return text


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

    if not isinstance(payload, dict) or not isinstance(payload.get("regions"), list):
        raise _pia_validation_error("PIA server-list payload has no regions array.")

    regions: list[Region] = []
    malformed_entries = 0
    for item in payload["regions"]:
        try:
            if not isinstance(item, dict) or not isinstance(item.get("servers"), dict):
                raise ValueError("invalid region entry")
            meta = item["servers"]["meta"][0]
            wireguard = item["servers"]["wg"][0]
            if not isinstance(meta, dict) or not isinstance(wireguard, dict):
                raise ValueError("invalid server entry")
            geo_value = item.get("geo", False)
            if not isinstance(geo_value, bool):
                raise ValueError("invalid geo flag")
            region_id = _reject_control_text(item.get("id"), "region id", max_length=128)
            name = _reject_control_text(item.get("name"), "region name", max_length=256)
            regions.append(
                Region(
                    region_id=region_id,
                    name=name,
                    meta_ip=_validate_ip(meta.get("ip"), "metadata server IP"),
                    wireguard_ip=_validate_ip(wireguard.get("ip"), "WireGuard server IP"),
                    wireguard_hostname=_validate_hostname(wireguard.get("cn"), "WireGuard certificate hostname"),
                    geo=geo_value,
                )
            )
        except (KeyError, IndexError, TypeError, ValueError, PiaError):
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


def authenticate(credentials: "Credentials", timeout: float = 20.0) -> str:
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

    try:
        token = _reject_control_text(payload.get("token"), "PIA token", max_length=4096)
        token.encode("ascii")
    except (PiaError, UnicodeEncodeError) as exc:
        raise PiaError(
            "error.no_token.title",
            "error.no_token.message",
            details="PIA returned an empty or invalid token.",
        ) from exc
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
    try:
        private_key = _validate_wireguard_key(private_key, "generated WireGuard private key")
        public_key = _validate_wireguard_key(public_key, "generated WireGuard public key")
    except PiaError as exc:
        raise PiaError(
            "error.wg_public.title",
            "error.wg_public.message",
            details=exc.details,
        ) from exc
    return private_key, public_key


def _request_wireguard_data(
    *,
    hostname: str,
    server_ip: str,
    token: str,
    public_key: str,
    timeout: float = 20.0,
) -> dict[str, object]:
    hostname = _validate_hostname(hostname, "WireGuard certificate hostname")
    server_ip = _validate_ip(server_ip, "WireGuard server IP")
    token = _reject_control_text(token, "PIA token", max_length=4096)
    try:
        token.encode("ascii")
    except UnicodeEncodeError as exc:
        raise _pia_validation_error("PIA token contains non-ASCII characters.") from exc
    public_key = _validate_wireguard_key(public_key, "WireGuard public key")

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
                    f"User-Agent: PIA-Bazzite/{__version__}\r\n"
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

    if not isinstance(payload, dict):
        raise _pia_validation_error("PIA WireGuard registration response is not an object.")
    if payload.get("status") != "OK":
        message = payload.get("message", "Unknown PIA error")
        raise PiaError(
            "error.wg_rejected.title",
            "error.wg_rejected.message",
            details=str(message)[:500],
        )

    required_fields = ("peer_ip", "server_key", "server_port", "dns_servers")
    missing = [field for field in required_fields if field not in payload or payload[field] in (None, "", [])]
    if missing:
        raise PiaError(
            "error.wg_incomplete.title",
            "error.wg_incomplete.message",
            details="Missing fields: " + ", ".join(missing),
        )
    dns_servers = payload["dns_servers"]
    if not isinstance(dns_servers, list) or not 1 <= len(dns_servers) <= 8:
        raise _pia_validation_error("PIA DNS server list is invalid.")
    return {
        **payload,
        "peer_ip": _validate_interface_address(payload["peer_ip"], "WireGuard peer IP"),
        "server_key": _validate_wireguard_key(payload["server_key"], "WireGuard server key"),
        "server_port": _validate_port(payload["server_port"], "WireGuard server port"),
        "dns_servers": [_validate_ip(value, "PIA DNS server") for value in dns_servers],
    }


def create_wireguard_config(
    *,
    config_path: Path,
    credentials: "Credentials",
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

    endpoint_ip = _validate_ip(region.wireguard_ip, "WireGuard endpoint IP")
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
        f"Endpoint = {endpoint_ip}:{payload['server_port']}\n"
    )

    temporary = config_path.with_name(
        f".{config_path.name}.{os.getpid()}.{secrets.token_hex(6)}.tmp"
    )
    try:
        if config_path.exists() or config_path.is_symlink():
            metadata = config_path.lstat()
            if config_path.is_symlink() or not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise OSError(f"Refusing unsafe WireGuard config target: {config_path}")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(temporary, flags, 0o600)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8", closefd=False) as handle:
                handle.write(config)
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            os.close(fd)
        os.replace(temporary, config_path)
        config_path.chmod(0o600)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise PiaError(
            "error.config_write.title",
            "error.config_write.message",
            details=str(exc),
        ) from exc
