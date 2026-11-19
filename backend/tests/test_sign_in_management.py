# =============================================================================
# Copyright (c) 2026 ZombieTech LLC. All rights reserved.
#
# SPDX-License-Identifier: PolyForm-Strict-1.0.0
# See LICENSE in the project root for the full terms.
#
# Licensing inquiries: license@zombietech.biz
# =============================================================================
# ai: claude-opus-5-5 | 2026-11-19
"""Managing sign-in methods from Settings: the re-auth window, the app-origin
check, ownership of ids, and the method overview."""
import pytest
from sqlalchemy import select

from app.config import settings
from app.database import PasswordCredential, UserIdentity, WebAuthnCredential
from tests.sign_in_helpers import (
    APP_ORIGIN, PASSWORD, age_sessions, make_user, password_login, sessions_of,
)


@pytest.fixture()
def cook(anon_client, db_session):
    user = make_user(db_session, "cook@example.com", google_subject="g-cook")
    assert password_login(anon_client, "cook@example.com").status_code == 204
    return user


def test_methods_overview(anon_client, cook):
    res = anon_client.get("/auth/methods")
    assert res.status_code == 200
    body = res.json()
    assert body["has_password"] is True
    assert body["passkeys"] == []
    assert [g["email"] for g in body["google"]] == ["cook@example.com"]
    assert body["reauth_valid_until"]


def test_stale_session_must_reauth_before_changes(anon_client, db_session, cook):
    age_sessions(db_session, cook.id, minutes=11)
    res = anon_client.put("/auth/password", json={"password": "another long passphrase"}, headers=APP_ORIGIN)
    assert (res.status_code, res.json()["detail"]) == (403, "reauth_required")

    assert anon_client.post("/auth/reauth/password", json={"password": PASSWORD}).status_code == 204

    res = anon_client.put("/auth/password", json={"password": "another long passphrase"}, headers=APP_ORIGIN)
    assert res.status_code == 204


def test_wrong_reauth_password_is_401_without_signing_out(anon_client, db_session, cook):
    res = anon_client.post("/auth/reauth/password", json={"password": "not the password"})
    assert (res.status_code, res.json()["detail"]) == (401, "invalid_credentials")
    assert anon_client.get("/auth/me").status_code == 200


def test_changing_the_password_ends_other_sessions_only(anon_client, db_session, cook):
    password_login(anon_client, "cook@example.com")   # this browser's session is now the newer one
    elsewhere_id, current_id = (s.id for s in sessions_of(db_session, cook.id))

    res = anon_client.put("/auth/password", json={"password": "another long passphrase"}, headers=APP_ORIGIN)

    assert res.status_code == 204
    assert [s.id for s in sessions_of(db_session, cook.id)] == [current_id] != [elsewhere_id]
    assert anon_client.get("/auth/me").status_code == 200


@pytest.mark.parametrize(("method", "path", "body"), [
    ("PUT", "/auth/password", {"password": "another long passphrase"}),
    ("DELETE", "/auth/password", None),
    ("POST", "/auth/passkeys/register/options", None),
    ("DELETE", "/auth/identities/1", None),
])
@pytest.mark.parametrize("origin", ["chrome-extension://abcdef", None])
def test_changes_from_outside_the_app_are_refused(anon_client, cook, method, path, body, origin):
    headers = {"Origin": origin} if origin else {}
    res = anon_client.request(method, path, json=body, headers=headers)
    assert (res.status_code, res.json()["detail"]) == (403, "untrusted_origin")


def test_another_users_methods_are_not_found(anon_client, db_session, cook):
    other = make_user(db_session, "other@example.com", google_subject="g-other")
    db_session.add(WebAuthnCredential(
        user_id=other.id, credential_id=b"other-cred", public_key=b"k", sign_count=0, name="Theirs", backed_up=False,
    ))
    db_session.commit()
    passkey_id = db_session.scalar(select(WebAuthnCredential.id))
    identity_id = db_session.scalar(select(UserIdentity.id).where(UserIdentity.user_id == other.id))

    assert anon_client.patch(f"/auth/passkeys/{passkey_id}", json={"name": "Mine"}, headers=APP_ORIGIN).status_code == 404
    assert anon_client.delete(f"/auth/passkeys/{passkey_id}", headers=APP_ORIGIN).status_code == 404
    assert anon_client.delete(f"/auth/identities/{identity_id}", headers=APP_ORIGIN).status_code == 404


def test_unlink_google_then_the_password_is_the_last_method(anon_client, db_session, cook):
    identity_id = db_session.scalar(select(UserIdentity.id).where(UserIdentity.user_id == cook.id))
    assert anon_client.delete(f"/auth/identities/{identity_id}", headers=APP_ORIGIN).status_code == 204

    res = anon_client.delete("/auth/password", headers=APP_ORIGIN)

    assert (res.status_code, res.json()["detail"]) == (409, "last_method")
    assert db_session.get(PasswordCredential, cook.id) is not None


def test_set_password_rules_apply(anon_client, cook):
    res = anon_client.put("/auth/password", json={"password": "cook@example.com"}, headers=APP_ORIGIN)
    assert (res.status_code, res.json()["detail"]) == (422, "weak_password:same_as_email")


def test_reauth_window_matches_the_setting(anon_client, cook, monkeypatch):
    monkeypatch.setattr(settings, "reauth_window_minutes", 0)
    res = anon_client.put("/auth/password", json={"password": "another long passphrase"}, headers=APP_ORIGIN)
    assert res.status_code == 403
