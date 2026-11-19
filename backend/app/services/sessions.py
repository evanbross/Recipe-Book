# =============================================================================
# Copyright (c) 2026 ZombieTech LLC. All rights reserved.
#
# SPDX-License-Identifier: PolyForm-Strict-1.0.0
# See LICENSE in the project root for the full terms.
#
# Licensing inquiries: license@zombietech.biz
# =============================================================================
# ai: claude-opus-5-5 | 2026-11-19
"""Sign-in sessions: the cookie carries a random token, the table only its hash.

A leaf module (no imports from other services) so sign-in, household and
sign-in-method services can all use it without importing each other.
"""
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, update
from sqlalchemy.orm import Session

from app.config import settings
from app.database import UserSession, hash_session_token


# ai: claude-opus-5-5 | 2026-11-17
class SessionService:
    """Creates, re-confirms and ends sessions. Flushes nothing itself; the caller commits."""

    def __init__(self, db: Session) -> None:
        self._db = db

    # ai: claude-opus-5-5 | 2026-11-19
    def create(self, user_id: int, tenant_id: int, auth_method: str) -> str:
        """Add a session and return the raw token for the cookie."""
        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        self._db.add(UserSession(
            token_hash=hash_session_token(token),
            user_id=user_id,
            tenant_id=tenant_id,
            auth_method=auth_method,
            authenticated_at=now,
            expires_at=now + timedelta(days=settings.session_lifetime_days),
        ))
        return token

    # ai: claude-opus-5-5 | 2026-11-19
    def mark_reauthenticated(self, session_id: int) -> None:
        """The user just proved who they are again: restart the re-auth window."""
        self._db.execute(
            update(UserSession)
            .where(UserSession.id == session_id)
            .values(authenticated_at=datetime.now(timezone.utc))
        )

    def delete(self, token: str) -> None:
        self._db.execute(delete(UserSession).where(UserSession.token_hash == hash_session_token(token)))

    def delete_for_member(self, user_id: int, tenant_id: int) -> None:
        self._db.execute(
            delete(UserSession).where(UserSession.user_id == user_id, UserSession.tenant_id == tenant_id)
        )

    # ai: claude-opus-5-5 | 2026-11-19
    def delete_all_for_user(self, user_id: int, except_session_id: int | None = None) -> None:
        """Sign the user out everywhere (after a password reset), or everywhere but
        the current browser (after a password change)."""
        stmt = delete(UserSession).where(UserSession.user_id == user_id)
        if except_session_id is not None:
            stmt = stmt.where(UserSession.id != except_session_id)
        self._db.execute(stmt)
