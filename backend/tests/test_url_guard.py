# =============================================================================
# Copyright (c) 2026 ZombieTech LLC. All rights reserved.
#
# SPDX-License-Identifier: PolyForm-Strict-1.0.0
# See LICENSE in the project root for the full terms.
#
# Licensing inquiries: license@zombietech.biz
# =============================================================================
# ai: claude-opus-5-5 | 2026-11-13
"""SSRF guard tests: address classification, the scraper's per-hop hook, and the
capture routes' 400 response. DNS is stubbed so nothing touches the network."""
import socket
from unittest.mock import patch

import httpx
import pytest

from app.services import scraper
from app.services.url_guard import UnsafeURLError, check_public_destination

_PUBLIC_IP = "93.184.216.34"
_real_getaddrinfo = socket.getaddrinfo


def _fake_dns(mapping: dict[str, list[str]]):
    """getaddrinfo stand-in: names in mapping resolve to the given IPs; IP
    literals fall through to the real resolver (no network needed for those)."""
    def getaddrinfo(host, port, *args, **kwargs):
        if host in mapping:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in mapping[host]]
        return _real_getaddrinfo(host, port, *args, **kwargs)
    return patch("app.services.url_guard.socket.getaddrinfo", side_effect=getaddrinfo)


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/",
    "http://localhost:2019/config/",
    "http://10.0.0.5/",
    "http://192.168.1.10:9000/bucket",
    "http://169.254.169.254/latest/meta-data/",
    "http://[::1]/",
    "http://[::ffff:127.0.0.1]/",
    "http://0.0.0.0/",
])
def test_internal_destinations_are_rejected(url):
    with _fake_dns({"localhost": ["127.0.0.1"]}), pytest.raises(UnsafeURLError):
        check_public_destination(url)


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com/x", "gopher://x"])
def test_non_http_schemes_are_rejected(url):
    with pytest.raises(UnsafeURLError):
        check_public_destination(url)


def test_public_destination_is_allowed():
    with _fake_dns({"recipes.example": [_PUBLIC_IP]}):
        check_public_destination("https://recipes.example/soup")


def test_host_with_any_internal_address_is_rejected():
    with _fake_dns({"mixed.example": [_PUBLIC_IP, "10.1.2.3"]}), pytest.raises(UnsafeURLError):
        check_public_destination("https://mixed.example/")


def test_unresolvable_host_is_rejected():
    with patch("app.services.url_guard.socket.getaddrinfo", side_effect=socket.gaierror), \
            pytest.raises(UnsafeURLError):
        check_public_destination("https://nope.invalid/")


def test_scraper_rejects_redirect_to_internal_address():
    """The guard must run on each redirect hop, not just the first URL."""
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(302, headers={"Location": "http://127.0.0.1:2019/config/"})

    real_client = httpx.Client

    def client_with_mock_transport(**kwargs):
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    with _fake_dns({"public.example": [_PUBLIC_IP]}), \
            patch("app.services.scraper.httpx.Client", side_effect=client_with_mock_transport), \
            pytest.raises(UnsafeURLError):
        scraper.fetch_page_image("http://public.example/image.jpg")

    assert requested == ["http://public.example/image.jpg"]


@pytest.mark.parametrize("path,body", [
    ("/capture/url", {"url": "http://127.0.0.1:2019/config/"}),
    ("/capture/scan", {"url": "http://127.0.0.1:2019/config/"}),
])
def test_capture_routes_return_400_for_internal_urls(client, path, body):
    res = client.post(path, json=body)
    assert res.status_code == 400
    assert "not allowed" in res.json()["detail"]
