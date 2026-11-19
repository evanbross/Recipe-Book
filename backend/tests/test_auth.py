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
Google sign-in, sessions, the sign-in requirement on every data route, and
household invites.

These use anon_client: no dependency overrides, so every request goes through
the real cookie lookup against the real test schema. Only Google is faked, at
the token exchange and ID-token verification.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.routing import APIRoute
from sqlalchemy import select, update

from app.config import settings
from app.database import (
    ROLE_MEMBER, ROLE_OWNER, SESSION_COOKIE_NAME, TenantInvite, TenantMembership, User, UserSession,
)
from app.main import app
from app.services.google_oauth import GoogleIdentity
from tests.sign_in_helpers import follow_ticket, google_callback

API_PORT = 54321
PUBLIC_ROUTES = {
    ("GET", "/health"),
    ("GET", "/auth/login"),
    ("GET", "/auth/callback"),
    ("GET", "/auth/complete"),
    ("POST", "/auth/logout"),
    ("GET", "/email/auth/callback"),
    # ai: claude-opus-5-5 | 2026-11-19
    # Password and passkey sign-in (spec section 7.1). Listed one by one on purpose:
    # the signed-in /auth routes share these routers and must still answer 401.
    ("POST", "/auth/password/login"),
    ("POST", "/auth/password/register"),
    ("POST", "/auth/password/verify"),
    ("POST", "/auth/password/forgot"),
    ("POST", "/auth/password/reset"),
    ("POST", "/auth/passkeys/login/options"),
    ("POST", "/auth/passkeys/login/verify"),
}


@pytest.fixture(autouse=True)
def _oauth_config(monkeypatch, fake_google_credentials):
    monkeypatch.setattr(settings, "api_port", API_PORT)
    monkeypatch.setattr(settings, "auth_allowed_emails", "")


def _sign_in(  # ai: claude-opus-5-5 | 2026-11-19
    client, email: str, *, verified: bool = True, name: str | None = None, subject: str | None = None,
) -> str:
    """Run the three-hop Google sign-in; return the final redirect location."""
    # One Google account per email unless a test says otherwise.
    identity = GoogleIdentity(subject=subject or f"sub-{email}", email=email, email_verified=verified, name=name)
    google, location = google_callback(client, "/auth/login", identity)
    assert google["redirect_uri"] == [f"http://localhost:{API_PORT}/auth/callback"]
    if "/auth/complete?" not in location:
        return location
    return follow_ticket(client, location)


def _membership(db_session, email: str) -> TenantMembership | None:
    return db_session.scalar(
        select(TenantMembership).join(User, User.id == TenantMembership.user_id).where(User.email == email)
    )


# ── every data route needs a session ──────────────────────────────────────────

def _concrete(path: str) -> str:
    return path.replace("{key:path}", "tenants/1/x.jpg").replace("{", "").replace("}", "").replace(
        "recipe_id", "1").replace("tag_id", "1").replace("site_id", "1").replace(
        "candidate_id", "1").replace("invite_id", "1").replace("user_id", "1").replace(
        "passkey_id", "1").replace("identity_id", "1")  # ai: claude-opus-5-5 | 2026-11-19


def _protected_routes() -> list[tuple[str, str]]:
    routes = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in route.methods:
            if (method, route.path) not in PUBLIC_ROUTES:
                routes.append((method, route.path))
    return sorted(routes)


@pytest.mark.parametrize(("method", "path"), _protected_routes())
def test_every_non_public_route_refuses_anonymous_requests(anon_client, method, path):
    res = anon_client.request(method, _concrete(path))
    assert res.status_code == 401, f"{method} {path} answered {res.status_code} without a session"


def test_a_bogus_cookie_is_not_a_session(anon_client):
    anon_client.cookies.set(SESSION_COOKIE_NAME, "made-up")
    assert anon_client.get("/recipes").status_code == 401


# ── sign-in ───────────────────────────────────────────────────────────────────

def test_first_allowlisted_user_becomes_owner_and_can_use_the_app(anon_client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "auth_allowed_emails", "Cook@Example.com, other@example.com")

    assert _sign_in(anon_client, "cook@example.com", name="Cook") == f"{settings.public_url}/"

    me = anon_client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "cook@example.com"
    assert me.json()["role"] == ROLE_OWNER
    assert anon_client.get("/recipes").status_code == 200

    stored = db_session.scalar(select(UserSession))
    assert stored.token_hash != anon_client.cookies[SESSION_COOKIE_NAME]   # only the hash is stored


def test_second_allowlisted_user_joins_as_member(anon_client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "auth_allowed_emails", "first@example.com,second@example.com")
    _sign_in(anon_client, "first@example.com")
    anon_client.cookies.clear()
    _sign_in(anon_client, "second@example.com")

    assert _membership(db_session, "first@example.com").role == ROLE_OWNER
    assert _membership(db_session, "second@example.com").role == ROLE_MEMBER


@pytest.mark.parametrize(("email", "verified", "error"), [
    ("stranger@example.com", True, "not_invited"),
    ("allowed@example.com", False, "unverified_email"),
])
def test_refused_sign_ins_create_nothing(anon_client, db_session, monkeypatch, email, verified, error):
    monkeypatch.setattr(settings, "auth_allowed_emails", "allowed@example.com")
    location = _sign_in(anon_client, email, verified=verified)
    assert location == f"{settings.public_url}/login?error={error}"
    assert db_session.scalar(select(User).where(User.email == email)) is None
    assert anon_client.get("/auth/me").status_code == 401


def test_callback_with_unknown_state_is_refused(anon_client):
    res = anon_client.get("/auth/callback?code=abc&state=never-issued", follow_redirects=False)
    assert res.headers["location"] == f"{settings.public_url}/login?error=expired"


def test_sign_in_ticket_works_once(anon_client, monkeypatch):
    monkeypatch.setattr(settings, "auth_allowed_emails", "cook@example.com")
    res = anon_client.get("/auth/login", follow_redirects=False)
    state = parse_qs(urlparse(res.headers["location"]).query)["state"][0]
    identity = GoogleIdentity(subject="sub-cook", email="cook@example.com", email_verified=True, name=None)
    with patch("google_auth_oauthlib.flow.Flow.fetch_token"), \
            patch("app.routes.auth.identity_from_flow", return_value=identity):
        res = anon_client.get(f"/auth/callback?code=abc&state={state}", follow_redirects=False)
    ticket = parse_qs(urlparse(res.headers["location"]).query)["ticket"][0]

    assert anon_client.get(f"/auth/complete?ticket={ticket}", follow_redirects=False).headers["location"] \
        == f"{settings.public_url}/"
    assert anon_client.get(f"/auth/complete?ticket={ticket}", follow_redirects=False).headers["location"] \
        == f"{settings.public_url}/login?error=expired"


def test_session_cookie_flags(anon_client, monkeypatch):
    monkeypatch.setattr(settings, "auth_allowed_emails", "cook@example.com")
    res = anon_client.get("/auth/login", follow_redirects=False)
    state = parse_qs(urlparse(res.headers["location"]).query)["state"][0]
    identity = GoogleIdentity(subject="sub-cook", email="cook@example.com", email_verified=True, name=None)
    with patch("google_auth_oauthlib.flow.Flow.fetch_token"), \
            patch("app.routes.auth.identity_from_flow", return_value=identity):
        res = anon_client.get(f"/auth/callback?code=abc&state={state}", follow_redirects=False)
    ticket = parse_qs(urlparse(res.headers["location"]).query)["ticket"][0]
    cookie = anon_client.get(f"/auth/complete?ticket={ticket}", follow_redirects=False).headers["set-cookie"]
    assert cookie.startswith(f"{SESSION_COOKIE_NAME}=")
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Path=/" in cookie


def test_logout_ends_the_session(anon_client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "auth_allowed_emails", "cook@example.com")
    _sign_in(anon_client, "cook@example.com")
    token = anon_client.cookies[SESSION_COOKIE_NAME]

    assert anon_client.post("/auth/logout").status_code == 204
    assert db_session.scalar(select(UserSession)) is None
    anon_client.cookies.set(SESSION_COOKIE_NAME, token)   # a copied cookie is dead too
    assert anon_client.get("/auth/me").status_code == 401


def test_expired_session_is_refused(anon_client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "auth_allowed_emails", "cook@example.com")
    _sign_in(anon_client, "cook@example.com")
    db_session.execute(update(UserSession).values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
    db_session.commit()
    assert anon_client.get("/recipes").status_code == 401


# ── invites and members ───────────────────────────────────────────────────────

def test_invited_email_joins_the_household_on_sign_in(anon_client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "auth_allowed_emails", "owner@example.com")
    _sign_in(anon_client, "owner@example.com")
    res = anon_client.post("/household/invites", json={"email": "  Guest@Example.COM "})
    assert res.status_code == 201
    assert res.json()["email"] == "guest@example.com"

    anon_client.cookies.clear()
    _sign_in(anon_client, "guest@example.com")
    household = anon_client.get("/household").json()
    assert {m["email"]: m["role"] for m in household["members"]} == {
        "owner@example.com": ROLE_OWNER, "guest@example.com": ROLE_MEMBER,
    }
    assert household["invites"] == []


def test_members_cannot_invite_or_remove(anon_client, monkeypatch):
    monkeypatch.setattr(settings, "auth_allowed_emails", "owner@example.com,member@example.com")
    _sign_in(anon_client, "owner@example.com")
    anon_client.cookies.clear()
    _sign_in(anon_client, "member@example.com")

    assert anon_client.post("/household/invites", json={"email": "x@example.com"}).status_code == 403
    assert anon_client.delete("/household/members/1").status_code == 403
    assert anon_client.delete("/admin/purge-recipes").status_code == 403


def test_duplicate_and_member_invites_conflict(client, signed_in_user):
    assert client.post("/household/invites", json={"email": "guest@example.com"}).status_code == 201
    assert client.post("/household/invites", json={"email": "GUEST@example.com"}).status_code == 409
    assert client.post("/household/invites", json={"email": "owner@example.com"}).status_code == 409
    assert client.post("/household/invites", json={"email": "not-an-email"}).status_code == 422


def test_owner_cannot_remove_themselves(client, signed_in_user):
    assert client.delete(f"/household/members/{signed_in_user.user_id}").status_code == 400


def test_removed_member_is_signed_out_immediately(anon_client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "auth_allowed_emails", "owner@example.com,member@example.com")
    _sign_in(anon_client, "owner@example.com")
    owner_cookie = anon_client.cookies[SESSION_COOKIE_NAME]
    anon_client.cookies.clear()
    _sign_in(anon_client, "member@example.com")
    member_cookie = anon_client.cookies[SESSION_COOKIE_NAME]
    member_id = db_session.scalar(select(User.id).where(User.email == "member@example.com"))

    anon_client.cookies.set(SESSION_COOKIE_NAME, owner_cookie)
    assert anon_client.delete(f"/household/members/{member_id}").status_code == 204
    anon_client.cookies.set(SESSION_COOKIE_NAME, member_cookie)
    assert anon_client.get("/recipes").status_code == 401


def test_invites_are_private_to_their_household(client, other_household):
    other_invite = TenantInvite(email="theirs@example.com")
    other_household.add(other_invite)
    other_household.commit()

    assert client.get("/household").json()["invites"] == []
    assert client.delete(f"/household/invites/{other_invite.id}").status_code == 404
    other_household.expire_all()
    assert other_household.get(TenantInvite, other_invite.id) is not None


def test_invite_to_another_household_is_accepted_alongside_membership(
    anon_client, db_session, other_household, monkeypatch,
):
    """Invites from every household for the email are accepted at sign-in."""
    monkeypatch.setattr(settings, "auth_allowed_emails", "cook@example.com")
    _sign_in(anon_client, "cook@example.com")
    other_household.add(TenantInvite(email="cook@example.com"))
    other_household.commit()

    anon_client.cookies.clear()
    _sign_in(anon_client, "cook@example.com")
    user_id = db_session.scalar(select(User.id).where(User.email == "cook@example.com"))
    tenants = set(db_session.scalars(select(TenantMembership.tenant_id).where(TenantMembership.user_id == user_id)))
    assert tenants == {db_session.info["tenant_id"], other_household.info["tenant_id"]}


# ── write requests from other origins ─────────────────────────────────────────

@pytest.mark.parametrize(("origin", "allowed"), [
    (None, True),
    ("http://recipe-app.localhost", True),
    ("chrome-extension://abcdefghijklmnop", True),
    ("http://some-other-app.localhost", False),
    ("https://evil.example", False),
])
def test_writes_from_untrusted_origins_are_refused(client, origin, allowed):
    headers = {"Origin": origin} if origin else {}
    res = client.post("/tags/categories", json={"name": "Cuisine"}, headers=headers)
    assert (res.status_code != 403) is allowed
