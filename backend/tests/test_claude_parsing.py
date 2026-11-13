# =============================================================================
# Copyright (c) 2026 ZombieTech LLC. All rights reserved.
#
# SPDX-License-Identifier: PolyForm-Strict-1.0.0
# See LICENSE in the project root for the full terms.
#
# Licensing inquiries: license@zombietech.biz
# =============================================================================
# ai: claude-opus-5-5 | 2026-11-13
"""Tests for Claude-reply parsing: the shared JSON helper and the email/page
recipe parser. The Anthropic client is replaced by a stub returning canned text,
so these exercise our parsing rules, not the API."""
import json
from types import SimpleNamespace
from unittest.mock import patch

import anthropic
import httpx
import pytest

from app.services.claude_json import parse_json_reply
from app.services.recipe_email_parser import parse_recipe_from_email, parse_recipe_from_page

_CLIENT = "app.services.recipe_email_parser._client"


def _reply(text: str) -> SimpleNamespace:
    """Shape of anthropic's Message that the parser reads: .content[0].text."""
    return SimpleNamespace(content=[SimpleNamespace(text=text)])


def _recipe_json(**overrides) -> str:
    data = {
        "has_recipe": True,
        "title": "Pancakes",
        "ingredients": "flour\neggs",
        "instructions": "mix\ncook",
    }
    data.update(overrides)
    return json.dumps(data)


# ── parse_json_reply ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("wrapped", [
    '{"a": 1}',
    '```json\n{"a": 1}\n```',
    '```\n{"a": 1}\n```',
    '  \n{"a": 1}\n  ',
])
def test_parse_json_reply_strips_optional_fences(wrapped):
    assert parse_json_reply(wrapped) == {"a": 1}


def test_parse_json_reply_raises_on_non_json():
    with pytest.raises(json.JSONDecodeError):
        parse_json_reply("Sorry, I can't help with that.")


# ── parse_recipe_from_email ───────────────────────────────────────────────────

def test_email_with_recipe_returns_capture_result():
    with patch(_CLIENT) as client:
        client.messages.create.return_value = _reply(_recipe_json())
        result = parse_recipe_from_email("Weekend brunch", "a@b.com", "body")

    assert result is not None
    assert result.title == "Pancakes"
    assert result.ingredients == "flour\neggs"
    sent = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "Subject: Weekend brunch" in sent


def test_email_without_recipe_returns_none():
    with patch(_CLIENT) as client:
        client.messages.create.return_value = _reply('{"has_recipe": false}')
        assert parse_recipe_from_email("Sale!", "a@b.com", "body") is None


def test_email_missing_title_falls_back_to_subject():
    with patch(_CLIENT) as client:
        client.messages.create.return_value = _reply(_recipe_json(title=None))
        result = parse_recipe_from_email("Grandma's stew", "a@b.com", "body")
    assert result.title == "Grandma's stew"


def test_email_missing_title_and_subject_uses_generic_title():
    with patch(_CLIENT) as client:
        client.messages.create.return_value = _reply(_recipe_json(title=""))
        result = parse_recipe_from_email("", "a@b.com", "body")
    assert result.title == "Recipe from Email"


@pytest.mark.parametrize("reply", ["not json at all", "[1, 2, 3]", '"just a string"'])
def test_email_malformed_reply_returns_none(reply):
    with patch(_CLIENT) as client:
        client.messages.create.return_value = _reply(reply)
        assert parse_recipe_from_email("s", "a@b.com", "body") is None


def test_email_reply_failing_schema_validation_returns_none():
    with patch(_CLIENT) as client:
        client.messages.create.return_value = _reply(_recipe_json(servings={"n": 4}))
        assert parse_recipe_from_email("s", "a@b.com", "body") is None


def test_email_body_is_truncated_before_sending():
    with patch(_CLIENT) as client:
        client.messages.create.return_value = _reply('{"has_recipe": false}')
        parse_recipe_from_email("s", "a@b.com", "~" * 50_000)
    sent = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert sent.count("~") == 15_000


def test_email_api_error_propagates():
    error = anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com"))
    with patch(_CLIENT) as client:
        client.messages.create.side_effect = error
        with pytest.raises(anthropic.APIConnectionError):
            parse_recipe_from_email("s", "a@b.com", "body")


# ── parse_recipe_from_page ────────────────────────────────────────────────────

def test_page_missing_title_falls_back_to_url_slug():
    with patch(_CLIENT) as client:
        client.messages.create.return_value = _reply(_recipe_json(title=None))
        result = parse_recipe_from_page("https://a.com/recipes/spicy_tofu-bowl/", "text")
    assert result.title == "Spicy Tofu Bowl"


def test_page_sends_source_url_and_returns_recipe():
    with patch(_CLIENT) as client:
        client.messages.create.return_value = _reply("```json\n" + _recipe_json() + "\n```")
        result = parse_recipe_from_page("https://a.com/r/1", "page text")
    assert result.title == "Pancakes"
    sent = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "Source URL: https://a.com/r/1" in sent


def test_page_without_recipe_returns_none():
    with patch(_CLIENT) as client:
        client.messages.create.return_value = _reply('{"has_recipe": false}')
        assert parse_recipe_from_page("https://a.com/x", "text") is None
