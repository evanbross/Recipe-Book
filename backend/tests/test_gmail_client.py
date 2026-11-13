# =============================================================================
# Copyright (c) 2026 ZombieTech LLC. All rights reserved.
#
# SPDX-License-Identifier: PolyForm-Strict-1.0.0
# See LICENSE in the project root for the full terms.
#
# Licensing inquiries: license@zombietech.biz
# =============================================================================

# ai: claude-opus-5-5 | 2026-11-13
"""Tests for Gmail message parsing and the no-interactive-auth rule.

Message dicts mirror the Gmail API's users.messages.get(format="full") shape;
no Google API calls are made."""
import base64
from unittest.mock import patch

import pytest

from app.services.gmail_client import GmailClient, NotAuthenticatedError


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def _part(mime: str, text: str) -> dict:
    return {"mimeType": mime, "body": {"data": _b64(text)}}


def _message(payload: dict, subject: str = "Soup!", sender: str = "News <hi@a.com>") -> dict:
    payload = {**payload, "headers": [{"name": "Subject", "value": subject},
                                      {"name": "FROM", "value": sender}]}
    return {"payload": payload}


def test_extract_text_reads_headers_case_insensitively():
    subject, sender, body = GmailClient.extract_text(_message(_part("text/plain", "hello")))
    assert (subject, sender, body) == ("Soup!", "News <hi@a.com>", "hello")


def test_extract_text_prefers_richer_html_alternative():
    html = "<p>Ingredients</p><p>2 cups water</p><p>Boil it for ten minutes</p>"
    payload = {"mimeType": "multipart/alternative",
               "parts": [_part("text/plain", "See HTML"), _part("text/html", html)]}
    body = GmailClient.extract_text(_message(payload))[2]
    assert "2 cups water" in body
    assert "<p>" not in body


def test_extract_text_walks_nested_multiparts():
    inner = {"mimeType": "multipart/alternative", "parts": [_part("text/plain", "nested body")]}
    payload = {"mimeType": "multipart/mixed",
               "parts": [inner, {"mimeType": "image/png", "body": {}}]}
    assert GmailClient.extract_text(_message(payload))[2] == "nested body"


def test_html_text_skips_scripts_and_keeps_link_targets():
    html = ('<style>p{}</style><script>evil()</script>'
            '<p>Read it: <a href="https://a.com/recipes/soup">Get recipe</a></p>')
    body = GmailClient.extract_text(_message(_part("text/html", html)))[2]
    assert "evil" not in body and "p{}" not in body
    assert "Get recipe: https://a.com/recipes/soup" in body


def test_invalid_base64_yields_empty_body():
    payload = {"mimeType": "text/plain", "body": {"data": "a"}}  # 1 data char: undecodable
    assert GmailClient.extract_text(_message(payload))[2] == ""


def test_extract_html_finds_nested_html_part():
    html = "<p>hi</p>"
    payload = {"mimeType": "multipart/mixed",
               "parts": [{"mimeType": "multipart/alternative",
                          "parts": [_part("text/plain", "hi"), _part("text/html", html)]}]}
    assert GmailClient.extract_html(_message(payload)) == html


def test_extract_html_returns_empty_when_absent():
    assert GmailClient.extract_html(_message(_part("text/plain", "hi"))) == ""


def test_resolve_labels_includes_sublabels_once():
    labels = [
        {"name": "Cooking", "id": "L1"},
        {"name": "Cooking/Italian", "id": "L2"},
        {"name": "Cookbooks", "id": "L3"},   # shares a prefix but is not a sublabel
        {"name": "Baking", "id": "L4"},
    ]
    with patch.object(GmailClient, "_build_service"), \
            patch.object(GmailClient, "list_all_labels", return_value=labels):
        resolved = GmailClient().resolve_labels_with_sublabels(["Cooking", "Cooking/Italian", "Baking"])
    assert resolved == [("Cooking", "L1"), ("Cooking/Italian", "L2"), ("Baking", "L4")]


def test_missing_token_raises_instead_of_starting_oauth(tmp_path):
    with patch("app.services.gmail_client.GOOGLE_TOKEN_FILE", tmp_path / "missing.json"), \
            patch("app.services.gmail_client.build") as build, \
            pytest.raises(NotAuthenticatedError):
        GmailClient()
    build.assert_not_called()
