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
Google sign-in.

The OAuth client is a Desktop client, so Google can only send the browser back
to http://localhost:<API port>, not to the app's own host. A cookie set there
wouldn't reach the app, so sign-in takes one extra hop:

1. GET  /auth/login     (app host)   -> redirect to Google
2. GET  /auth/callback  (localhost)  -> exchange the code, verify the ID token,
                                        resolve user + household, redirect with
                                        a one-time ticket (60 s, single use)
3. GET  /auth/complete  (app host)   -> trade the ticket for a session cookie

All three are public. /auth/me needs a session; /auth/logout works either way.
"""
import logging

import requests
from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import RedirectResponse
from google.auth.exceptions import TransportError
from oauthlib.oauth2.rfc6749.errors import OAuth2Error
from sqlalchemy.orm import Session

from app.config import settings
from app.database import (
    SESSION_COOKIE_NAME, AuthContext, Tenant, User, all_tenants_session, get_current_auth,
    get_request_session,
)
from app.schemas import HouseholdRef, MeOut, SignedInUser
from app.services.auth import SessionService, SignInRefusedError, SignInService
from app.services.google_oauth import (
    SIGN_IN_SCOPES, OAuthNotConfiguredError, PendingStore, build_flow, identity_from_flow,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# Google redirects straight to the API port, so this is the path without the /api prefix.
CALLBACK_PATH = f"{router.prefix}/callback"
# OAuth state -> PKCE verifier, while the user is on Google's page.
_login_states: PendingStore[str] = PendingStore(ttl_seconds=600)
# Ticket -> (user_id, tenant_id), between the localhost callback and /auth/complete.
_sign_in_tickets: PendingStore[tuple[int, int]] = PendingStore(ttl_seconds=60)


def _to_login_page(error: str) -> RedirectResponse:
    return RedirectResponse(f"{settings.public_url}/login?error={error}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/login", response_class=RedirectResponse, status_code=status.HTTP_303_SEE_OTHER)
def login() -> RedirectResponse:
    """Send the browser to Google's account chooser."""
    try:
        flow = build_flow(SIGN_IN_SCOPES, CALLBACK_PATH)
    except OAuthNotConfiguredError as exc:
        logger.error("Sign-in is not configured: %s", exc)
        return _to_login_page("not_configured")
    auth_url, state = flow.authorization_url(prompt="select_account")
    _login_states.add(state, flow.code_verifier)
    return RedirectResponse(auth_url, status_code=status.HTTP_303_SEE_OTHER)


@router.get("/callback", response_class=RedirectResponse, status_code=status.HTTP_303_SEE_OTHER)
def callback(code: str | None = None, state: str = "", error: str | None = None) -> RedirectResponse:
    """Google redirects here, on localhost. Never sets a cookie: see the module docstring."""
    if error or not code:
        logger.info("Google sign-in did not complete: %s", error or "no code")
        return _to_login_page("cancelled")
    code_verifier = _login_states.pop(state)
    if code_verifier is None:
        logger.warning("Sign-in callback with an unknown or expired state.")
        return _to_login_page("expired")

    # Talk to Google before opening a DB session, so no pooled connection waits on it.
    try:
        flow = build_flow(SIGN_IN_SCOPES, CALLBACK_PATH)
        flow.code_verifier = code_verifier
        flow.fetch_token(code=code)
        identity = identity_from_flow(flow)
    except (OAuthNotConfiguredError, OAuth2Error, requests.RequestException, TransportError, ValueError) as exc:
        logger.warning("Google sign-in failed: %s", exc)
        return _to_login_page("google_error")

    with all_tenants_session() as db:
        try:
            user_id, tenant_id = SignInService(db).sign_in(identity)
        except SignInRefusedError as exc:
            db.rollback()
            logger.info("Sign-in refused (%s).", exc.reason)
            return _to_login_page(exc.reason)
        db.commit()

    ticket = _sign_in_tickets.put((user_id, tenant_id))
    return RedirectResponse(
        f"{settings.public_url}{settings.api_public_prefix}/auth/complete?ticket={ticket}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/complete", response_class=RedirectResponse, status_code=status.HTTP_303_SEE_OTHER)
def complete(ticket: str = "", db: Session = Depends(get_request_session)) -> RedirectResponse:
    """Trade a sign-in ticket for a session cookie on the app's own host."""
    signed_in = _sign_in_tickets.pop(ticket)
    if signed_in is None:
        return _to_login_page("expired")
    user_id, tenant_id = signed_in
    token = SessionService(db).create(user_id, tenant_id)
    db.commit()

    response = RedirectResponse(f"{settings.public_url}/", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=settings.session_lifetime_days * 86400,
        path="/",
        httponly=True,
        samesite="lax",
        secure=settings.public_url.startswith("https://"),
    )
    return response


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
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, db: Session = Depends(get_request_session)) -> Response:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        SessionService(db).delete(token)
        db.commit()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/", httponly=True, samesite="lax")
    return response
