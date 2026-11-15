# =============================================================================
# Copyright (c) 2026 ZombieTech LLC. All rights reserved.
#
# SPDX-License-Identifier: PolyForm-Strict-1.0.0
# See LICENSE in the project root for the full terms.
#
# Licensing inquiries: license@zombietech.biz
# =============================================================================
# ai: claude-opus-5-5 | 2026-11-14
"""Recompute every tag slug from its name with the server-side slugify.

Slugs used to be derived twice -- by the frontend's toSlug and the backend's
_to_slug -- and the two disagreed ('Quick & Easy' -> 'quick--easy' vs
'quick-easy'; accents dropped vs folded). The server now owns derivation, so
existing rows are brought in line. Tags whose new (category_id, slug) collide
are merged into the lowest id, as in migration 004.
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict

import sqlalchemy as sa
from alembic import op

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def _slugify(name: str) -> str:
    """Frozen copy of app.services.slugs.slugify as of this migration.

    Migrations must not import app code: a later change to the helper would
    silently change what this historical migration does.
    """
    ascii_only = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_only.lower()).strip("-")
    return slug[:100].rstrip("-")


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, name, slug, category_id FROM tags ORDER BY id")).all()

    groups: dict[tuple[int | None, str], list[int]] = defaultdict(list)
    new_slug: dict[int, str] = {}
    for tag_id, name, old_slug, category_id in rows:
        # A name with no ASCII letters/digits has nothing to derive from; keep its slug.
        slug = _slugify(name) or old_slug
        new_slug[tag_id] = slug
        groups[(category_id, slug)].append(tag_id)

    for ids in groups.values():
        keep, *dupes = ids  # ids are ascending, so keep is the lowest
        for dup in dupes:
            conn.execute(sa.text(
                "INSERT INTO recipe_tags (recipe_id, tag_id) "
                "SELECT recipe_id, :keep FROM recipe_tags WHERE tag_id = :dup "
                "ON CONFLICT DO NOTHING"
            ), {"keep": keep, "dup": dup})
            conn.execute(sa.text("DELETE FROM tags WHERE id = :dup"), {"dup": dup})  # cascades recipe_tags
            del new_slug[dup]

    # Two passes so a row taking another row's old slug never trips the unique
    # constraint mid-update: first park every changing row on a unique temp slug.
    changing = {
        tag_id: slug for tag_id, _name, old_slug, _cat in rows
        if tag_id in new_slug and (slug := new_slug[tag_id]) != old_slug
    }
    for tag_id in changing:
        conn.execute(sa.text("UPDATE tags SET slug = :tmp WHERE id = :id"),
                     {"tmp": f"__reslug-{tag_id}", "id": tag_id})
    for tag_id, slug in changing.items():
        conn.execute(sa.text("UPDATE tags SET slug = :slug WHERE id = :id"), {"slug": slug, "id": tag_id})


def downgrade() -> None:
    # Old slugs and merged duplicates are not restorable; the schema is unchanged.
    pass
