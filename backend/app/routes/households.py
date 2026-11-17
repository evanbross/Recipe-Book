# =============================================================================
# Copyright (c) 2026 ZombieTech LLC. All rights reserved.
#
# SPDX-License-Identifier: PolyForm-Strict-1.0.0
# See LICENSE in the project root for the full terms.
#
# Licensing inquiries: license@zombietech.biz
# =============================================================================
# ai: claude-opus-5-5 | 2026-11-17
"""The signed-in household: members and invites. Changes are owner-only."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.database import ROLE_OWNER, AuthContext, get_current_auth, get_db
from app.schemas import HouseholdInviteOut, HouseholdOut, InviteCreate
from app.services.households import (
    AlreadyMemberError, CannotRemoveSelfError, DuplicateInviteError, HouseholdService,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/household", tags=["household"])


def require_owner(auth: AuthContext = Depends(get_current_auth)) -> AuthContext:
    if auth.role != ROLE_OWNER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the household owner can do that.")
    return auth


@router.get("", response_model=HouseholdOut)
def get_household(db: Session = Depends(get_db)) -> HouseholdOut:
    return HouseholdOut.model_validate(HouseholdService(db).overview())


@router.post("/invites", response_model=HouseholdInviteOut, status_code=status.HTTP_201_CREATED)
def create_invite(
    body: InviteCreate,
    auth: AuthContext = Depends(require_owner),
    db: Session = Depends(get_db),
) -> HouseholdInviteOut:
    try:
        invite = HouseholdService(db).invite(body.email, invited_by_user_id=auth.user_id)
    except AlreadyMemberError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That person is already in this household.")
    except DuplicateInviteError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That email has already been invited.")
    db.commit()
    db.refresh(invite)
    return HouseholdInviteOut.model_validate(invite)


@router.delete("/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_invite(
    invite_id: int,
    _auth: AuthContext = Depends(require_owner),
    db: Session = Depends(get_db),
) -> Response:
    if not HouseholdService(db).revoke_invite(invite_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found.")
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    user_id: int,
    auth: AuthContext = Depends(require_owner),
    db: Session = Depends(get_db),
) -> Response:
    try:
        removed = HouseholdService(db).remove_member(user_id, acting_user_id=auth.user_id)
    except CannotRemoveSelfError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You can't remove yourself.")
    if not removed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found.")
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
