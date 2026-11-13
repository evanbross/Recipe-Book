# =============================================================================
# Copyright (c) 2026 ZombieTech LLC. All rights reserved.
#
# SPDX-License-Identifier: PolyForm-Strict-1.0.0
# See LICENSE in the project root for the full terms.
#
# Licensing inquiries: license@zombietech.biz
# =============================================================================
"""SSRF guard for server-side fetches of untrusted URLs.

URLs reach the scraper from user input and from inbound email HTML, so a link
(or a redirect from one) could point the backend at loopback services (Caddy
admin, MinIO, Postgres), the LAN, or a cloud metadata endpoint. Every request,
including each redirect hop, must pass check_public_destination() first.

Leaf module: no project imports.
"""
import ipaddress
import socket
from urllib.parse import urlsplit


class UnsafeURLError(ValueError):
    """The URL's scheme or resolved address is not allowed for outbound fetches."""


# ai: claude-opus-5-5 | 2026-11-13
def _is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%", 1)[0])  # drop IPv6 zone id
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return not (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
        or ip.is_reserved or ip.is_unspecified
    )


# ai: claude-opus-5-5 | 2026-11-13
def check_public_destination(url: str) -> None:
    """Raise UnsafeURLError unless url is http(s) and every address it resolves to is public.

    All resolved addresses are checked, not just the first, because the client
    may connect to any of them. A residual DNS-rebinding window remains between
    this lookup and the client's own; closing it would need IP-pinned connections.
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise UnsafeURLError(f"Scheme not allowed: {parts.scheme!r}")
    host = parts.hostname
    if not host:
        raise UnsafeURLError("URL has no host")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"Cannot resolve host {host!r}") from exc
    for info in infos:
        address = str(info[4][0])
        if not _is_public(address):
            raise UnsafeURLError(f"Destination {host!r} resolves to non-public address {address}")
