# =============================================================================
# Copyright (c) 2026 ZombieTech LLC. All rights reserved.
#
# SPDX-License-Identifier: PolyForm-Strict-1.0.0
# See LICENSE in the project root for the full terms.
#
# Licensing inquiries: license@zombietech.biz
# =============================================================================
"""The one place this app calls Claude.

Every service sends its prompt through request_text(), so the model (the
CLAUDE_MODEL setting), refusal fallbacks, and response handling are defined once.
"""
import logging
from typing import Any

import anthropic

from app.config import settings

logger = logging.getLogger(__name__)

_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

# Non-streaming ceiling. Current models think by default and thinking tokens
# count toward max_tokens, so a tight cap could cut the JSON reply off mid-way.
_MAX_TOKENS = 16_000

# Server-side refusal fallback: if a safety classifier declines, the API retries
# the same request on a fallback model it picks by refusal category, in one call.
_FALLBACK_BETA = "server-side-fallback-2026-07-01"


class ClaudeRefusalError(RuntimeError):
    """Claude (and its fallback) declined the request; there is no answer text."""


# ai: claude-opus-5-5 | 2026-11-13
def request_text(content: str | list[dict[str, Any]]) -> str:
    """Send one user message to the configured model and return its text reply.

    Thinking blocks are skipped; only text blocks are returned, joined.

    Raises:
        ClaudeRefusalError: the request was declined.
        anthropic.APIError: the API call failed (after the SDK's own retries).
    """
    response = _client.beta.messages.create(
        model=settings.claude_model,
        max_tokens=_MAX_TOKENS,
        betas=[_FALLBACK_BETA],
        fallbacks="default",
        messages=[{"role": "user", "content": content}],
    )

    if response.stop_reason == "refusal":
        category = response.stop_details.category if response.stop_details else None
        raise ClaudeRefusalError(f"Claude declined the request (category: {category})")
    if response.stop_reason == "max_tokens":
        logger.warning("Claude reply hit max_tokens (%d); it is likely truncated", _MAX_TOKENS)

    return "".join(block.text for block in response.content if block.type == "text")
