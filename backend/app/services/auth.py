# =============================================================================
# Copyright (c) 2026 ZombieTech LLC. All rights reserved.
#
# SPDX-License-Identifier: PolyForm-Strict-1.0.0
# See LICENSE in the project root for the full terms.
#
# Licensing inquiries: license@zombietech.biz
# =============================================================================
# ai: claude-opus-5-5 | 2026-11-17
"""
Who may sign in, and sign-in sessions.

A verified Google email gets in when it has at least one household
membership after this sign-in. Memberships come from:

- pending invites for that email (all accepted at every sign-in), or
- AUTH_ALLOWED_EMAILS: an allowlisted email with no household joins the
  default household; the first such user becomes its owner.

Once a membership exists it is the authority: removing an email from the
allowlist doesn't lock out a user who already belongs to a household.
"""
import logging
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import (
    ROLE_MEMBER, ROLE_OWNER, TenantInvite, TenantMembership, User, UserSession,
    hash_session_token, resolve_default_tenant_id,
)
from app.services.google_oauth import GoogleIdentity

logger = logging.getLogger(__name__)


class SignInRefusedError(Exception):
    """Google identified the user, but they may not use this app.

    `reason` is a short code the login page shows a message for.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class SignInService:
    """Resolves a Google identity to a user and household.

    Needs a session opened with all_tenants_session(): invites for one email
    can belong to several households, so the lookup deliberately spans them.
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    def sign_in(self, identity: GoogleIdentity) -> tuple[int, int]:
        """Return (user_id, tenant_id) for the household this sign-in acts for.
        Flushes but doesn't commit; the caller commits."""
        if not identity.email_verified:
            raise SignInRefusedError("unverified_email")

        invites = self._db.scalars(select(TenantInvite).where(TenantInvite.email == identity.email)).all()
        allowlisted = identity.email in settings.allowed_emails
        user = self._db.scalar(select(User).where(User.email == identity.email))
        if user is None:
            if not invites and not allowlisted:
                raise SignInRefusedError("not_invited")
            user = self._create_user(identity)
        elif identity.name and not user.display_name:
            user.display_name = identity.name

        member_of = set(self._db.scalars(
            select(TenantMembership.tenant_id).where(TenantMembership.user_id == user.id)
        ))
        for invite in invites:
            if invite.tenant_id not in member_of:
                self._db.add(TenantMembership(tenant_id=invite.tenant_id, user_id=user.id, role=ROLE_MEMBER))
                member_of.add(invite.tenant_id)
                logger.info("User %d accepted the invite to household %d.", user.id, invite.tenant_id)
            self._db.delete(invite)

        if not member_of and allowlisted:
            default_id = resolve_default_tenant_id(self._db)
            has_owner = self._db.scalar(
                select(TenantMembership.user_id)
                .where(TenantMembership.tenant_id == default_id, TenantMembership.role == ROLE_OWNER)
                .limit(1)
            ) is not None
            role = ROLE_MEMBER if has_owner else ROLE_OWNER
            self._db.add(TenantMembership(tenant_id=default_id, user_id=user.id, role=role))
            logger.info("Allowlisted user %d joined the default household as %s.", user.id, role)

        self._db.flush()
        # The oldest membership is the household a sign-in acts for. Switching
        # between several households is not built yet.
        tenant_id = self._db.scalar(
            select(TenantMembership.tenant_id)
            .where(TenantMembership.user_id == user.id)
            .order_by(TenantMembership.created_at, TenantMembership.tenant_id)
            .limit(1)
        )
        if tenant_id is None:
            # A known user removed from every household, with no invite and not allowlisted.
            raise SignInRefusedError("not_invited")
        return user.id, tenant_id

    def _create_user(self, identity: GoogleIdentity) -> User:
        # Insert and handle the unique-email race, rather than SELECT-then-INSERT
        # alone: two sign-ins for the same new email can arrive together.
        user = User(email=identity.email, display_name=identity.name)
        try:
            with self._db.begin_nested():
                self._db.add(user)
                self._db.flush()
        except IntegrityError:
            existing = self._db.scalar(select(User).where(User.email == identity.email))
            if existing is None:
                raise
            return existing
        logger.info("Created user %d for a first sign-in.", user.id)
        return user


class SessionService:
    """Sign-in sessions: the cookie carries a random token, the table its hash."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def create(self, user_id: int, tenant_id: int) -> str:
        """Add a session and return the raw token for the cookie. The caller commits."""
        token = secrets.token_urlsafe(32)
        self._db.add(UserSession(
            token_hash=hash_session_token(token),
            user_id=user_id,
            tenant_id=tenant_id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=settings.session_lifetime_days),
        ))
        return token

    def delete(self, token: str) -> None:
        self._db.execute(delete(UserSession).where(UserSession.token_hash == hash_session_token(token)))

    def delete_for_member(self, user_id: int, tenant_id: int) -> None:
        self._db.execute(
            delete(UserSession).where(UserSession.user_id == user_id, UserSession.tenant_id == tenant_id)
        )
