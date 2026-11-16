# =============================================================================
# Copyright (c) 2026 ZombieTech LLC. All rights reserved.
#
# SPDX-License-Identifier: PolyForm-Strict-1.0.0
# See LICENSE in the project root for the full terms.
#
# Licensing inquiries: license@zombietech.biz
# =============================================================================

# ai: claude-opus-5-5 | 2026-11-13
"""Tests for the Tampermonkey capture listener over a real localhost socket."""
from http import HTTPStatus

import httpx
import pytest

from app.services.capture_listener import CaptureListener


@pytest.fixture(scope="module")
def http():
    # Shared across the module: constructing an httpx client (SSL context) takes
    # ~1 s on Windows, which per-test clients turned into most of the runtime.
    with httpx.Client(trust_env=False) as client:
        yield client


@pytest.fixture(scope="module")
def _server():
    # Module-scoped too: each stop() waits out serve_forever's 0.5 s poll interval.
    received: list[dict] = []

    def submit(body: dict) -> tuple[dict, int]:
        received.append(body)
        return {"status": "queued"}, HTTPStatus.ACCEPTED

    server = CaptureListener(host="127.0.0.1", port=0, max_bytes=4096, submit_capture=submit)
    server.start()
    try:
        yield f"http://127.0.0.1:{server.port}", received
    finally:
        server.stop()


@pytest.fixture()
def listener(_server):
    """(base_url, submitted_bodies) with the submission log reset for this test."""
    base, received = _server
    received.clear()
    return base, received


def test_health(http, listener):
    base, _ = listener
    assert http.get(f"{base}/health").json() == {"status": "ok"}


def test_json_capture_is_submitted(http, listener):
    base, received = listener
    res = http.post(f"{base}/capture/url",
                     json={"url": " https://a.com/r ", "tag_ids": [1, "x", 2]})
    assert res.status_code == HTTPStatus.ACCEPTED
    assert received == [{"url": "https://a.com/r", "tag_ids": [1, 2], "html": None}]


# ai: claude-opus-5-5 | 2026-11-15
def test_page_html_is_passed_through(http, listener):
    base, received = listener
    res = http.post(f"{base}/capture/url", json={"url": "https://a.com/r", "html": "<h1>Soup</h1>"})
    assert res.status_code == HTTPStatus.ACCEPTED
    assert received == [{"url": "https://a.com/r", "tag_ids": [], "html": "<h1>Soup</h1>"}]


def test_json_with_charset_is_accepted(http, listener):
    base, received = listener
    res = http.post(f"{base}/capture/url", content=b'{"url": "https://a.com/r"}',
                     headers={"Content-Type": "application/json; charset=utf-8"})
    assert res.status_code == HTTPStatus.ACCEPTED
    assert len(received) == 1


@pytest.mark.parametrize("content_type", [
    "text/plain",                         # what a cross-site no-cors fetch sends
    "application/x-www-form-urlencoded",  # what a cross-site HTML form sends
    None,
])
def test_non_json_content_type_is_rejected_without_submitting(http, listener, content_type):
    base, received = listener
    headers = {"Content-Type": content_type} if content_type else {}
    res = http.post(f"{base}/capture/url", content=b'{"url": "https://a.com/r"}', headers=headers)
    assert res.status_code == HTTPStatus.UNSUPPORTED_MEDIA_TYPE
    assert received == []


@pytest.mark.parametrize("body,expected", [
    (b"not json", HTTPStatus.BAD_REQUEST),
    (b"[1, 2]", HTTPStatus.BAD_REQUEST),
    (b'{"tag_ids": [1]}', HTTPStatus.BAD_REQUEST),
    (b'{"url": "' + b"a" * 5000 + b'"}', HTTPStatus.REQUEST_ENTITY_TOO_LARGE),
    (b'{"url": "https://a.com/r", "html": 42}', HTTPStatus.BAD_REQUEST),
    (b'{"url": "file:///etc/passwd", "html": "<p>x</p>"}', HTTPStatus.BAD_REQUEST),
])
def test_bad_bodies_are_rejected(http, listener, body, expected):
    base, received = listener
    res = http.post(f"{base}/capture/url", content=body,
                     headers={"Content-Type": "application/json"})
    assert res.status_code == expected
    assert received == []


def test_unknown_path_is_404(http, listener):
    base, _ = listener
    res = http.post(f"{base}/admin", json={"url": "https://a.com"})
    assert res.status_code == HTTPStatus.NOT_FOUND
