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
Who may sign in, and which household a sign-in acts for.

Every method (Google, password, passkey) first establishes *who* the user is,
then shares one household decision (SignInService.resolve_household). A user
gets in when they have at least one household membership after this sign-in.
Memberships come from:

- pending invites for that email (all accepted at every sign-in), or
- AUTH_ALLOWED_EMAILS: an allowlisted email with no household joins the
  default household; the first such user becomes its owner.

Once a membership exists it is the authority: removing an email from the
allowlist doesn't lock out a user who already belongs to a household.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import (
    ROLE_MEMBER, ROLE_OWNER, TenantInvite, TenantMembership, User, resolve_default_tenant_id,
)
from app.services.google_oauth import GoogleIdentity
from app.services.sign_in_methods import IdentityService, LinkRequiredError

logger = logging.getLogger(__name__)


class SignInRefusedError(Exception):
    """We know who the user is, but they may not use this app (yet).

    `reason` is a short code the login page shows a message for.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class SignInService:
    """Resolves a signed-in user to a household.

    Needs a session opened with all_tenants_session() (or an unbound request
    session): invites for one email can belong to several households, so the
    lookup deliberately spans them.
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    # ai: claude-opus-5-5 | 2026-11-19
    def sign_in(self, identity: GoogleIdentity) -> tuple[int, int]:
        """Google: return (user_id, tenant_id) for the household this sign-in acts for.
        Flushes but doesn't commit; the caller commits."""
        if not identity.email_verified:
            raise SignInRefusedError("unverified_email")
        try:
            user = IdentityService(self._db).user_for_google(identity)
        except LinkRequiredError:
            raise SignInRefusedError("link_required") from None
        if user is None:
            if not self._may_join(identity.email):
                raise SignInRefusedError("not_invited")
            user = self._create_google_user(identity)
        elif identity.name and not user.display_name:
            user.display_name = identity.name
        return user.id, self.resolve_household(user, identity.email)

    # ai: claude-opus-5-5 | 2026-11-19
    def resolve_household(self, user: User, email_for_invites: str) -> int:
        """Accept pending invites for the email, place an allowlisted newcomer in the
        default household, and return the household this sign-in acts for.
        Raises SignInRefusedError("not_invited") if the user belongs to none."""
        invites = self._db.scalars(select(TenantInvite).where(TenantInvite.email == email_for_invites)).all()
        member_of = set(self._db.scalars(
            select(TenantMembership.tenant_id).where(TenantMembership.user_id == user.id)
        ))
        for invite in invites:
            if invite.tenant_id not in member_of:
                self._db.add(TenantMembership(tenant_id=invite.tenant_id, user_id=user.id, role=ROLE_MEMBER))
                member_of.add(invite.tenant_id)
                logger.info("User %d accepted the invite to household %d.", user.id, invite.tenant_id)
            self._db.delete(invite)

        if not member_of and email_for_invites in settings.allowed_emails:
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
            # A user removed from every household, with no invite and not allowlisted.
            raise SignInRefusedError("not_invited")
        return tenant_id

    def _may_join(self, email: str) -> bool:
        if email in settings.allowed_emails:
            return True
        return self._db.scalar(select(TenantInvite.id).where(TenantInvite.email == email).limit(1)) is not None

    # ai: claude-opus-5-5 | 2026-11-19
    def _create_google_user(self, identity: GoogleIdentity) -> User:
        # Insert and handle the unique-email race, rather than SELECT-then-INSERT
        # alone: two sign-ins for the same new account can arrive together.
        user = User(email=identity.email, display_name=identity.name, email_verified_at=datetime.now(timezone.utc))
        try:
            with self._db.begin_nested():
                self._db.add(user)
                self._db.flush()
        except IntegrityError:
            # The other sign-in won. If it was this same Google account, it has
            # stored the identity: sign in as that user. Otherwise refuse.
            existing = IdentityService(self._db).user_for_google(identity)
            if existing is None:
                raise
            return existing
        IdentityService(self._db).create_google_identity(user.id, identity)
        logger.info("Created user %d for a first sign-in.", user.id)
        return user
