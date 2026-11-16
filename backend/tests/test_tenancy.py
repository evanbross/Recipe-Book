# =============================================================================
# Copyright (c) 2026 ZombieTech LLC. All rights reserved.
#
# SPDX-License-Identifier: PolyForm-Strict-1.0.0
# See LICENSE in the project root for the full terms.
#
# Licensing inquiries: license@zombietech.biz
# =============================================================================
# ai: claude-opus-5-5 | 2026-11-16
"""
Household isolation, end to end against the real schema.

`client` acts for the default household (db_session's). `other_household` is a
session bound to a second household; anything it creates must be invisible and
untouchable through the API, and the enforcement hooks must fail closed.
"""
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app import models
from app.database import TenantMismatchError, TenantNotSetError, all_tenants_session


def _recipe(session, title: str, **extra) -> models.Recipe:
    recipe = models.Recipe(title=title, source_type="manual", **extra)
    session.add(recipe)
    session.commit()
    return recipe


def _tag(session, name: str, slug: str) -> models.Tag:
    tag = models.Tag(name=name, slug=slug)
    session.add(tag)
    session.commit()
    return tag


# ── recipes ───────────────────────────────────────────────────────────────────

def test_other_households_recipes_are_invisible(client, db_session, other_household):
    _recipe(db_session, "Ours")
    theirs = _recipe(other_household, "Theirs")

    assert [r["title"] for r in client.get("/recipes").json()] == ["Ours"]
    assert [r["title"] for r in client.get("/search", params={"q": "Theirs"}).json()["results"]] == []
    assert client.get(f"/recipes/{theirs.id}").status_code == 404


def test_other_households_recipes_cannot_be_changed(client, other_household):
    theirs = _recipe(other_household, "Theirs")

    assert client.patch(f"/recipes/{theirs.id}", json={"title": "Hijacked"}).status_code == 404
    assert client.delete(f"/recipes/{theirs.id}").status_code == 404

    other_household.expire_all()
    assert other_household.get(models.Recipe, theirs.id).title == "Theirs"


def test_purge_only_deletes_own_household(client, db_session, other_household):
    _recipe(db_session, "Ours")
    theirs = _recipe(other_household, "Theirs")

    assert client.delete("/admin/purge-recipes").json()["deleted_recipes"] == 1
    other_household.expire_all()
    assert other_household.get(models.Recipe, theirs.id) is not None


def test_new_rows_are_stamped_with_the_requesting_household(client, db_session):
    created = client.post("/recipes", json={"title": "Fresh"}).json()
    assert db_session.get(models.Recipe, created["id"]).tenant_id == db_session.info["tenant_id"]


# ── tags ──────────────────────────────────────────────────────────────────────

def test_other_households_tags_are_invisible_and_cannot_be_attached(client, other_household):
    theirs = _tag(other_household, "Secret", "secret")

    assert client.get("/tags").json() == []
    assert client.delete(f"/tags/{theirs.id}").status_code == 404
    created = client.post("/recipes", json={"title": "Mine", "tag_ids": [theirs.id]}).json()
    assert created["tags"] == []


def test_households_can_reuse_tag_and_category_names(client, other_household):
    other_category = models.TagCategory(name="Cuisine", slug="cuisine")
    other_household.add(other_category)
    other_household.commit()
    _tag(other_household, "Italian", "italian")

    category = client.post("/tags/categories", json={"name": "Cuisine"})
    assert category.status_code == 201, category.text
    tag = client.post("/tags", json={"name": "Italian"})
    assert tag.status_code == 201, tag.text


# ── settings, watchlist, email ────────────────────────────────────────────────

def test_settings_are_per_household(client, other_household):
    other_household.add(models.AppSetting(key="email_scan_max_per_folder", value="99"))
    other_household.commit()

    assert client.get("/email/settings").json()["max_per_folder"] != 99
    client.patch("/email/settings", json={"max_per_folder": 7})
    assert client.get("/email/settings").json()["max_per_folder"] == 7

    other_household.expire_all()
    assert other_household.scalar(
        select(models.AppSetting.value).where(models.AppSetting.key == "email_scan_max_per_folder")
    ) == "99"


def test_other_households_watched_sites_are_invisible(client, other_household):
    site = models.WatchedSite(name="Theirs", url="https://example.com")
    other_household.add(site)
    other_household.commit()

    assert client.get("/watchlist").json() == []
    assert client.delete(f"/watchlist/{site.id}").status_code == 404


def test_other_households_email_candidates_cannot_be_imported(client, other_household):
    scanned = models.ScannedEmail(gmail_message_id="m1", disposition="candidate")
    other_household.add(scanned)
    other_household.flush()
    candidate = models.EmailRecipeCandidate(scanned_email_id=scanned.id, title="Their email recipe")
    other_household.add(candidate)
    other_household.commit()

    assert client.get("/email/candidates").json() == []
    assert client.post(f"/email/candidates/{candidate.id}/import").status_code == 404
    assert client.delete(f"/email/candidates/{candidate.id}").status_code == 404


def test_same_gmail_message_can_be_scanned_by_two_households(db_session, other_household):
    for session in (db_session, other_household):
        session.add(models.ScannedEmail(gmail_message_id="shared", disposition="no_recipe"))
        session.commit()


# ── images ────────────────────────────────────────────────────────────────────

def test_images_are_served_only_to_the_owning_household(client, db_session, other_household):
    _recipe(db_session, "Ours", image_key="tenants/1/originals/ours.jpg")
    _recipe(other_household, "Theirs", image_key="tenants/2/originals/theirs.jpg")

    with patch("app.routes.images.storage_svc.get_image", return_value=(b"jpeg-bytes", "image/jpeg")) as get:
        ours = client.get("/images/tenants/1/originals/ours.jpg")
        theirs = client.get("/images/tenants/2/originals/theirs.jpg")

    assert ours.status_code == 200
    assert ours.content == b"jpeg-bytes"
    assert ours.headers["content-type"] == "image/jpeg"
    assert "private" in ours.headers["cache-control"]
    assert theirs.status_code == 404
    get.assert_called_once_with("tenants/1/originals/ours.jpg")


# ── enforcement fails closed ──────────────────────────────────────────────────

@pytest.fixture()
def unbound_session(engine):
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def test_unbound_session_cannot_read_household_data(unbound_session, db_session):
    _recipe(db_session, "Ours")
    with pytest.raises(TenantNotSetError):
        unbound_session.scalars(select(models.Recipe)).all()


def test_unbound_session_cannot_write_household_data(unbound_session, db_session):
    unbound_session.add(models.Recipe(title="Orphan", source_type="manual"))
    with pytest.raises(TenantNotSetError):
        unbound_session.flush()


def test_unbound_session_can_still_read_tenants(unbound_session, db_session):
    assert unbound_session.scalars(select(models.Tenant)).all()


def test_row_for_another_household_is_rejected(db_session, other_household):
    db_session.add(models.Recipe(title="Smuggled", source_type="manual", tenant_id=other_household.info["tenant_id"]))
    with pytest.raises(TenantMismatchError):
        db_session.flush()


def test_session_get_is_scoped(db_session, other_household):
    theirs = _recipe(other_household, "Theirs")
    assert db_session.get(models.Recipe, theirs.id) is None


def test_bulk_updates_are_scoped(db_session, other_household):
    _recipe(other_household, "Theirs")
    updated = db_session.query(models.Recipe).update({"title": "Mass edit"})
    db_session.commit()
    assert updated == 0
    other_household.expire_all()
    assert other_household.scalars(select(models.Recipe.title)).all() == ["Theirs"]


def test_all_tenants_session_spans_households(db_session, other_household):
    _recipe(db_session, "Ours")
    _recipe(other_household, "Theirs")
    with all_tenants_session() as session:
        titles = sorted(session.scalars(select(models.Recipe.title)))
    assert titles == ["Ours", "Theirs"]


def test_scan_status_and_report_are_hidden_from_other_households(client, other_household):
    # The scan state is server-global (one Gmail connection per server); only the
    # household that ran the scan may see its progress and per-email log.
    running = {"running": True, "processed": 3, "total": 9, "errors": [], "started_at": "2026-11-16T00:00:00"}
    with patch("app.routes.email_scan._scan_owner_tenant_id", other_household.info["tenant_id"]), \
            patch.dict("app.routes.email_scan._scan_status", running), \
            patch("app.routes.email_scan._scan_log", [{"subject": "Their newsletter"}]):
        status = client.get("/email/scan/status").json()
        report = client.get("/email/scan/report").json()

    assert status["running"] is False and status["processed"] == 0
    assert report["entries"] == [] and report["started_at"] is None
