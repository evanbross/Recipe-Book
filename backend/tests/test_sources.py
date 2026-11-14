# =============================================================================
# Copyright (c) 2026 ZombieTech LLC. All rights reserved.
#
# SPDX-License-Identifier: PolyForm-Strict-1.0.0
# See LICENSE in the project root for the full terms.
#
# Licensing inquiries: license@zombietech.biz
# =============================================================================
# ai: claude-opus-5-5 | 2026-11-14
"""Tests for source-name derivation and the Source-tag upsert (real test DB)."""
import pytest

from app import models
from app.services.sources import get_or_create_source_tag, resolve_source_name


# ── resolve_source_name ──────────────────────────────────────────────────────

@pytest.mark.parametrize("url, expected", [
    ("https://www.seriouseats.com/best-chili", "Serious Eats"),
    ("https://cooking.nytimes.com/recipes/123", "New York Times Cooking"),
    # Host case and an explicit port must not defeat the known-source lookup.
    ("https://WWW.SeriousEats.com:443/x", "Serious Eats"),
])
def test_resolve_known_source(url, expected):
    assert resolve_source_name(url) == expected


def test_known_source_beats_jsonld():
    jsonld = {"publisher": {"name": "Some Publisher"}}
    assert resolve_source_name("https://www.bonappetit.com/r", jsonld) == "Bon Appétit"


@pytest.mark.parametrize("jsonld, expected", [
    ({"publisher": {"name": "  Grandma's Kitchen "}}, "Grandma's Kitchen"),
    ({"author": "Jane Cook"}, "Jane Cook"),
    # Publisher wins over author when both are present.
    ({"publisher": {"name": "Pub"}, "author": "Auth"}, "Pub"),
])
def test_resolve_from_jsonld(jsonld, expected):
    assert resolve_source_name("https://unknown-blog.com/r", jsonld) == expected


@pytest.mark.parametrize("jsonld", [
    {"publisher": {"name": ""}},
    {"publisher": ["not", "a", "dict"]},
])
def test_unusable_jsonld_falls_back_to_domain(jsonld):
    assert resolve_source_name("https://unknown-blog.com/r", jsonld) == "Unknown Blog"


@pytest.mark.parametrize("url, expected", [
    ("https://www.some-blog.com/r", "Some Blog"),
    ("https://my_food_site.net/r", "My Food Site"),
    # Two-part public suffix: the name is the label before "co.uk", not "My Blog.co".
    ("https://www.my-blog.co.uk/r", "My Blog"),
    # Subdomains don't leak into the name.
    ("https://recipes.example.com/r", "Example"),
    # Uppercase host and port are normalized before prettifying.
    ("https://WWW.Tasty-Corner.com:8080/r", "Tasty Corner"),
])
def test_resolve_prettified_domain_fallback(url, expected):
    assert resolve_source_name(url) == expected


def test_resolve_returns_none_without_host():
    assert resolve_source_name("not a url") is None


# ── get_or_create_source_tag ─────────────────────────────────────────────────

def test_creates_source_category_and_tag(db_session):
    tag = get_or_create_source_tag(db_session, "Bon Appétit")
    db_session.commit()

    assert tag.name == "Bon Appétit"
    assert tag.slug == "bon-appetit"  # accents folded to ASCII
    assert tag.category.slug == "source"
    assert tag.category.name == "Source"


def test_repeat_calls_reuse_the_same_tag(db_session):
    first = get_or_create_source_tag(db_session, "Serious Eats")
    db_session.commit()
    second = get_or_create_source_tag(db_session, "Serious Eats")
    db_session.commit()

    assert second.id == first.id
    assert db_session.query(models.Tag).filter_by(slug="serious-eats").count() == 1
    assert db_session.query(models.TagCategory).filter_by(slug="source").count() == 1


def test_reuses_existing_source_category(db_session, make_category):
    existing = make_category(name="Source", slug="source")

    tag = get_or_create_source_tag(db_session, "Food52")
    db_session.commit()

    assert tag.category_id == existing.id


def test_same_slug_in_another_category_is_a_separate_tag(db_session, make_category, make_tag):
    cuisine = make_category(name="Cuisine", slug="cuisine")
    other = make_tag(name="Maangchi", slug="maangchi", category_id=cuisine.id)

    tag = get_or_create_source_tag(db_session, "Maangchi")
    db_session.commit()

    assert tag.id != other.id
    assert tag.category.slug == "source"


def test_empty_source_name_returns_none(db_session):
    assert get_or_create_source_tag(db_session, "") is None
