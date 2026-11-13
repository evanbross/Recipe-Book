# =============================================================================
# Copyright (c) 2026 ZombieTech LLC. All rights reserved.
#
# SPDX-License-Identifier: PolyForm-Strict-1.0.0
# See LICENSE in the project root for the full terms.
#
# Licensing inquiries: license@zombietech.biz
# =============================================================================
# ai: claude-opus-5-5 | 2026-11-13
"""Integration tests for /watchlist against the real test database."""
from datetime import datetime, timedelta, timezone

import pytest

from app import models


@pytest.fixture()
def make_site(db_session):
    def _make_site(name: str = "Serious Eats", check_every_days: int = 7,
                   last_visited_at: datetime | None = None) -> models.WatchedSite:
        site = models.WatchedSite(
            name=name, url=f"https://{name.lower().replace(' ', '')}.com",
            check_every_days=check_every_days, last_visited_at=last_visited_at,
        )
        db_session.add(site)
        db_session.commit()
        db_session.refresh(site)
        return site

    return _make_site


def _ago(days: float) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


def test_create_site_defaults_interval_and_is_due(client):
    res = client.post("/watchlist", json={"name": "NYT Cooking", "url": "https://cooking.nytimes.com"})
    assert res.status_code == 201
    body = res.json()
    assert body["check_every_days"] == 7
    assert body["last_visited_at"] is None
    assert body["due"] is True


def test_list_sites_is_ordered_by_name(client, make_site):
    make_site("Zebra Kitchen")
    make_site("Apple Pie Blog")
    names = [s["name"] for s in client.get("/watchlist").json()]
    assert names == ["Apple Pie Blog", "Zebra Kitchen"]


def test_due_lists_only_sites_whose_interval_elapsed(client, make_site):
    make_site("Never Visited")
    make_site("Overdue", check_every_days=7, last_visited_at=_ago(8))
    make_site("Fresh", check_every_days=7, last_visited_at=_ago(1))
    due = {s["name"] for s in client.get("/watchlist/due").json()}
    assert due == {"Never Visited", "Overdue"}


def test_mark_visited_resets_due(client, make_site):
    site = make_site(last_visited_at=_ago(30))
    res = client.post(f"/watchlist/{site.id}/visit")
    assert res.status_code == 200
    assert res.json()["due"] is False
    assert client.get("/watchlist/due").json() == []


def test_update_site_changes_only_given_fields(client, make_site):
    site = make_site("Old Name", check_every_days=7)
    res = client.patch(f"/watchlist/{site.id}", json={"check_every_days": 14})
    assert res.status_code == 200
    assert res.json()["name"] == "Old Name"
    assert res.json()["check_every_days"] == 14


def test_delete_site(client, make_site, db_session):
    site = make_site()
    assert client.delete(f"/watchlist/{site.id}").status_code == 204
    db_session.expire_all()
    assert db_session.get(models.WatchedSite, site.id) is None


@pytest.mark.parametrize("method,path", [
    ("patch", "/watchlist/999999"),
    ("delete", "/watchlist/999999"),
    ("post", "/watchlist/999999/visit"),
])
def test_missing_site_returns_404(client, method, path):
    kwargs = {"json": {"name": "x"}} if method == "patch" else {}
    assert getattr(client, method)(path, **kwargs).status_code == 404


@pytest.mark.parametrize("days", [0, -3])
def test_non_positive_interval_is_rejected(client, make_site, days):
    res = client.post("/watchlist", json={"name": "x", "url": "https://x.com", "check_every_days": days})
    assert res.status_code == 422
    site = make_site()
    assert client.patch(f"/watchlist/{site.id}", json={"check_every_days": days}).status_code == 422
