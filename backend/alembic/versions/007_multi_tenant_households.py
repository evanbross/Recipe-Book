# =============================================================================
# Copyright (c) 2026 ZombieTech LLC. All rights reserved.
#
# SPDX-License-Identifier: PolyForm-Strict-1.0.0
# See LICENSE in the project root for the full terms.
#
# Licensing inquiries: license@zombietech.biz
# =============================================================================
# ai: claude-opus-5-5 | 2026-11-16
"""Multi-tenant households.

- New tables: tenants (households), users, tenant_memberships.
- tenant_id (NOT NULL, FK, ON DELETE CASCADE) on every household-owned table.
- Uniqueness becomes per household: tag category name/slug, tag
  (category, slug), Gmail message id, image-preference sender domain, and the
  app_settings primary key (now tenant_id + key).
- Backfill: one default household (slug 'default') owns every existing row.
- Stored MinIO image URLs are cleared where a key exists: images are now
  served through the API from the key, so the stored URL was dead data.

Downgrade is only possible while a single household exists, since the old
global uniqueness rules can't hold multiple households' rows. Cleared image
URLs are not restored (the API derives them from the keys either way).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None

# Frozen copy of settings.default_tenant_slug's default as of this migration.
_DEFAULT_TENANT_SLUG = "default"
_DEFAULT_TENANT_NAME = "My household"

_TENANT_TABLES = (
    "tag_categories", "tags", "recipes", "scanned_emails", "email_recipe_candidates",
    "app_settings", "recipe_image_candidates", "watched_sites", "email_image_preferences",
)
# Tables whose tenant_id isn't the leading column of a composite unique/PK get their own index.
_TENANT_INDEXED = ("recipes", "email_recipe_candidates", "recipe_image_candidates", "watched_sites")


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("slug", name="tenants_slug_key"),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("email", name="users_email_key"),
    )
    op.create_table(
        "tenant_memberships",
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_tenant_memberships_user_id", "tenant_memberships", ["user_id"])

    conn = op.get_bind()
    default_id = conn.execute(
        sa.text(
            "INSERT INTO tenants (name, slug, created_at) "
            "VALUES (:name, :slug, (NOW() AT TIME ZONE 'UTC')) RETURNING id"
        ),
        {"name": _DEFAULT_TENANT_NAME, "slug": _DEFAULT_TENANT_SLUG},
    ).scalar_one()

    for table in _TENANT_TABLES:
        op.add_column(table, sa.Column("tenant_id", sa.Integer(), nullable=True))
        conn.execute(sa.text(f"UPDATE {table} SET tenant_id = :tid"), {"tid": default_id})
        op.alter_column(table, "tenant_id", nullable=False)
        op.create_foreign_key(f"{table}_tenant_id_fkey", table, "tenants", ["tenant_id"], ["id"], ondelete="CASCADE")
    for table in _TENANT_INDEXED:
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])

    # Global uniqueness -> per household.
    op.drop_constraint("tag_categories_name_key", "tag_categories", type_="unique")
    op.drop_constraint("tag_categories_slug_key", "tag_categories", type_="unique")
    op.create_unique_constraint("uq_tag_categories_tenant_id_name", "tag_categories", ["tenant_id", "name"])
    op.create_unique_constraint("uq_tag_categories_tenant_id_slug", "tag_categories", ["tenant_id", "slug"])

    op.drop_constraint("uq_tags_category_id_slug", "tags", type_="unique")
    op.create_unique_constraint(
        "uq_tags_tenant_id_category_id_slug", "tags", ["tenant_id", "category_id", "slug"],
        postgresql_nulls_not_distinct=True,
    )

    op.drop_index("ix_scanned_emails_gmail_message_id", table_name="scanned_emails")
    op.create_unique_constraint(
        "uq_scanned_emails_tenant_id_gmail_message_id", "scanned_emails", ["tenant_id", "gmail_message_id"],
    )

    op.drop_index("ix_email_image_preferences_sender_domain", table_name="email_image_preferences")
    op.create_unique_constraint(
        "uq_email_image_preferences_tenant_id_sender_domain", "email_image_preferences", ["tenant_id", "sender_domain"],
    )

    op.drop_constraint("app_settings_pkey", "app_settings", type_="primary")
    op.create_primary_key("app_settings_pkey", "app_settings", ["tenant_id", "key"])

    op.execute("UPDATE recipes SET image_url = NULL WHERE image_key IS NOT NULL")
    op.execute("UPDATE recipes SET thumbnail_url = NULL WHERE thumbnail_key IS NOT NULL")


def downgrade() -> None:
    conn = op.get_bind()
    households = conn.execute(sa.text("SELECT count(*) FROM tenants")).scalar_one()
    if households > 1:
        raise RuntimeError(
            f"Cannot downgrade: {households} households exist, and the pre-007 schema "
            "can only hold one. Delete the extra households first."
        )

    op.drop_constraint("app_settings_pkey", "app_settings", type_="primary")
    op.create_primary_key("app_settings_pkey", "app_settings", ["key"])

    op.drop_constraint("uq_email_image_preferences_tenant_id_sender_domain", "email_image_preferences", type_="unique")
    op.create_index("ix_email_image_preferences_sender_domain", "email_image_preferences", ["sender_domain"], unique=True)

    op.drop_constraint("uq_scanned_emails_tenant_id_gmail_message_id", "scanned_emails", type_="unique")
    op.create_index("ix_scanned_emails_gmail_message_id", "scanned_emails", ["gmail_message_id"], unique=True)

    op.drop_constraint("uq_tags_tenant_id_category_id_slug", "tags", type_="unique")
    op.create_unique_constraint(
        "uq_tags_category_id_slug", "tags", ["category_id", "slug"], postgresql_nulls_not_distinct=True,
    )

    op.drop_constraint("uq_tag_categories_tenant_id_slug", "tag_categories", type_="unique")
    op.drop_constraint("uq_tag_categories_tenant_id_name", "tag_categories", type_="unique")
    op.create_unique_constraint("tag_categories_slug_key", "tag_categories", ["slug"])
    op.create_unique_constraint("tag_categories_name_key", "tag_categories", ["name"])

    for table in _TENANT_INDEXED:
        op.drop_index(f"ix_{table}_tenant_id", table_name=table)
    for table in _TENANT_TABLES:
        op.drop_constraint(f"{table}_tenant_id_fkey", table, type_="foreignkey")
        op.drop_column(table, "tenant_id")

    op.drop_index("ix_tenant_memberships_user_id", table_name="tenant_memberships")
    op.drop_table("tenant_memberships")
    op.drop_table("users")
    op.drop_table("tenants")
