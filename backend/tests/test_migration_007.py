# =============================================================================
# Copyright (c) 2026 ZombieTech LLC. All rights reserved.
#
# SPDX-License-Identifier: PolyForm-Strict-1.0.0
# See LICENSE in the project root for the full terms.
#
# Licensing inquiries: license@zombietech.biz
# =============================================================================
# ai: claude-opus-5-5 | 2026-11-16
"""Migration 007 against pre-existing data: the backfill and the downgrade guard.

Steps the shared test DB down to 006 and back. Every test leaves it at head, so
the rest of the suite is unaffected; row cleanup is db_session's job.
"""
import pytest
from alembic import command
from sqlalchemy import text

from tests.conftest import alembic_config


@pytest.fixture()
def at_006(engine, db_session):
    # db_session first: it creates the test household, which this downgrade must drop,
    # and its teardown later deletes whatever rows the test left.
    # End db_session's open transaction: it holds a share lock on tenants (from its
    # household lookup) that would block the downgrade's DROP TABLE forever.
    db_session.rollback()
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM tenants"))
    command.downgrade(alembic_config(), "006")
    try:
        yield engine
    finally:
        command.upgrade(alembic_config(), "head")


def test_upgrade_assigns_existing_rows_to_the_default_household(at_006):
    with at_006.begin() as conn:
        conn.execute(text(
            "INSERT INTO recipes (title, source_type, image_key, image_url, thumbnail_key, thumbnail_url, "
            "created_at, updated_at) VALUES "
            "('Stored', 'web', 'originals/a.jpg', 'http://localhost:9000/b/originals/a.jpg', "
            " 'thumbnails/a.jpg', 'http://localhost:9000/b/thumbnails/a.jpg', now(), now()), "
            "('Linked', 'web', NULL, 'https://cdn.example.com/x.jpg', NULL, NULL, now(), now())"
        ))
        conn.execute(text("INSERT INTO app_settings (key, value) VALUES ('email_scan_labels', 'Dinner')"))
        conn.execute(text("INSERT INTO tag_categories (name, slug) VALUES ('Source', 'source')"))

    command.upgrade(alembic_config(), "007")

    with at_006.connect() as conn:
        default_id = conn.execute(text("SELECT id FROM tenants WHERE slug = 'default'")).scalar_one()
        rows = conn.execute(text("SELECT title, tenant_id, image_url, thumbnail_url FROM recipes ORDER BY title")).all()
        setting_tenant = conn.execute(text("SELECT tenant_id FROM app_settings")).scalar_one()
        category_tenant = conn.execute(text("SELECT tenant_id FROM tag_categories")).scalar_one()

    assert setting_tenant == category_tenant == default_id
    assert [(r.title, r.tenant_id) for r in rows] == [("Linked", default_id), ("Stored", default_id)]
    linked, stored = rows
    assert linked.image_url == "https://cdn.example.com/x.jpg"       # external link kept
    assert stored.image_url is None and stored.thumbnail_url is None  # dead MinIO URLs cleared


def test_downgrade_refuses_while_several_households_exist(at_006):
    command.upgrade(alembic_config(), "007")
    with at_006.begin() as conn:
        conn.execute(text("INSERT INTO tenants (name, slug, created_at) VALUES ('Second', 'second', now())"))

    with pytest.raises(RuntimeError, match="2 households exist"):
        command.downgrade(alembic_config(), "006")
