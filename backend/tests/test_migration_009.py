# =============================================================================
# Copyright (c) 2026 ZombieTech LLC. All rights reserved.
#
# SPDX-License-Identifier: PolyForm-Strict-1.0.0
# See LICENSE in the project root for the full terms.
#
# Licensing inquiries: license@zombietech.biz
# =============================================================================
# ai: claude-opus-5-5 | 2026-11-19
"""Migration 009 against pre-existing users and sessions, in both directions.

Steps the shared test DB down to 008 and back. Every test leaves it at head, so
the rest of the suite is unaffected; row cleanup is db_session's job.
"""
from datetime import datetime, timezone

import pytest
from alembic import command
from sqlalchemy import inspect, text

from tests.conftest import alembic_config

_NEW_TABLES = {"user_identities", "password_credentials", "webauthn_credentials", "email_tokens", "login_attempts"}


@pytest.fixture()
def at_008(engine, db_session):
    # End db_session's open transaction first: its household lookup holds a lock
    # that would block the downgrade's ALTER/DROP TABLE forever.
    db_session.rollback()
    command.downgrade(alembic_config(), "008")
    try:
        yield engine
    finally:
        command.upgrade(alembic_config(), "head")


def _seed_google_user_with_session(conn) -> None:
    tenant_id = conn.execute(text("SELECT id FROM tenants WHERE slug = 'default'")).scalar_one()
    user_id = conn.execute(text(
        "INSERT INTO users (email, display_name, created_at) "
        "VALUES ('legacy@example.com', 'Legacy', '2026-11-17 12:00:00') RETURNING id"
    )).scalar_one()
    conn.execute(text(
        "INSERT INTO user_sessions (token_hash, user_id, tenant_id, created_at, expires_at) "
        "VALUES (:h, :u, :t, now(), now() + interval '1 day')"
    ), {"h": "a" * 64, "u": user_id, "t": tenant_id})


def test_upgrade_backfills_existing_users_and_sessions(at_008):
    with at_008.begin() as conn:
        _seed_google_user_with_session(conn)

    command.upgrade(alembic_config(), "009")

    with at_008.connect() as conn:
        verified_at = conn.execute(text("SELECT email_verified_at FROM users")).scalar_one()
        session = conn.execute(text("SELECT auth_method, authenticated_at FROM user_sessions")).one()

    # users.created_at is naive UTC; the backfill must keep the instant, not shift it.
    assert verified_at == datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
    assert session.auth_method == "google"
    assert session.authenticated_at is not None


def test_downgrade_then_upgrade_round_trips(at_008):
    command.upgrade(alembic_config(), "009")
    command.downgrade(alembic_config(), "008")

    tables = set(inspect(at_008).get_table_names())
    user_columns = {c["name"] for c in inspect(at_008).get_columns("users")}
    session_columns = {c["name"] for c in inspect(at_008).get_columns("user_sessions")}
    assert not tables & _NEW_TABLES
    assert not user_columns & {"email_verified_at", "webauthn_user_handle"}
    assert not session_columns & {"auth_method", "authenticated_at"}

    command.upgrade(alembic_config(), "009")
    assert _NEW_TABLES <= set(inspect(at_008).get_table_names())
