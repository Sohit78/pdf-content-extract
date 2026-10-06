"""Request authentication and outbound-URL safety checks."""

import ipaddress
import os
import secrets
import socket
from typing import Optional
from urllib.parse import urlparse

from fastapi import Header, HTTPException

ALLOWED_SCHEMES = {"http", "https"}
TRUTHY = {"1", "true", "yes", "on"}


def configured_api_key() -> str:
    return os.getenv("API_KEY", "").strip()


def auth_enabled() -> bool:
    return bool(configured_api_key())


def private_urls_allowed() -> bool:
    return os.getenv("ALLOW_PRIVATE_URLS", "").strip().lower() in TRUTHY


async def require_api_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    expected = configured_api_key()
    if not expected:
        # No key configured: the API stays open, as it was before.
        return
    if not x_api_key or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key header.")


def _is_non_public(ip: ipaddress._BaseAddress) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def assert_safe_url(url: str) -> None:
    """Reject anything that is not a public http(s) endpoint.

    Guards the URL extractor against being used to reach loopback, link-local
    (cloud metadata) or RFC1918 hosts. Set ALLOW_PRIVATE_URLS=true to disable,
    which is what you want when pointing it at a PDF on your own network.
    """
    if private_urls_allowed():
        return

    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise ValueError(f"Unsupported URL scheme '{parsed.scheme}'. Use http or https.")

    host = parsed.hostname
    if not host:
        raise ValueError("URL has no host.")

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        resolved = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise ValueError(f"Could not resolve host '{host}'.") from exc

    for info in resolved:
        ip = ipaddress.ip_address(info[4][0])
        if _is_non_public(ip):
            raise ValueError(f"Refusing to fetch from non-public address {ip} ({host}).")
