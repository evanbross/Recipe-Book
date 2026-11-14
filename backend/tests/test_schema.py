# =============================================================================
# Copyright (c) 2026 ZombieTech LLC. All rights reserved.
#
# SPDX-License-Identifier: PolyForm-Strict-1.0.0
# See LICENSE in the project root for the full terms.
#
# Licensing inquiries: license@zombietech.biz
# =============================================================================
# ai: claude-opus-5-5 | 2026-11-14
"""The ORM models must describe exactly the schema the Alembic chain builds."""
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from app.database import Base


def test_models_match_migrated_schema(engine):
    # `engine` is the session fixture that ran `alembic upgrade head`.
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)

    assert diff == [], f"Models and migrations disagree; add a migration: {diff}"
