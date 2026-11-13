# =============================================================================
# Copyright (c) 2026 ZombieTech LLC. All rights reserved.
#
# SPDX-License-Identifier: PolyForm-Strict-1.0.0
# See LICENSE in the project root for the full terms.
#
# Licensing inquiries: license@zombietech.biz
# =============================================================================
"""Parse JSON replies from Claude.

Leaf module (no project imports) so every Claude-calling service can share it
without creating an import cycle.
"""
import json


# ai: claude-opus-5-5 | 2026-11-13
def parse_json_reply(text: str) -> object:
    """Strip an optional ```json / ``` code fence from a Claude reply and parse it.

    Prompts ask for bare JSON, but models sometimes wrap it in a fence anyway.

    Raises:
        json.JSONDecodeError: the reply is not valid JSON.
    """
    clean = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(clean)
