# =============================================================================
# Copyright (c) 2026 ZombieTech LLC. All rights reserved.
#
# SPDX-License-Identifier: PolyForm-Strict-1.0.0
# See LICENSE in the project root for the full terms.
#
# Licensing inquiries: license@zombietech.biz
# =============================================================================
# ai: claude-opus-5-5 | 2026-11-19
"""Google accounts as identities: stored by subject, adopted legacy users,
linking from Settings, and Google re-auth. Only Google itself is faked."""
import time

import pytest
from sqlalchemy import func, select

from app.config import settings
from app.database import SESSION_COOKIE_NAME, User, UserIdentity
from app.services.google_oauth import GoogleIdentity
from tests.sign_in_helpers import (
    age_sessions, follow_ticket, google_callback, make_user, password_login, sessions_of,
)

API_PORT = 54321


@pytest.fixture(autouse=True)
def _oauth_config(monkeypatch, fake_google_credentials):
    monkeypatch.setattr(settings, "api_port", API_PORT)
    monkeypatch.setattr(settings, "auth_allowed_emails", "new@example.com,legacy@example.com")


def _google(email: str, subject: str, *, auth_time: int | None = None) -> GoogleIdentity:
    return GoogleIdentity(subject=subject, email=email, email_verified=True, name=None, auth_time=auth_time)


def _identities(db_session) -> list[tuple[int, str, str]]:
    db_session.expire_all()
    return [(i.user_id, i.subject, i.email) for i in db_session.scalars(select(UserIdentity).order_by(UserIdentity.id))]


# ── sign-in ───────────────────────────────────────────────────────────────────

def test_new_google_user_is_stored_by_subject(anon_client, db_session):
    _, location = google_callback(anon_client, "/auth/login", _google("new@example.com", "g-1"))
    assert follow_ticket(anon_client, location) == f"{settings.public_url}/"

    user = db_session.scalar(select(User).where(User.email == "new@example.com"))
    assert _identities(db_session) == [(user.id, "g-1", "new@example.com")]
    assert user.email_verified_at is not None
    assert [s.auth_method for s in sessions_of(db_session, user.id)] == ["google"]


def test_returning_google_user_is_found_by_subject_even_after_an_email_change(anon_client, db_session):
    user = make_user(db_session, "old-address@example.com", password=None, google_subject="g-1")
    _, location = google_callback(anon_client, "/auth/login", _google("renamed@example.com", "g-1"))
    assert follow_ticket(anon_client, location) == f"{settings.public_url}/"
    assert [s.user_id for s in sessions_of(db_session, user.id)] == [user.id]


def test_legacy_google_user_is_adopted_on_first_sign_in(anon_client, db_session):
    legacy = make_user(db_session, "legacy@example.com", password=None)   # made by the old flow: no subject

    _, location = google_callback(anon_client, "/auth/login", _google("legacy@example.com", "g-legacy"))

    assert follow_ticket(anon_client, location) == f"{settings.public_url}/"
    assert _identities(db_session) == [(legacy.id, "g-legacy", "legacy@example.com")]


def test_email_match_with_another_method_requires_linking(anon_client, db_session):
    make_user(db_session, "legacy@example.com")   # has a password

    _, location = google_callback(anon_client, "/auth/login", _google("legacy@example.com", "g-stranger"))

    assert location == f"{settings.public_url}/login?error=link_required"
    assert _identities(db_session) == []
    assert db_session.scalar(select(func.count()).select_from(User)) == 1


# ── linking from Settings ─────────────────────────────────────────────────────

def test_link_google_from_settings(anon_client, db_session):
    cook = make_user(db_session, "cook@example.com")
    password_login(anon_client, "cook@example.com")

    google, location = google_callback(anon_client, "/auth/google/link", _google("cook.alt@gmail.com", "g-alt"))

    assert google["prompt"] == ["select_account"]
    assert follow_ticket(anon_client, location) == f"{settings.public_url}/settings?linked=google"
    assert _identities(db_session) == [(cook.id, "g-alt", "cook.alt@gmail.com")]
    # ...and it now signs in as cook, though its email is different.
    anon_client.post("/auth/logout")
    _, location = google_callback(anon_client, "/auth/login", _google("cook.alt@gmail.com", "g-alt"))
    assert follow_ticket(anon_client, location) == f"{settings.public_url}/"
    assert anon_client.get("/auth/me").json()["user"]["email"] == "cook@example.com"


def test_linking_a_google_account_owned_by_someone_else_is_refused(anon_client, db_session):
    make_user(db_session, "owner@example.com", password=None, google_subject="g-taken")
    make_user(db_session, "cook@example.com")
    password_login(anon_client, "cook@example.com")

    _, location = google_callback(anon_client, "/auth/google/link", _google("owner@example.com", "g-taken"))

    assert follow_ticket(anon_client, location) == f"{settings.public_url}/settings?error=already_linked"
    assert len(_identities(db_session)) == 1


def test_link_needs_a_recent_sign_in(anon_client, db_session):
    cook = make_user(db_session, "cook@example.com")
    password_login(anon_client, "cook@example.com")
    age_sessions(db_session, cook.id, minutes=11)
    res = anon_client.get("/auth/google/link", follow_redirects=False)
    assert res.headers["location"] == f"{settings.public_url}/settings?error=reauth_required"


# ── re-auth ───────────────────────────────────────────────────────────────────

@pytest.fixture()
def google_cook(anon_client, db_session) -> User:
    """Signed in with a password, with a linked Google account g-cook, re-auth stale."""
    cook = make_user(db_session, "cook@example.com", google_subject="g-cook")
    password_login(anon_client, "cook@example.com")
    age_sessions(db_session, cook.id, minutes=11)
    return cook


def test_google_reauth_restarts_the_window(anon_client, db_session, google_cook):
    before = sessions_of(db_session, google_cook.id)[0].authenticated_at
    google, location = google_callback(
        anon_client, "/auth/reauth/google", _google("cook@example.com", "g-cook", auth_time=int(time.time())),
    )
    assert google["prompt"] == ["login"] and google["max_age"] == ["0"]
    assert follow_ticket(anon_client, location) == f"{settings.public_url}/settings?reauth=ok"
    assert sessions_of(db_session, google_cook.id)[0].authenticated_at > before


def test_google_reauth_without_a_fresh_password_is_refused(anon_client, google_cook):
    stale = int(time.time()) - 6 * 60
    _, location = google_callback(anon_client, "/auth/reauth/google", _google("cook@example.com", "g-cook", auth_time=stale))
    assert location == f"{settings.public_url}/settings?error=reauth_failed"


def test_google_reauth_with_another_google_account_is_refused(anon_client, google_cook):
    _, location = google_callback(
        anon_client, "/auth/reauth/google", _google("someone@example.com", "g-other", auth_time=int(time.time())),
    )
    assert location == f"{settings.public_url}/settings?error=reauth_wrong_account"


def test_reauth_ticket_from_another_session_is_refused(anon_client, db_session, google_cook):
    _, location = google_callback(
        anon_client, "/auth/reauth/google", _google("cook@example.com", "g-cook", auth_time=int(time.time())),
    )
    # The same user signs in again: a different session now holds the cookie.
    password_login(anon_client, "cook@example.com")
    first, _ = sessions_of(db_session, google_cook.id)
    assert anon_client.cookies.get(SESSION_COOKIE_NAME)

    assert follow_ticket(anon_client, location) == f"{settings.public_url}/settings?error=expired"
    first_after, _ = sessions_of(db_session, google_cook.id)
    assert first_after.authenticated_at == first.authenticated_at   # the session that started it wasn't bumped
