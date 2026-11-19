# =============================================================================
# Copyright (c) 2026 ZombieTech LLC. All rights reserved.
#
# SPDX-License-Identifier: PolyForm-Strict-1.0.0
# See LICENSE in the project root for the full terms.
#
# Licensing inquiries: license@zombietech.biz
# =============================================================================
# ai: claude-opus-5-5 | 2026-11-19
"""Passkeys: registering, signing in without a username, re-auth, managing.

A SoftAuthenticator plays the browser + authenticator with a real key, and
every response goes through py_webauthn's real verification.
"""
import pytest
from sqlalchemy import select

from app.config import settings
from app.database import SESSION_COOKIE_NAME, User, WebAuthnCredential
from tests.sign_in_helpers import APP_ORIGIN, age_sessions, make_user, password_login, sessions_of
from tests.soft_authenticator import SoftAuthenticator


@pytest.fixture()
def cook(anon_client, db_session) -> User:
    """A user signed in with a password in anon_client, so re-auth is fresh."""
    user = make_user(db_session, "cook@example.com")
    assert password_login(anon_client, "cook@example.com").status_code == 204
    return user


def _authenticator() -> SoftAuthenticator:
    return SoftAuthenticator(rp_id=settings.webauthn_rp_id, origin=settings.public_url)


def _register_passkey(client, name: str | None = None) -> tuple[SoftAuthenticator, dict]:
    authenticator = _authenticator()
    options = client.post("/auth/passkeys/register/options", headers=APP_ORIGIN)
    assert options.status_code == 200, options.text
    body = {"flow_id": options.json()["flow_id"], "credential": authenticator.create(options.json()["options"])}
    if name:
        body["name"] = name
    res = client.post("/auth/passkeys/register/verify", json=body, headers=APP_ORIGIN)
    assert res.status_code == 201, res.text
    return authenticator, res.json()


def _passkey_login(client, authenticator: SoftAuthenticator, **get_kwargs):
    options = client.post("/auth/passkeys/login/options").json()
    credential = authenticator.get(options["options"], **get_kwargs)
    return client.post("/auth/passkeys/login/verify", json={"flow_id": options["flow_id"], "credential": credential})


# ── registering ───────────────────────────────────────────────────────────────

def test_register_options_require_a_recent_sign_in(anon_client, db_session, cook):
    age_sessions(db_session, cook.id, minutes=11)
    res = anon_client.post("/auth/passkeys/register/options", headers=APP_ORIGIN)
    assert (res.status_code, res.json()["detail"]) == (403, "reauth_required")


def test_register_stores_the_passkey(anon_client, db_session, cook):
    _, passkey = _register_passkey(anon_client, name="Laptop")

    row = db_session.scalar(select(WebAuthnCredential).where(WebAuthnCredential.user_id == cook.id))
    assert passkey["name"] == row.name == "Laptop"
    assert row.transports == ["internal", "hybrid"]
    assert row.backed_up is True
    db_session.refresh(cook)
    assert cook.webauthn_user_handle is not None and len(cook.webauthn_user_handle) == 32


def test_register_options_ask_for_a_discoverable_passkey(anon_client, cook):
    options = anon_client.post("/auth/passkeys/register/options", headers=APP_ORIGIN).json()["options"]
    assert options["rp"]["id"] == settings.webauthn_rp_id
    assert options["authenticatorSelection"]["residentKey"] == "required"
    assert options["attestation"] == "none"


# ── signing in ────────────────────────────────────────────────────────────────

def test_passkey_sign_in_needs_no_username(anon_client, db_session, cook):
    authenticator, _ = _register_passkey(anon_client)
    anon_client.post("/auth/logout")

    options = anon_client.post("/auth/passkeys/login/options").json()
    assert "allowCredentials" not in options["options"] or options["options"]["allowCredentials"] == []
    res = anon_client.post("/auth/passkeys/login/verify", json={
        "flow_id": options["flow_id"], "credential": authenticator.get(options["options"]),
    })

    assert res.status_code == 204
    assert anon_client.cookies.get(SESSION_COOKIE_NAME)
    assert [s.auth_method for s in sessions_of(db_session, cook.id)] == ["passkey"]
    row = db_session.scalar(select(WebAuthnCredential).where(WebAuthnCredential.user_id == cook.id))
    assert row.sign_count == 1 and row.last_used_at is not None


@pytest.mark.parametrize("tamper", [
    {"origin": "http://evil.localhost"},
    {"rp_id": "evil.localhost"},
])
def test_passkey_for_another_site_is_refused(anon_client, cook, tamper):
    authenticator, _ = _register_passkey(anon_client)
    res = _passkey_login(anon_client, authenticator, **tamper)
    assert (res.status_code, res.json()["detail"]) == (401, "invalid_credentials")


def test_a_challenge_works_once(anon_client, cook):
    authenticator, _ = _register_passkey(anon_client)
    options = anon_client.post("/auth/passkeys/login/options").json()
    body = {"flow_id": options["flow_id"], "credential": authenticator.get(options["options"])}
    assert anon_client.post("/auth/passkeys/login/verify", json=body).status_code == 204
    assert anon_client.post("/auth/passkeys/login/verify", json=body).status_code == 401


def test_unknown_passkey_is_refused(anon_client):
    res = _passkey_login(anon_client, _authenticator())
    assert (res.status_code, res.json()["detail"]) == (401, "invalid_credentials")


def test_sign_count_going_backwards_is_refused(anon_client, cook):
    authenticator, _ = _register_passkey(anon_client)
    assert _passkey_login(anon_client, authenticator, sign_count=5).status_code == 204
    assert _passkey_login(anon_client, authenticator, sign_count=3).status_code == 401


def test_user_handle_of_another_account_is_refused(anon_client, db_session, cook):
    authenticator, _ = _register_passkey(anon_client)
    res = _passkey_login(anon_client, authenticator, user_handle=b"x" * 32)
    assert res.status_code == 401


# ── re-auth ───────────────────────────────────────────────────────────────────

def test_passkey_reauth_restarts_the_window(anon_client, db_session, cook):
    authenticator, _ = _register_passkey(anon_client)
    age_sessions(db_session, cook.id, minutes=11)

    options = anon_client.post("/auth/reauth/passkey/options").json()
    allowed = [c["id"] for c in options["options"]["allowCredentials"]]
    res = anon_client.post("/auth/reauth/passkey/verify", json={
        "flow_id": options["flow_id"], "credential": authenticator.get(options["options"]),
    })

    assert res.status_code == 204
    assert len(allowed) == 1
    assert anon_client.post("/auth/passkeys/register/options", headers=APP_ORIGIN).status_code == 200


def test_another_users_passkey_cannot_reauth_this_user(anon_client, db_session, cook):
    other_authenticator, _ = _register_passkey(anon_client)   # registered to cook...
    other = make_user(db_session, "other@example.com")
    db_session.execute(
        WebAuthnCredential.__table__.update().values(user_id=other.id)   # ...now belongs to someone else
    )
    db_session.commit()

    options = anon_client.post("/auth/reauth/passkey/options").json()
    res = anon_client.post("/auth/reauth/passkey/verify", json={
        "flow_id": options["flow_id"], "credential": other_authenticator.get(options["options"]),
    })
    assert res.status_code == 401


def test_a_sign_in_challenge_cannot_finish_a_reauth(anon_client, cook):
    authenticator, _ = _register_passkey(anon_client)
    options = anon_client.post("/auth/passkeys/login/options").json()
    res = anon_client.post("/auth/reauth/passkey/verify", json={
        "flow_id": options["flow_id"], "credential": authenticator.get(options["options"]),
    })
    assert res.status_code == 401


# ── managing ──────────────────────────────────────────────────────────────────

def test_rename_and_remove_a_passkey(anon_client, db_session, cook):
    _, passkey = _register_passkey(anon_client)

    renamed = anon_client.patch(f"/auth/passkeys/{passkey['id']}", json={"name": "Phone"}, headers=APP_ORIGIN)
    assert (renamed.status_code, renamed.json()["name"]) == (200, "Phone")
    assert anon_client.delete(f"/auth/passkeys/{passkey['id']}", headers=APP_ORIGIN).status_code == 204
    assert db_session.scalar(select(WebAuthnCredential)) is None


def test_removing_the_last_method_is_refused(anon_client, db_session, cook):
    _, passkey = _register_passkey(anon_client)
    assert anon_client.delete("/auth/password", headers=APP_ORIGIN).status_code == 204

    res = anon_client.delete(f"/auth/passkeys/{passkey['id']}", headers=APP_ORIGIN)

    assert (res.status_code, res.json()["detail"]) == (409, "last_method")
    assert db_session.scalar(select(WebAuthnCredential)) is not None
