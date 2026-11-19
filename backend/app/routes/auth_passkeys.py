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
Passkeys (WebAuthn). Every ceremony is two calls: /options returns a flow id
and the options for @simplewebauthn/browser, /verify takes the flow id and what
the browser's authenticator returned.

- sign-in:  /auth/passkeys/login/*     public; no username, the passkey names the user
- re-auth:  /auth/reauth/passkey/*     signed in; only the session user's passkeys
- manage:   /auth/passkeys/register/*, PATCH/DELETE /auth/passkeys/{id}
"""
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.database import (
    AUTH_METHOD_PASSKEY, AuthContext, User, get_current_auth, get_request_session, require_app_origin,
    require_recent_auth,
)
from app.routes.auth_common import finish_sign_in, get_sign_in_session
from app.schemas import (
    PasskeyOptionsOut, PasskeyOut, PasskeyRegisterRequest, PasskeyRenameRequest, PasskeyVerifyRequest,
)
from app.services.sessions import SessionService
from app.services.sign_in_methods import (
    InvalidCredentialsError, LastMethodError, MethodNotFoundError, PasskeyService,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _invalid(detail: str = "invalid_credentials") -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail=detail)


# ── sign-in (public) ──────────────────────────────────────────────────────────

@router.post("/passkeys/login/options", response_model=PasskeyOptionsOut, status_code=status.HTTP_200_OK)
def passkey_login_options(db: Session = Depends(get_sign_in_session)) -> PasskeyOptionsOut:
    flow_id, options = PasskeyService(db).authentication_options(user_id=None)
    return PasskeyOptionsOut(flow_id=flow_id, options=options)


@router.post("/passkeys/login/verify", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def passkey_login_verify(body: PasskeyVerifyRequest, db: Session = Depends(get_sign_in_session)) -> Response:
    try:
        user_id = PasskeyService(db).authenticate(body.flow_id, body.credential, expected_user_id=None)
    except InvalidCredentialsError:
        db.rollback()
        raise _invalid() from None
    return finish_sign_in(db, user_id, AUTH_METHOD_PASSKEY)


# ── re-auth (signed in) ───────────────────────────────────────────────────────

@router.post("/reauth/passkey/options", response_model=PasskeyOptionsOut, status_code=status.HTTP_200_OK)
def reauth_passkey_options(
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_request_session),
) -> PasskeyOptionsOut:
    flow_id, options = PasskeyService(db).authentication_options(user_id=auth.user_id)
    return PasskeyOptionsOut(flow_id=flow_id, options=options)


@router.post("/reauth/passkey/verify", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def reauth_passkey_verify(
    body: PasskeyVerifyRequest,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_request_session),
) -> Response:
    try:
        PasskeyService(db).authenticate(body.flow_id, body.credential, expected_user_id=auth.user_id)
    except InvalidCredentialsError:
        db.rollback()
        raise _invalid() from None
    SessionService(db).mark_reauthenticated(auth.session_id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── managing (signed in, recently re-authenticated, from the app itself) ──────

@router.post(
    "/passkeys/register/options", response_model=PasskeyOptionsOut, status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_app_origin)],
)
def passkey_register_options(
    auth: AuthContext = Depends(require_recent_auth),
    db: Session = Depends(get_request_session),
) -> PasskeyOptionsOut:
    user = db.get(User, auth.user_id)
    if user is None:
        raise LookupError("Signed-in user disappeared.")
    flow_id, options = PasskeyService(db).registration_options(user)
    db.commit()   # keeps a newly created webauthn_user_handle
    return PasskeyOptionsOut(flow_id=flow_id, options=options)


@router.post(
    "/passkeys/register/verify", response_model=PasskeyOut, status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_app_origin)],
)
def passkey_register_verify(
    body: PasskeyRegisterRequest,
    auth: AuthContext = Depends(require_recent_auth),
    db: Session = Depends(get_request_session),
) -> PasskeyOut:
    try:
        row = PasskeyService(db).register(auth.user_id, body.flow_id, body.credential, body.name)
    except InvalidCredentialsError:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="invalid_credential") from None
    out = PasskeyOut.model_validate(row)
    db.commit()
    return out


@router.patch(
    "/passkeys/{passkey_id}", response_model=PasskeyOut, status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_app_origin)],
)
def rename_passkey(
    passkey_id: int,
    body: PasskeyRenameRequest,
    auth: AuthContext = Depends(require_recent_auth),
    db: Session = Depends(get_request_session),
) -> PasskeyOut:
    try:
        row = PasskeyService(db).rename(auth.user_id, passkey_id, body.name)
    except MethodNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not_found") from None
    out = PasskeyOut.model_validate(row)
    db.commit()
    return out


@router.delete(
    "/passkeys/{passkey_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response,
    dependencies=[Depends(require_app_origin)],
)
def remove_passkey(
    passkey_id: int,
    auth: AuthContext = Depends(require_recent_auth),
    db: Session = Depends(get_request_session),
) -> Response:
    try:
        PasskeyService(db).remove(auth.user_id, passkey_id)
    except MethodNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not_found") from None
    except LastMethodError:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="last_method") from None
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
