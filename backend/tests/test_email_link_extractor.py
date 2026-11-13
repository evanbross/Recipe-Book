# =============================================================================
# Copyright (c) 2026 ZombieTech LLC. All rights reserved.
#
# SPDX-License-Identifier: PolyForm-Strict-1.0.0
# See LICENSE in the project root for the full terms.
#
# Licensing inquiries: license@zombietech.biz
# =============================================================================
# ai: claude-opus-5-5 | 2026-11-13
"""Unit tests for the email recipe-link heuristics (pure HTML parsing, no I/O)."""
from app.services.email_link_extractor import extract_recipe_links


def _a(href: str, text: str) -> str:
    return f'<a href="{href}">{text}</a>'


def test_empty_html_returns_empty_list():
    assert extract_recipe_links("") == []


def test_cta_text_links_come_before_path_matches():
    html = (
        _a("https://site.com/recipes/soup", "Tomato soup")
        + _a("https://other.com/cake", "Get the Recipe")
    )
    assert extract_recipe_links(html) == [
        "https://other.com/cake",
        "https://site.com/recipes/soup",
    ]


def test_cta_matching_is_case_insensitive_and_ignores_trailing_period():
    assert extract_recipe_links(_a("https://a.com/x", "VIEW RECIPE.")) == ["https://a.com/x"]


def test_cta_contains_phrase_matches_sentence_style_links():
    html = _a("https://a.com/article", "you can access the article and video here")
    assert extract_recipe_links(html) == ["https://a.com/article"]


def test_unrelated_links_are_ignored():
    html = _a("https://a.com/about", "About us") + _a("https://a.com/shop", "Shop now")
    assert extract_recipe_links(html) == []


def test_relative_and_mailto_links_are_ignored():
    html = _a("/recipes/soup", "Get recipe") + _a("mailto:x@y.com", "Get recipe")
    assert extract_recipe_links(html) == []


def test_tracking_and_unsubscribe_links_are_dropped():
    html = (
        _a("https://click.em.site.com/recipes/soup", "Get recipe")
        + _a("https://site.com/unsubscribe?u=1", "recipe")
    )
    assert extract_recipe_links(html) == []


def test_duplicates_differing_only_in_query_fragment_or_slash_are_collapsed():
    html = (
        _a("https://a.com/recipes/soup?utm=1", "Get recipe")
        + _a("https://a.com/recipes/soup/#top", "Soup")
    )
    assert extract_recipe_links(html) == ["https://a.com/recipes/soup?utm=1"]


def test_result_is_capped_at_ten():
    html = "".join(_a(f"https://a.com/recipes/{i}", f"r{i}") for i in range(15))
    links = extract_recipe_links(html)
    assert len(links) == 10
    assert links[0] == "https://a.com/recipes/0"
