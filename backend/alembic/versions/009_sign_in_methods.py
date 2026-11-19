# =============================================================================
# Copyright (c) 2026 ZombieTech LLC. All rights reserved.
#
# SPDX-License-Identifier: PolyForm-Strict-1.0.0
# See LICENSE in the project root for the full terms.
#
# Licensing inquiries: license@zombietech.biz
# =============================================================================
# ai: claude-opus-5-5 | 2026-11-19
"""Sign-in methods: passwords, passkeys and linked Google accounts.

- users: email_verified_at (backfilled: every existing user came through
  Google, which verified the address) and webauthn_user_handle.
- user_identities: outside accounts by the provider's stable subject id.
  Existing Google users have none yet; they are adopted on their next sign-in.
- password_credentials, webauthn_credentials: the other two methods.
- email_tokens: single-use verification and password-reset links.
- login_attempts: failed-password throttle.
- user_sessions: auth_method and authenticated_at (existing sessions are
  Google sessions; the server default backfills both).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("webauthn_user_handle", sa.LargeBinary(), nullable=True))
    op.create_unique_constraint("users_webauthn_user_handle_key", "users", ["webauthn_user_handle"])
    op.execute("UPDATE users SET email_verified_at = created_at AT TIME ZONE 'UTC'")

    op.create_table(
        "user_identities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("provider", "subject", name="user_identities_provider_subject_key"),
    )
    op.create_index("ix_user_identities_user_id", "user_identities", ["user_id"])

    op.create_table(
        "password_credentials",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "webauthn_credentials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("credential_id", sa.LargeBinary(), nullable=False),
        sa.Column("public_key", sa.LargeBinary(), nullable=False),
        sa.Column("sign_count", sa.BigInteger(), nullable=False),
        sa.Column("transports", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("backed_up", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("credential_id", name="webauthn_credentials_credential_id_key"),
    )
    op.create_index("ix_webauthn_credentials_user_id", "webauthn_credentials", ["user_id"])

    op.create_table(
        "email_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("purpose", sa.String(20), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("display_name", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("token_hash", name="email_tokens_token_hash_key"),
    )
    op.create_index("ix_email_tokens_email", "email_tokens", ["email"])

    op.create_table(
        "login_attempts",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("succeeded", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_login_attempts_email_created_at", "login_attempts", ["email", "created_at"])

    op.add_column(
        "user_sessions",
        sa.Column("auth_method", sa.String(20), nullable=False, server_default="google"),
    )
    op.add_column(
        "user_sessions",
        sa.Column("authenticated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_column("user_sessions", "authenticated_at")
    op.drop_column("user_sessions", "auth_method")
    op.drop_index("ix_login_attempts_email_created_at", table_name="login_attempts")
    op.drop_table("login_attempts")
    op.drop_index("ix_email_tokens_email", table_name="email_tokens")
    op.drop_table("email_tokens")
    op.drop_index("ix_webauthn_credentials_user_id", table_name="webauthn_credentials")
    op.drop_table("webauthn_credentials")
    op.drop_table("password_credentials")
    op.drop_index("ix_user_identities_user_id", table_name="user_identities")
    op.drop_table("user_identities")
    op.drop_constraint("users_webauthn_user_handle_key", "users", type_="unique")
    op.drop_column("users", "webauthn_user_handle")
    op.drop_column("users", "email_verified_at")
