# =============================================================================
# Copyright (c) 2026 ZombieTech LLC. All rights reserved.
#
# SPDX-License-Identifier: PolyForm-Strict-1.0.0
# See LICENSE in the project root for the full terms.
#
# Licensing inquiries: license@zombietech.biz
# =============================================================================
# ai: claude-opus-5-5 | 2026-11-14
"""Make tag slugs unique within a category (NULL category counts as one group).

Without this, sources.get_or_create_source_tag's IntegrityError-based upsert
never fired and every capture from a site created another copy of its Source tag.
Any existing duplicates are merged into the lowest-id tag first.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "004"
down_revision = "d74078c4737f"
branch_labels = None
depends_on = None

_CONSTRAINT = "uq_tags_category_id_slug"

# Maps every duplicate tag id to the lowest id in its (category_id, slug) group.
# IS NOT DISTINCT FROM groups NULL categories together, matching the constraint.
_DUPLICATES_CTE = """
    WITH dupes AS (
        SELECT t.id AS dup_id, keep.id AS keep_id
        FROM tags t
        JOIN LATERAL (
            SELECT MIN(k.id) AS id FROM tags k
            WHERE k.slug = t.slug AND k.category_id IS NOT DISTINCT FROM t.category_id
        ) keep ON keep.id <> t.id
    )
"""


def upgrade() -> None:
    op.execute(sa.text(_DUPLICATES_CTE + """
        INSERT INTO recipe_tags (recipe_id, tag_id)
        SELECT rt.recipe_id, d.keep_id
        FROM recipe_tags rt JOIN dupes d ON d.dup_id = rt.tag_id
        ON CONFLICT DO NOTHING
    """))
    # recipe_tags rows for the duplicates go with them (ON DELETE CASCADE).
    op.execute(sa.text(_DUPLICATES_CTE + """
        DELETE FROM tags WHERE id IN (SELECT dup_id FROM dupes)
    """))
    op.create_unique_constraint(
        _CONSTRAINT, "tags", ["category_id", "slug"], postgresql_nulls_not_distinct=True,
    )


def downgrade() -> None:
    # Merged duplicates are not restored; only the constraint is removed.
    op.drop_constraint(_CONSTRAINT, "tags", type_="unique")
