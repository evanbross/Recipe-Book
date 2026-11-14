# =============================================================================
# Copyright (c) 2026 ZombieTech LLC. All rights reserved.
#
# SPDX-License-Identifier: PolyForm-Strict-1.0.0
# See LICENSE in the project root for the full terms.
#
# Licensing inquiries: license@zombietech.biz
# =============================================================================
# ai: claude-opus-5-5 | 2026-11-14
"""Drop redundant indexes/constraints so the models and schema compare clean.

- ix_<table>_id indexes duplicated the primary-key index on four tables (and
  were missing on the others); primary keys are indexed already.
- scanned_emails.gmail_message_id and email_image_preferences.sender_domain each
  had both a UNIQUE constraint and a unique index; the unique index stays.

tests/test_schema.py asserts that autogenerate finds no diff after this.
"""
from __future__ import annotations

from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None

_PK_INDEXES = {
    "ix_recipes_id": "recipes",
    "ix_tag_categories_id": "tag_categories",
    "ix_tags_id": "tags",
    "ix_watched_sites_id": "watched_sites",
}
_DUPLICATE_UNIQUES = {
    "scanned_emails_gmail_message_id_key": ("scanned_emails", "gmail_message_id"),
    "email_image_preferences_sender_domain_key": ("email_image_preferences", "sender_domain"),
}


def upgrade() -> None:
    for index_name, table in _PK_INDEXES.items():
        op.drop_index(index_name, table_name=table)
    for constraint_name, (table, _column) in _DUPLICATE_UNIQUES.items():
        op.drop_constraint(constraint_name, table, type_="unique")


def downgrade() -> None:
    for constraint_name, (table, column) in _DUPLICATE_UNIQUES.items():
        op.create_unique_constraint(constraint_name, table, [column])
    for index_name, table in _PK_INDEXES.items():
        op.create_index(index_name, table, ["id"])
