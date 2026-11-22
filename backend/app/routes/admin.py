# =============================================================================
# Copyright (c) 2026 ZombieTech LLC. All rights reserved.
#
# SPDX-License-Identifier: PolyForm-Strict-1.0.0
# See LICENSE in the project root for the full terms.
#
# Licensing inquiries: license@zombietech.biz
# =============================================================================
"""Server-administrator endpoints for global infrastructure settings."""
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session
from zt_common.smtp import SmtpDeliveryError, send_email

from app.database import (
    AuthContext, User, get_request_session, require_admin, require_app_origin, require_recent_admin,
)
from app.schemas import SmtpSettingsOut, SmtpSettingsUpdate
from app.services.system_settings import SystemSmtpSettings

router = APIRouter(prefix="/admin", tags=["admin"])


# ai: gpt-5 | 2026-11-21
@router.get("/smtp", response_model=SmtpSettingsOut)
def get_smtp_settings(
    _auth: AuthContext = Depends(require_admin),
    db: Session = Depends(get_request_session),
) -> SmtpSettingsOut:
    return SmtpSettingsOut.model_validate(SystemSmtpSettings(db).view(), from_attributes=True)


# ai: gpt-5 | 2026-11-21
@router.put(
    "/smtp", response_model=SmtpSettingsOut,
    dependencies=[Depends(require_app_origin)],
)
def update_smtp_settings(
    body: SmtpSettingsUpdate,
    _auth: AuthContext = Depends(require_recent_admin),
    db: Session = Depends(get_request_session),
) -> SmtpSettingsOut:
    view = SystemSmtpSettings(db).save(**body.model_dump())
    db.commit()
    return SmtpSettingsOut.model_validate(view, from_attributes=True)


# ai: gpt-5 | 2026-11-21
@router.post(
    "/smtp/test", status_code=status.HTTP_204_NO_CONTENT, response_class=Response,
    dependencies=[Depends(require_app_origin)],
)
def test_smtp_settings(
    auth: AuthContext = Depends(require_recent_admin),
    db: Session = Depends(get_request_session),
) -> Response:
    user = db.get(User, auth.user_id)
    if user is None:
        raise LookupError("Signed-in administrator disappeared.")
    try:
        send_email(
            SystemSmtpSettings(db).effective_config(), to=user.email,
            subject="RecipeBox SMTP test", body_text="Your RecipeBox outgoing mail configuration works.",
        )
    except SmtpDeliveryError:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="email_failed") from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)
