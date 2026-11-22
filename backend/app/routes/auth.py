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
Google (sign-in, linking, re-auth), the signed-in user, and the sign-in methods
overview. Passwords and passkeys live in auth_password.py / auth_passkeys.py.

The OAuth client is a Desktop client, so Google can only send the browser back
to http://localhost:<API port>, not to the app's own host. A cookie set there
wouldn't reach the app, so every Google flow takes one extra hop:

1. GET  /auth/login | /auth/google/link | /auth/reauth/google   (app host) -> Google
2. GET  /auth/callback  (localhost)  -> exchange the code, verify the ID token,
                                        redirect with a one-time ticket (60 s, single use)
3. GET  /auth/complete  (app host)   -> sign in: trade the ticket for a session cookie;
                                        link / re-auth: check the cookie's session is the
                                        one that started the flow, then act on it

The OAuth state records which of the three flows it is, and for linking and
re-auth the user and session that started it. Link and re-auth write nothing
until step 3, where the cookie proves the same browser is finishing the flow.
"""
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

import requests
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from google.auth.exceptions import TransportError
from oauthlib.oauth2.rfc6749.errors import OAuth2Error
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import (
    AUTH_METHOD_GOOGLE, PROVIDER_GOOGLE, REAUTH_REQUIRED, SESSION_COOKIE_NAME, AuthContext, NotSignedInError, Tenant, User,
    UserIdentity, all_tenants_session, get_current_auth, get_request_session, require_app_origin,
    require_recent_auth,
)
from app.routes.auth_common import set_session_cookie
from app.schemas import HouseholdRef, MeOut, SignedInUser, SignInMethodsOut
from app.services.auth import SignInRefusedError, SignInService
from app.services.google_oauth import (
    SIGN_IN_SCOPES, GoogleIdentity, OAuthNotConfiguredError, PendingStore, build_flow, identity_from_flow,
)
from app.services.sessions import SessionService
from app.services.sign_in_methods import (
    AlreadyLinkedError, IdentityService, LastMethodError, MethodNotFoundError, MethodSummary,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# Google redirects straight to the API port, so this is the path without the /api prefix.
CALLBACK_PATH = f"{router.prefix}/callback"
# Re-auth only counts if the user typed their Google password this recently.
REAUTH_MAX_AGE_SECONDS = 300

GooglePurpose = Literal["sign_in", "link", "reauth"]


# ai: claude-opus-5-5 | 2026-11-19
@dataclass(frozen=True)
class GoogleFlowState:
    """What /auth/callback needs to know about a flow while the user is on Google's page."""
    code_verifier: str
    purpose: GooglePurpose
    user_id: int | None = None      # link / reauth: who started it
    session_id: int | None = None   # link / reauth: from which session


# ai: claude-opus-5-5 | 2026-11-19
@dataclass(frozen=True)
class TicketPayload:
    """What /auth/complete acts on: a sign-in's user and household, or a verified
    Google identity for the link / re-auth started by session_id."""
    purpose: GooglePurpose
    user_id: int
    tenant_id: int | None = None
    session_id: int | None = None
    identity: GoogleIdentity | None = None


# OAuth state -> flow, while the user is on Google's page.
_login_states: PendingStore[GoogleFlowState] = PendingStore(ttl_seconds=600)
# Ticket -> payload, between the localhost callback and /auth/complete.
_sign_in_tickets: PendingStore[TicketPayload] = PendingStore(ttl_seconds=60)


def _to_login_page(error: str) -> RedirectResponse:
    return RedirectResponse(f"{settings.public_url}/login?error={error}", status_code=status.HTTP_303_SEE_OTHER)


# ai: claude-opus-5-5 | 2026-11-19
def _to_settings(query: str) -> RedirectResponse:
    return RedirectResponse(f"{settings.public_url}/settings?{query}", status_code=status.HTTP_303_SEE_OTHER)


# ai: claude-opus-5-5 | 2026-11-19
def _start_google(
    purpose: GooglePurpose, on_error: RedirectResponse, *,
    user_id: int | None = None, session_id: int | None = None, **auth_params: str,
) -> RedirectResponse:
    """Redirect to Google, remembering the flow under the OAuth state Google echoes back."""
    try:
        flow = build_flow(SIGN_IN_SCOPES, CALLBACK_PATH)
    except OAuthNotConfiguredError as exc:
        logger.error("Google sign-in is not configured: %s", exc)
        return on_error
    auth_url, oauth_state = flow.authorization_url(**auth_params)
    _login_states.add(oauth_state, GoogleFlowState(
        code_verifier=flow.code_verifier, purpose=purpose, user_id=user_id, session_id=session_id,
    ))
    return RedirectResponse(auth_url, status_code=status.HTTP_303_SEE_OTHER)


@router.get("/login", response_class=RedirectResponse, status_code=status.HTTP_303_SEE_OTHER)
def login() -> RedirectResponse:
    """Send the browser to Google's account chooser."""
    return _start_google("sign_in", _to_login_page("not_configured"), prompt="select_account")


# ai: claude-opus-5-5 | 2026-11-19
@router.get("/google/link", response_class=RedirectResponse, status_code=status.HTTP_303_SEE_OTHER)
def google_link(auth: AuthContext = Depends(get_current_auth)) -> RedirectResponse:
    """Settings: link another Google account. A browser navigation, so a stale
    re-auth redirects back to Settings instead of answering 403 JSON."""
    if datetime.now(timezone.utc) > auth.reauth_valid_until:
        return _to_settings(f"error={REAUTH_REQUIRED}")
    return _start_google(
        "link", _to_settings("error=not_configured"),
        user_id=auth.user_id, session_id=auth.session_id, prompt="select_account",
    )


# ai: claude-opus-5-5 | 2026-11-19
@router.get("/reauth/google", response_class=RedirectResponse, status_code=status.HTTP_303_SEE_OTHER)
def reauth_google(auth: AuthContext = Depends(get_current_auth)) -> RedirectResponse:
    """Prove it's you again with Google: max_age=0 makes Google ask for the password."""
    return _start_google(
        "reauth", _to_settings("error=not_configured"),
        user_id=auth.user_id, session_id=auth.session_id, prompt="login", max_age="0",
    )


@router.get("/callback", response_class=RedirectResponse, status_code=status.HTTP_303_SEE_OTHER)
def callback(code: str | None = None, state: str = "", error: str | None = None) -> RedirectResponse:
    """Google redirects here, on localhost. Never sets a cookie: see the module docstring."""
    flow_state = _login_states.pop(state)
    if flow_state is None:
        logger.warning("Google callback with an unknown or expired state.")
        return _to_login_page("expired")
    fail = _to_login_page if flow_state.purpose == "sign_in" else (lambda e: _to_settings(f"error={e}"))
    if error or not code:
        logger.info("Google flow did not complete: %s", error or "no code")
        return fail("cancelled")

    # Talk to Google before opening a DB session, so no pooled connection waits on it.
    try:
        flow = build_flow(SIGN_IN_SCOPES, CALLBACK_PATH)
        flow.code_verifier = flow_state.code_verifier
        flow.fetch_token(code=code)
        identity = identity_from_flow(flow)
    except (OAuthNotConfiguredError, OAuth2Error, requests.RequestException, TransportError, ValueError) as exc:
        logger.warning("Google sign-in failed: %s", exc)
        return fail("google_error")

    if flow_state.purpose == "sign_in":
        with all_tenants_session() as db:
            try:
                user_id, tenant_id = SignInService(db).sign_in(identity)
            except SignInRefusedError as exc:
                db.rollback()
                logger.info("Sign-in refused (%s).", exc.reason)
                return _to_login_page(exc.reason)
            db.commit()
        payload = TicketPayload(purpose="sign_in", user_id=user_id, tenant_id=tenant_id)
    else:
        if flow_state.user_id is None or flow_state.session_id is None:
            raise LookupError("Link/re-auth flow state without a user or session.")
        if flow_state.purpose == "reauth":
            refusal = _reauth_refusal(flow_state.user_id, identity)
            if refusal:
                return fail(refusal)
        payload = TicketPayload(
            purpose=flow_state.purpose, user_id=flow_state.user_id,
            session_id=flow_state.session_id, identity=identity,
        )

    ticket = _sign_in_tickets.put(payload)
    return RedirectResponse(
        f"{settings.public_url}{settings.api_public_prefix}/auth/complete?ticket={ticket}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# ai: claude-opus-5-5 | 2026-11-19
def _reauth_refusal(user_id: int, identity: GoogleIdentity) -> str | None:
    """Why a Google re-auth doesn't count, or None if it does: it must be one of
    the user's own linked Google accounts, and the password typed just now."""
    with all_tenants_session() as db:
        linked = db.scalar(
            select(UserIdentity.id).where(
                UserIdentity.user_id == user_id,
                UserIdentity.provider == PROVIDER_GOOGLE,
                UserIdentity.subject == identity.subject,
            )
        )
    if linked is None:
        logger.info("Google re-auth by an account not linked to user %d.", user_id)
        return "reauth_wrong_account"
    if identity.auth_time is None or time.time() - identity.auth_time > REAUTH_MAX_AGE_SECONDS:
        logger.info("Google re-auth for user %d without a fresh auth_time (%s).", user_id, identity.auth_time)
        return "reauth_failed"
    return None


@router.get("/complete", response_class=RedirectResponse, status_code=status.HTTP_303_SEE_OTHER)
def complete(request: Request, ticket: str = "", db: Session = Depends(get_request_session)) -> RedirectResponse:
    """Finish a Google flow on the app's own host, where the session cookie lives."""
    payload = _sign_in_tickets.pop(ticket)
    if payload is None:
        return _to_login_page("expired")

    if payload.purpose == "sign_in":
        if payload.tenant_id is None:
            raise LookupError("Sign-in ticket without a household.")
        token = SessionService(db).create(payload.user_id, payload.tenant_id, AUTH_METHOD_GOOGLE)
        db.commit()
        response = RedirectResponse(f"{settings.public_url}/", status_code=status.HTTP_303_SEE_OTHER)
        set_session_cookie(response, token)
        return response

    # Link / re-auth: only the session that started the flow may finish it, so a
    # ticket URL leaked to another browser (or user) is worthless there.
    try:
        auth = get_current_auth(request, db)
    except NotSignedInError:
        return _to_login_page("expired")
    if auth.session_id != payload.session_id or auth.user_id != payload.user_id or payload.identity is None:
        logger.warning("Google %s ticket presented by a different session; refused.", payload.purpose)
        return _to_settings("error=expired")

    if payload.purpose == "reauth":
        SessionService(db).mark_reauthenticated(auth.session_id)
        db.commit()
        return _to_settings("reauth=ok")

    try:
        IdentityService(db).link_google(auth.user_id, payload.identity)
    except AlreadyLinkedError:
        db.rollback()
        return _to_settings("error=already_linked")
    db.commit()
    logger.info("User %d linked a Google account.", auth.user_id)
    return _to_settings("linked=google")


@router.get("/me", response_model=MeOut)
def me(
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_request_session),
) -> MeOut:
    user = db.get(User, auth.user_id)
    tenant = db.get(Tenant, auth.tenant_id)
    if user is None or tenant is None:
        # Both are guaranteed by the session lookup's join; a miss means a concurrent delete.
        raise LookupError("Signed-in user or household disappeared.")
    return MeOut(
        user=SignedInUser(id=user.id, email=user.email, display_name=user.display_name),
        household=HouseholdRef(id=tenant.id, name=tenant.name),
        role=auth.role,
        is_admin=auth.is_admin,
    )


# ai: claude-opus-5-5 | 2026-11-19
@router.get("/methods", response_model=SignInMethodsOut)
def sign_in_methods(
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_request_session),
) -> SignInMethodsOut:
    return MethodSummary(db).methods_for(auth.user_id, auth.reauth_valid_until)


# ai: claude-opus-5-5 | 2026-11-19
@router.delete(
    "/identities/{identity_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response,
    dependencies=[Depends(require_app_origin)],
)
def unlink_identity(
    identity_id: int,
    auth: AuthContext = Depends(require_recent_auth),
    db: Session = Depends(get_request_session),
) -> Response:
    try:
        IdentityService(db).unlink(auth.user_id, identity_id)
    except MethodNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not_found") from None
    except LastMethodError:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="last_method") from None
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, db: Session = Depends(get_request_session)) -> Response:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        SessionService(db).delete(token)
        db.commit()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/", httponly=True, samesite="lax")
    return response
