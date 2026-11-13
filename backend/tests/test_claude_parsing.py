# =============================================================================
# Copyright (c) 2026 ZombieTech LLC. All rights reserved.
#
# SPDX-License-Identifier: PolyForm-Strict-1.0.0
# See LICENSE in the project root for the full terms.
#
# Licensing inquiries: license@zombietech.biz
# =============================================================================

# ai: claude-opus-5-5 | 2026-11-13
"""Tests for the Claude call path: the shared client, JSON reply parsing, and the
email/page recipe parser.

The real anthropic SDK client is used with an httpx MockTransport standing in
for the network, so these exercise the SDK's actual request serialization and
response parsing (model, fallbacks, beta header, thinking blocks), not a mock of it.
"""
import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from unittest.mock import patch

import anthropic
import httpx
import pytest

from app.config import Settings, settings
from app.services.claude_client import ClaudeRefusalError, request_text
from app.services.claude_json import parse_json_reply
from app.services.recipe_email_parser import parse_recipe_from_email, parse_recipe_from_page


@dataclass
class FakeClaude:
    """Serves canned Messages API responses and records each request body/headers."""
    text: str = '{"has_recipe": false}'
    stop_reason: str = "end_turn"
    status: int = 200
    requests: list[httpx.Request] = field(default_factory=list)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status != 200:
            return httpx.Response(self.status, json={
                "type": "error", "error": {"type": "api_error", "message": "boom"}})
        body = json.loads(request.content)
        content = [
            # Current models think by default; the thinking block comes first.
            {"type": "thinking", "thinking": "", "signature": "sig"},
        ]
        stop_details = None
        if self.stop_reason == "refusal":
            stop_details = {"type": "refusal", "category": "cyber", "explanation": "declined"}
        else:
            content.append({"type": "text", "text": self.text})
        return httpx.Response(200, json={
            "id": "msg_1", "type": "message", "role": "assistant", "model": body["model"],
            "content": content, "stop_reason": self.stop_reason, "stop_sequence": None,
            "stop_details": stop_details,
            "usage": {"input_tokens": 10, "output_tokens": 10},
        })

    @property
    def last_body(self) -> dict:
        return json.loads(self.requests[-1].content)

    @property
    def last_prompt(self) -> str:
        content = self.last_body["messages"][0]["content"]
        return content if isinstance(content, str) else json.dumps(content)


@pytest.fixture()
def claude() -> Iterator[FakeClaude]:
    fake = FakeClaude()
    client = anthropic.Anthropic(
        api_key="test-key",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(fake.handler)),
    )
    with patch("app.services.claude_client._client", client):
        yield fake


def _recipe_json(**overrides) -> str:
    data = {
        "has_recipe": True,
        "title": "Pancakes",
        "ingredients": "flour\neggs",
        "instructions": "mix\ncook",
    }
    data.update(overrides)
    return json.dumps(data)


# ── request_text (shared client) ──────────────────────────────────────────────

def test_request_uses_configured_model_and_refusal_fallbacks(claude):
    claude.text = "hello"
    assert request_text("hi") == "hello"

    body = claude.last_body
    assert body["model"] == settings.claude_model
    assert body["fallbacks"] == "default"
    assert body["max_tokens"] >= 16_000
    assert "server-side-fallback-2026-07-01" in claude.requests[-1].headers["anthropic-beta"]


def test_default_model_is_sonnet():
    # The declared default, not the live value: backend/.env may override CLAUDE_MODEL.
    assert Settings.model_fields["claude_model"].default == "claude-sonnet-5-5"


def test_model_follows_the_setting(claude):
    with patch.object(settings, "claude_model", "claude-opus-5-5"):
        request_text("hi")
    assert claude.last_body["model"] == "claude-opus-5-5"


def test_thinking_blocks_are_skipped(claude):
    claude.text = '{"a": 1}'
    assert request_text("hi") == '{"a": 1}'


def test_refusal_raises(claude):
    claude.stop_reason = "refusal"
    with pytest.raises(ClaudeRefusalError, match="cyber"):
        request_text("hi")


def test_api_error_propagates(claude):
    claude.status = 500
    with pytest.raises(anthropic.APIStatusError):
        request_text("hi")


def test_image_content_blocks_are_sent_unchanged(claude):
    blocks = [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"}},
              {"type": "text", "text": "extract"}]
    request_text(blocks)
    assert claude.last_body["messages"][0]["content"] == blocks


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

def test_email_with_recipe_returns_capture_result(claude):
    claude.text = _recipe_json()
    result = parse_recipe_from_email("Weekend brunch", "a@b.com", "body")
    assert result is not None
    assert result.title == "Pancakes"
    assert result.ingredients == "flour\neggs"
    assert "Subject: Weekend brunch" in claude.last_prompt


def test_email_without_recipe_returns_none(claude):
    claude.text = '{"has_recipe": false}'
    assert parse_recipe_from_email("Sale!", "a@b.com", "body") is None


def test_email_missing_title_falls_back_to_subject(claude):
    claude.text = _recipe_json(title=None)
    assert parse_recipe_from_email("Grandma's stew", "a@b.com", "body").title == "Grandma's stew"


def test_email_missing_title_and_subject_uses_generic_title(claude):
    claude.text = _recipe_json(title="")
    assert parse_recipe_from_email("", "a@b.com", "body").title == "Recipe from Email"


@pytest.mark.parametrize("reply", ["not json at all", "[1, 2, 3]", '"just a string"'])
def test_email_malformed_reply_returns_none(claude, reply):
    claude.text = reply
    assert parse_recipe_from_email("s", "a@b.com", "body") is None


def test_email_reply_failing_schema_validation_returns_none(claude):
    claude.text = _recipe_json(servings={"n": 4})
    assert parse_recipe_from_email("s", "a@b.com", "body") is None


def test_email_body_is_truncated_before_sending(claude):
    parse_recipe_from_email("s", "a@b.com", "~" * 50_000)
    assert claude.last_prompt.count("~") == 15_000


def test_email_api_error_propagates(claude):
    claude.status = 500
    with pytest.raises(anthropic.APIError):
        parse_recipe_from_email("s", "a@b.com", "body")


# ── parse_recipe_from_page ────────────────────────────────────────────────────

def test_page_missing_title_falls_back_to_url_slug(claude):
    claude.text = _recipe_json(title=None)
    result = parse_recipe_from_page("https://a.com/recipes/spicy_tofu-bowl/", "text")
    assert result.title == "Spicy Tofu Bowl"


def test_page_sends_source_url_and_returns_recipe(claude):
    claude.text = "```json\n" + _recipe_json() + "\n```"
    result = parse_recipe_from_page("https://a.com/r/1", "page text")
    assert result.title == "Pancakes"
    assert "Source URL: https://a.com/r/1" in claude.last_prompt


def test_page_without_recipe_returns_none(claude):
    claude.text = '{"has_recipe": false}'
    assert parse_recipe_from_page("https://a.com/x", "text") is None
