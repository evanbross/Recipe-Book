# =============================================================================
# Copyright (c) 2026 ZombieTech LLC. All rights reserved.
#
# SPDX-License-Identifier: PolyForm-Strict-1.0.0
# See LICENSE in the project root for the full terms.
#
# Licensing inquiries: license@zombietech.biz
# =============================================================================
# ai: claude-opus-5-5 | 2026-11-19
"""Helpers shared by the sign-in method tests (test_sign_in_*.py)."""
import re
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.database import (
    PROVIDER_GOOGLE, ROLE_MEMBER, PasswordCredential, TenantMembership, User, UserIdentity, UserSession,
    current_tenant_id,
)
from app.services.google_oauth import GoogleIdentity
from app.services.passwords import PasswordHasherService

PASSWORD = "correct horse battery"
APP_ORIGIN = {"Origin": settings.public_url}


# ai: claude-opus-5-5 | 2026-11-19
def make_user(
    db_session: Session, email: str, *, password: str | None = PASSWORD, google_subject: str | None = None,
    member: bool = True,
) -> User:
    """A verified user, in the test's household unless member=False."""
    user = User(email=email, display_name=email.split("@")[0], email_verified_at=datetime.now(timezone.utc))
    db_session.add(user)
    db_session.flush()
    if password is not None:
        db_session.add(PasswordCredential(user_id=user.id, password_hash=PasswordHasherService().hash(password)))
    if google_subject is not None:
        db_session.add(UserIdentity(user_id=user.id, provider=PROVIDER_GOOGLE, subject=google_subject, email=email))
    if member:
        db_session.add(TenantMembership(tenant_id=current_tenant_id(db_session), user_id=user.id, role=ROLE_MEMBER))
    db_session.commit()
    return user


# ai: claude-opus-5-5 | 2026-11-19
def password_login(client, email: str, password: str = PASSWORD):
    return client.post("/auth/password/login", json={"email": email, "password": password})


# ai: claude-opus-5-5 | 2026-11-19
def sessions_of(db_session: Session, user_id: int) -> list[UserSession]:
    db_session.expire_all()
    return list(db_session.scalars(select(UserSession).where(UserSession.user_id == user_id).order_by(UserSession.id)))


# ai: claude-opus-5-5 | 2026-11-19
def age_sessions(db_session: Session, user_id: int, minutes: int) -> None:
    """Pretend the user's sessions last proved who they are `minutes` ago."""
    db_session.execute(
        update(UserSession)
        .where(UserSession.user_id == user_id)
        .values(authenticated_at=datetime.now(timezone.utc) - timedelta(minutes=minutes))
    )
    db_session.commit()


# ai: claude-opus-5-5 | 2026-11-19
def token_from(message: EmailMessage) -> str:
    """The token in the one app link an account email carries."""
    body = message.get_content()
    links = re.findall(re.escape(settings.public_url) + r"/[a-z-]+\?token=\S+", body)
    assert len(links) == 1, body
    return parse_qs(urlparse(links[0]).query)["token"][0]


# ai: claude-opus-5-5 | 2026-11-19
def google_callback(client, start_path: str, identity: GoogleIdentity) -> tuple[dict[str, list[str]], str]:
    """Start a Google flow at start_path, then play Google's redirect back to the
    localhost callback as `identity`. Returns (the authorization URL's query
    parameters, where the callback redirected). Only Google itself is faked."""
    res = client.get(start_path, follow_redirects=False)
    assert res.status_code == 303, res.text
    google = parse_qs(urlparse(res.headers["location"]).query)
    with patch("google_auth_oauthlib.flow.Flow.fetch_token"), \
            patch("app.routes.auth.identity_from_flow", return_value=identity):
        res = client.get(f"/auth/callback?code=abc&state={google['state'][0]}", follow_redirects=False)
    assert res.status_code == 303
    return google, res.headers["location"]


# ai: claude-opus-5-5 | 2026-11-19
def follow_ticket(client, callback_location: str) -> str:
    """Take the callback's redirect to /auth/complete; return where that sends the browser."""
    assert callback_location.startswith(f"{settings.public_url}{settings.api_public_prefix}/auth/complete?ticket=")
    ticket = parse_qs(urlparse(callback_location).query)["ticket"][0]
    res = client.get(f"/auth/complete?ticket={ticket}", follow_redirects=False)
    assert res.status_code == 303
    return res.headers["location"]
