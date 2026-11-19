# =============================================================================
# Copyright (c) 2026 ZombieTech LLC. All rights reserved.
#
# SPDX-License-Identifier: PolyForm-Strict-1.0.0
# See LICENSE in the project root for the full terms.
#
# Licensing inquiries: license@zombietech.biz
# =============================================================================
# ai: claude-opus-5-5 | 2026-11-19
"""Pieces the sign-in route modules (auth, auth_password, auth_passkeys) share."""
import logging
from collections.abc import Iterator

from fastapi import HTTPException, Response, status
from sqlalchemy.orm import Session
from zt_common.smtp import SmtpDeliveryError

from app.config import settings
from app.database import SESSION_COOKIE_NAME, User, all_tenants_session
from app.services.account_email import AccountEmailService, EmailToSend
from app.services.auth import SignInRefusedError, SignInService
from app.services.sessions import SessionService

logger = logging.getLogger(__name__)

EMAIL_FAILED = "email_failed"


# ai: claude-opus-5-5 | 2026-11-19
def get_sign_in_session() -> Iterator[Session]:
    """FastAPI dependency for the public sign-in routes: a session that may read
    across households, because a sign-in accepts invites from any of them."""
    with all_tenants_session() as db:
        yield db


# ai: claude-opus-5-5 | 2026-11-19
def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=settings.session_lifetime_days * 86400,
        path="/",
        httponly=True,
        samesite="lax",
        secure=settings.public_url.startswith("https://"),
    )


# ai: claude-opus-5-5 | 2026-11-19
def finish_sign_in(db: Session, user_id: int, auth_method: str) -> Response:
    """The user proved who they are: pick the household, start a session, commit,
    and answer 204 with the cookie. A user with no household gets 403 not_invited,
    and whatever the sign-in already created (e.g. a newly verified account) stays."""
    user = db.get(User, user_id)
    if user is None:
        raise LookupError(f"User {user_id} vanished during sign-in.")
    try:
        tenant_id = SignInService(db).resolve_household(user, user.email)
    except SignInRefusedError as exc:
        db.commit()
        logger.info("Sign-in of user %d refused (%s).", user_id, exc.reason)
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=exc.reason) from None
    token = SessionService(db).create(user_id, tenant_id, auth_method)
    db.commit()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    set_session_cookie(response, token)
    return response


# ai: claude-opus-5-5 | 2026-11-19
def send_account_email(email: EmailToSend | None) -> None:
    """Send after the caller has committed and is done with its DB work: a send
    can take the full SMTP timeout. None means the service decided not to send."""
    if email is None:
        return
    try:
        AccountEmailService().send(email)
    except SmtpDeliveryError:
        # zt_common logged the relay and reason; the client only learns it failed.
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=EMAIL_FAILED) from None
