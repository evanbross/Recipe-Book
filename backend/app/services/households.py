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
The signed-in household: its members and pending invites.

TenantInvite is TenantScoped, so the session's household filter applies to it
automatically. Tenant, User and TenantMembership are not (sign-in reads them
before a household is known), so every query on them here filters by the
session's household explicitly.
"""
import logging
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import Tenant, TenantInvite, TenantMembership, User, current_tenant_id
from app.services.sessions import SessionService  # ai: claude-opus-5-5 | 2026-11-19

logger = logging.getLogger(__name__)


class AlreadyMemberError(Exception):
    """The invited email already belongs to this household."""


class DuplicateInviteError(Exception):
    """This household already has a pending invite for the email."""


class CannotRemoveSelfError(Exception):
    """An owner tried to remove themselves, which would leave the household ownerless."""


@dataclass(frozen=True)
class Member:
    user_id: int
    email: str
    display_name: str | None
    role: str


@dataclass(frozen=True)
class Household:
    id: int
    name: str
    members: list[Member]
    invites: list[TenantInvite]


class HouseholdService:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._tenant_id = current_tenant_id(db)

    def overview(self) -> Household:
        tenant = self._db.get(Tenant, self._tenant_id)
        if tenant is None:
            raise LookupError(f"Household {self._tenant_id} does not exist.")
        rows = self._db.execute(
            select(User.id, User.email, User.display_name, TenantMembership.role)
            .join(TenantMembership, TenantMembership.user_id == User.id)
            .where(TenantMembership.tenant_id == self._tenant_id)
            .order_by(TenantMembership.created_at, User.id)
        ).all()
        invites = self._db.scalars(select(TenantInvite).order_by(TenantInvite.created_at)).all()
        return Household(
            id=tenant.id,
            name=tenant.name,
            members=[Member(user_id=r.id, email=r.email, display_name=r.display_name, role=r.role) for r in rows],
            invites=list(invites),
        )

    def invite(self, email: str, invited_by_user_id: int) -> TenantInvite:
        """Add a pending invite (email already normalized by the request schema). Caller commits."""
        already_member = self._db.scalar(
            select(User.id)
            .join(TenantMembership, TenantMembership.user_id == User.id)
            .where(TenantMembership.tenant_id == self._tenant_id, User.email == email)
        )
        if already_member is not None:
            raise AlreadyMemberError(email)
        invite = TenantInvite(email=email, invited_by_user_id=invited_by_user_id)
        try:
            with self._db.begin_nested():
                self._db.add(invite)
                self._db.flush()
        except IntegrityError as exc:
            raise DuplicateInviteError(email) from exc
        logger.info("Household %d invited a new email (invite %d).", self._tenant_id, invite.id)
        return invite

    def revoke_invite(self, invite_id: int) -> bool:
        """Delete a pending invite. False if this household has no such invite. Caller commits."""
        result = self._db.execute(delete(TenantInvite).where(TenantInvite.id == invite_id))
        return result.rowcount > 0

    def remove_member(self, user_id: int, acting_user_id: int) -> bool:
        """Remove a member and end their sessions in this household.
        False if they aren't a member. Caller commits."""
        if user_id == acting_user_id:
            raise CannotRemoveSelfError()
        result = self._db.execute(
            delete(TenantMembership)
            .where(TenantMembership.tenant_id == self._tenant_id, TenantMembership.user_id == user_id)
        )
        if result.rowcount == 0:
            return False
        SessionService(self._db).delete_for_member(user_id, self._tenant_id)
        logger.info("Household %d removed user %d.", self._tenant_id, user_id)
        return True
