# =============================================================================
# Copyright (c) 2026 ZombieTech LLC. All rights reserved.
#
# SPDX-License-Identifier: PolyForm-Strict-1.0.0
# See LICENSE in the project root for the full terms.
#
# Licensing inquiries: license@zombietech.biz
# =============================================================================
# ai: claude-opus-5-5 | 2026-11-19
"""
Password sign-in: register (verified by email), sign in, forgot/reset, and
set/change/remove from Settings.

Public routes never reveal whether an address has an account: registration
and "forgot password" always answer 202, and an unknown address fails sign-in
exactly like a wrong password.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.database import (
    AUTH_METHOD_PASSWORD, AuthContext, get_current_auth, get_request_session, require_app_origin,
    require_recent_auth,
)
from app.routes.auth_common import finish_sign_in, get_sign_in_session, send_account_email
from app.schemas import ForgotPasswordRequest, PasswordLoginRequest, PasswordRequest, RegisterRequest, ResetPasswordRequest, TokenRequest
from app.services.passwords import WeakPasswordError
from app.services.sessions import SessionService
from app.services.sign_in_methods import (
    InvalidCredentialsError, InvalidTokenError, LastMethodError, MethodNotFoundError, PasswordService,
    ThrottledError, UnverifiedEmailError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

INVALID_CREDENTIALS = "invalid_credentials"


def _weak(exc: WeakPasswordError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"weak_password:{exc.reason}")


def _throttled(exc: ThrottledError) -> HTTPException:
    return HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        detail="too_many_attempts",
        headers={"Retry-After": str(exc.retry_after_seconds)},
    )


# ── public ────────────────────────────────────────────────────────────────────

@router.post("/password/login", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def password_login(body: PasswordLoginRequest, db: Session = Depends(get_sign_in_session)) -> Response:
    try:
        user_id = PasswordService(db).authenticate(body.email, body.password)
    except ThrottledError as exc:
        raise _throttled(exc) from None
    except InvalidCredentialsError:
        db.commit()   # keep the recorded failure: it is what the throttle counts
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=INVALID_CREDENTIALS) from None
    except UnverifiedEmailError:
        db.commit()
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="unverified_email") from None
    return finish_sign_in(db, user_id, AUTH_METHOD_PASSWORD)


@router.post("/password/register", status_code=status.HTTP_202_ACCEPTED, response_class=Response)
def register(body: RegisterRequest, db: Session = Depends(get_sign_in_session)) -> Response:
    """Always 202, whether or not the address has an account; the email says which."""
    try:
        email = PasswordService(db).start_registration(body.email, body.password, body.display_name)
    except WeakPasswordError as exc:
        raise _weak(exc) from None
    db.commit()
    send_account_email(email)
    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.post("/password/verify", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def verify_email(body: TokenRequest, db: Session = Depends(get_sign_in_session)) -> Response:
    """Follow the verification link: create the account and sign in."""
    try:
        user_id = PasswordService(db).complete_registration(body.token)
    except InvalidTokenError:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="invalid_token") from None
    return finish_sign_in(db, user_id, AUTH_METHOD_PASSWORD)


@router.post("/password/forgot", status_code=status.HTTP_202_ACCEPTED, response_class=Response)
def forgot_password(body: ForgotPasswordRequest, db: Session = Depends(get_sign_in_session)) -> Response:
    email = PasswordService(db).start_reset(body.email)
    db.commit()
    send_account_email(email)
    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.post("/password/reset", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def reset_password(body: ResetPasswordRequest, db: Session = Depends(get_sign_in_session)) -> Response:
    """Set a new password from a reset link. Ends every session; the user signs in again."""
    try:
        PasswordService(db).complete_reset(body.token, body.password)
    except InvalidTokenError:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="invalid_token") from None
    except WeakPasswordError as exc:
        db.rollback()   # the link stays usable for a better password
        raise _weak(exc) from None
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── signed in ─────────────────────────────────────────────────────────────────

@router.post("/reauth/password", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def reauth_password(
    body: PasswordRequest,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_request_session),
) -> Response:
    try:
        PasswordService(db).authenticate_user(auth.user_id, body.password)
    except ThrottledError as exc:
        raise _throttled(exc) from None
    except (InvalidCredentialsError, UnverifiedEmailError):
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=INVALID_CREDENTIALS) from None
    SessionService(db).mark_reauthenticated(auth.session_id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/password", status_code=status.HTTP_204_NO_CONTENT, response_class=Response,
    dependencies=[Depends(require_app_origin)],
)
def set_password(
    body: PasswordRequest,
    auth: AuthContext = Depends(require_recent_auth),
    db: Session = Depends(get_request_session),
) -> Response:
    """Set or change the password. Signs out every other browser."""
    try:
        PasswordService(db).set_password(auth.user_id, body.password)
    except WeakPasswordError as exc:
        raise _weak(exc) from None
    SessionService(db).delete_all_for_user(auth.user_id, except_session_id=auth.session_id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/password", status_code=status.HTTP_204_NO_CONTENT, response_class=Response,
    dependencies=[Depends(require_app_origin)],
)
def remove_password(
    auth: AuthContext = Depends(require_recent_auth),
    db: Session = Depends(get_request_session),
) -> Response:
    try:
        PasswordService(db).remove_password(auth.user_id)
    except MethodNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not_found") from None
    except LastMethodError:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="last_method") from None
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
