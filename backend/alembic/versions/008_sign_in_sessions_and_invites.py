# =============================================================================
# Copyright (c) 2026 ZombieTech LLC. All rights reserved.
#
# SPDX-License-Identifier: PolyForm-Strict-1.0.0
# See LICENSE in the project root for the full terms.
#
# Licensing inquiries: license@zombietech.biz
# =============================================================================
# ai: claude-opus-5-5 | 2026-11-17
"""Google sign-in: sessions and household invites.

- user_sessions: one row per signed-in browser. Stores the SHA-256 of the
  cookie token, the user, the household the session acts for, and expiry.
- tenant_invites: emails invited to a household, accepted on next sign-in.

No backfill: existing households have no users yet. The first allowlisted
email (AUTH_ALLOWED_EMAILS) to sign in becomes the default household's owner.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("token_hash", name="user_sessions_token_hash_key"),
    )
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])
    op.create_index("ix_user_sessions_tenant_id", "user_sessions", ["tenant_id"])

    op.create_table(
        "tenant_invites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("invited_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "email", name="tenant_invites_tenant_email_key"),
    )
    op.create_index("ix_tenant_invites_email", "tenant_invites", ["email"])


def downgrade() -> None:
    op.drop_index("ix_tenant_invites_email", table_name="tenant_invites")
    op.drop_table("tenant_invites")
    op.drop_index("ix_user_sessions_tenant_id", table_name="user_sessions")
    op.drop_index("ix_user_sessions_user_id", table_name="user_sessions")
    op.drop_table("user_sessions")
