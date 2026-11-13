# =============================================================================
# Copyright (c) 2026 ZombieTech LLC. All rights reserved.
#
# SPDX-License-Identifier: PolyForm-Strict-1.0.0
# See LICENSE in the project root for the full terms.
#
# Licensing inquiries: license@zombietech.biz
# =============================================================================
# ai: claude-opus-5-5 | 2026-11-13
"""Integration tests for email image-candidate scoring and preference learning,
run against the real (Alembic-built) test schema. Network and MinIO are stubbed."""
from unittest.mock import patch

import pytest

from app import models
from app.services import image_candidates as svc

_STORED = {
    "image_key": "originals/abc.jpg", "image_url": "http://minio/originals/abc.jpg",
    "thumbnail_key": "thumbnails/abc.jpg", "thumbnail_url": "http://minio/thumbnails/abc.jpg",
}


def _img(src: str, alt: str = "", w: int | None = None, h: int | None = None) -> str:
    size = f' width="{w}" height="{h}"' if w and h else ""
    return f'<img src="{src}" alt="{alt}"{size}>'


def _candidates(db_session, recipe_id: int) -> list[models.RecipeImageCandidate]:
    return (db_session.query(models.RecipeImageCandidate)
            .filter_by(recipe_id=recipe_id).order_by(models.RecipeImageCandidate.rank).all())


def _pref(db_session, domain: str) -> models.EmailImagePreference | None:
    db_session.expire_all()
    return db_session.query(models.EmailImagePreference).filter_by(sender_domain=domain).first()


# ── prepare_candidates ────────────────────────────────────────────────────────

def test_prepare_stores_top_three_ranked_by_score(db_session, make_recipe):
    recipe = make_recipe()
    html = "".join([
        _img("https://cdn.a.com/1.jpg", w=100, h=100),
        _img("https://cdn.a.com/hero.jpg", alt="Chicken soup", w=1200, h=800),
        _img("https://cdn.a.com/3.jpg"),
        _img("https://cdn.a.com/4.jpg"),
        _img("https://cdn.a.com/5.jpg"),
    ])
    assert svc.prepare_candidates(db_session, recipe, "News <hi@a.com>", html) is True
    db_session.commit()

    cands = _candidates(db_session, recipe.id)
    assert len(cands) == 3
    assert cands[0].image_url == "https://cdn.a.com/hero.jpg"
    assert [c.rank for c in cands] == [0, 1, 2]
    assert cands[0].score >= cands[1].score >= cands[2].score
    assert {c.sender_domain for c in cands} == {"a.com"}


def test_prepare_skips_logos_trackers_tiny_and_relative_images(db_session, make_recipe):
    recipe = make_recipe()
    html = "".join([
        _img("https://a.com/logo.png"),
        _img("https://a.com/pixel.gif"),
        _img("https://a.com/x.gif", w=1, h=1),
        _img("/relative.jpg"),
    ])
    assert svc.prepare_candidates(db_session, recipe, "hi@a.com", html) is False
    assert _candidates(db_session, recipe.id) == []


def test_prepare_scores_linked_recipe_og_image_highest(db_session, make_recipe):
    recipe = make_recipe()
    html = '<a href="https://a.com/recipes/soup">Soup</a>' + _img("https://cdn.a.com/x.jpg", w=1200, h=800)
    with patch("app.services.image_candidates.scraper_svc.fetch_page",
               return_value=("text", "https://a.com/og.jpg", "https://a.com/recipes/soup", None)) as fetch:
        svc.prepare_candidates(db_session, recipe, "hi@a.com", html)
    fetch.assert_called_once_with("https://a.com/recipes/soup")
    db_session.commit()
    assert _candidates(db_session, recipe.id)[0].image_url == "https://a.com/og.jpg"


def test_prepare_survives_blocked_source_url(db_session, make_recipe):
    recipe = make_recipe()
    html = '<a href="https://a.com/recipes/soup">Soup</a>' + _img("https://cdn.a.com/x.jpg")
    with patch("app.services.image_candidates.scraper_svc.fetch_page",
               side_effect=ValueError("blocked")):
        assert svc.prepare_candidates(db_session, recipe, "hi@a.com", html) is True


def test_prepare_preference_boost_reorders_candidates(db_session, make_recipe):
    svc.update_preference(db_session, "a.com", "https://favored.cdn/pic.jpg", selected_rank=2)
    recipe = make_recipe()
    # Unboosted: other=57 (30 base + 9 size + 18 position), favored=50 (30 + 5 + 15).
    # The +25 image-domain boost lifts favored to 75, flipping the order.
    html = "".join([
        _img("https://other.cdn/1.jpg", w=300, h=200),
        _img("https://favored.cdn/2.jpg"),
    ])
    svc.prepare_candidates(db_session, recipe, "hi@a.com", html)
    db_session.commit()
    assert _candidates(db_session, recipe.id)[0].image_url == "https://favored.cdn/2.jpg"


# ── update_preference ─────────────────────────────────────────────────────────

def test_update_preference_inserts_then_increments(db_session):
    svc.update_preference(db_session, "a.com", "https://img1.cdn/x.jpg", selected_rank=0)
    pref = _pref(db_session, "a.com")
    assert (pref.selection_count, pref.url_domain, pref.preferred_rank) == (1, "img1.cdn", 0)

    svc.update_preference(db_session, "a.com", "https://img2.cdn/y.jpg", selected_rank=1)
    pref = _pref(db_session, "a.com")
    assert (pref.selection_count, pref.url_domain, pref.preferred_rank) == (2, "img2.cdn", 1)
    assert db_session.query(models.EmailImagePreference).count() == 1


def test_update_preference_ignores_empty_sender(db_session):
    svc.update_preference(db_session, "", "https://img.cdn/x.jpg", selected_rank=0)
    assert db_session.query(models.EmailImagePreference).count() == 0


# ── maybe_auto_apply ──────────────────────────────────────────────────────────

def _recipe_with_candidate(db_session, make_recipe, score: int):
    recipe = make_recipe(image_pending=True)
    db_session.add(models.RecipeImageCandidate(
        recipe_id=recipe.id, image_url="https://cdn.a.com/hero.jpg",
        score=score, rank=0, sender_domain="a.com",
    ))
    db_session.commit()
    return recipe


def _confirm_picks(db_session, count: int) -> None:
    for _ in range(count):
        svc.update_preference(db_session, "a.com", "https://cdn.a.com/x.jpg", selected_rank=0)


@pytest.mark.parametrize("picks,score", [(2, 95), (3, 79)])
def test_auto_apply_requires_enough_picks_and_score(db_session, make_recipe, picks, score):
    recipe = _recipe_with_candidate(db_session, make_recipe, score)
    _confirm_picks(db_session, picks)
    with patch("app.services.image_candidates.scraper_svc.fetch_page_image") as fetch:
        assert svc.maybe_auto_apply(db_session, recipe) is False
    fetch.assert_not_called()


def test_auto_apply_downloads_stores_and_clears_pending(db_session, make_recipe):
    recipe = _recipe_with_candidate(db_session, make_recipe, score=90)
    _confirm_picks(db_session, 3)
    with patch("app.services.image_candidates.scraper_svc.fetch_page_image",
               return_value=(b"bytes", "image/jpeg")), \
            patch("app.services.image_candidates.storage_svc.upload_image", return_value=_STORED), \
            patch("app.services.image_candidates.storage_svc.tag_objects_with_recipe_id") as tag:
        assert svc.maybe_auto_apply(db_session, recipe) is True

    db_session.expire_all()
    saved = db_session.get(models.Recipe, recipe.id)
    assert saved.image_pending is False
    assert saved.image_key == "originals/abc.jpg"
    assert _candidates(db_session, recipe.id)[0].selected is True
    tag.assert_called_once_with("originals/abc.jpg", "thumbnails/abc.jpg", recipe.id)


def test_auto_apply_download_failure_leaves_recipe_pending(db_session, make_recipe):
    recipe = _recipe_with_candidate(db_session, make_recipe, score=90)
    _confirm_picks(db_session, 3)
    with patch("app.services.image_candidates.scraper_svc.fetch_page_image",
               side_effect=OSError("connection reset")):
        assert svc.maybe_auto_apply(db_session, recipe) is False
    db_session.expire_all()
    assert db_session.get(models.Recipe, recipe.id).image_pending is True
