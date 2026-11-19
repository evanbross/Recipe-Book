# =============================================================================
# Copyright (c) 2026 ZombieTech LLC. All rights reserved.
#
# SPDX-License-Identifier: PolyForm-Strict-1.0.0
# See LICENSE in the project root for the full terms.
#
# Licensing inquiries: license@zombietech.biz
# =============================================================================
# ai: claude-opus-5-5 | 2026-11-19
"""Password sign-in: registration by email, sign-in, throttling, reset.

Real cookies through anon_client, real schema, real zt_common.smtp code with
only the socket replaced (sent_emails), plus one send through real MailHog.
"""
import json
import quopri
from email.header import decode_header, make_header
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from argon2 import PasswordHasher
from sqlalchemy import func, select, update

from app.config import settings
from app.database import (
    EMAIL_TOKEN_REGISTER, SESSION_COOKIE_NAME, EmailToken, PasswordCredential, TenantMembership, User,
)
from app.services import passwords
from app.services.account_email import AccountEmailService
from tests.sign_in_helpers import PASSWORD, make_user, password_login, sessions_of, token_from

NEW_EMAIL = "newcook@example.com"


@pytest.fixture(autouse=True)
def _allowlisted(monkeypatch):
    monkeypatch.setattr(settings, "auth_allowed_emails", NEW_EMAIL)


def _register(client, email: str = NEW_EMAIL, password: str = PASSWORD):
    return client.post("/auth/password/register", json={"email": email, "password": password, "display_name": "New"})


# ── registration ──────────────────────────────────────────────────────────────

def test_register_then_verify_creates_the_account_and_signs_in(anon_client, db_session, sent_emails):
    assert _register(anon_client).status_code == 202
    (message,) = sent_emails.sent
    assert message["To"] == NEW_EMAIL
    assert message["Subject"].startswith("RecipeBox — ")
    assert db_session.scalar(select(User).where(User.email == NEW_EMAIL)) is None   # not until the link is followed

    res = anon_client.post("/auth/password/verify", json={"token": token_from(message)})

    assert res.status_code == 204
    assert anon_client.cookies.get(SESSION_COOKIE_NAME)
    user = db_session.scalar(select(User).where(User.email == NEW_EMAIL))
    assert user.email_verified_at is not None and user.display_name == "New"
    assert db_session.get(PasswordCredential, user.id) is not None
    assert db_session.scalar(select(TenantMembership).where(TenantMembership.user_id == user.id)) is not None
    assert [s.auth_method for s in sessions_of(db_session, user.id)] == ["password"]
    assert anon_client.get("/auth/me").json()["user"]["email"] == NEW_EMAIL


def test_register_for_an_existing_address_sends_already_registered(anon_client, db_session, sent_emails):
    make_user(db_session, "cook@example.com")

    assert _register(anon_client, "cook@example.com").status_code == 202

    (message,) = sent_emails.sent
    assert "already has an account" in message.get_content()
    assert "/reset-password?token=" in message.get_content()
    assert db_session.scalar(
        select(func.count()).select_from(EmailToken).where(EmailToken.purpose == EMAIL_TOKEN_REGISTER)
    ) == 0


def test_register_answers_identically_for_new_and_existing_addresses(anon_client, db_session, sent_emails):
    make_user(db_session, "cook@example.com")
    new, existing = _register(anon_client, NEW_EMAIL), _register(anon_client, "cook@example.com")
    assert (new.status_code, new.content, new.headers.get("content-type")) == (
        existing.status_code, existing.content, existing.headers.get("content-type"))


@pytest.mark.parametrize(("password", "reason"), [
    ("elevenchars", "too_short"),
    (NEW_EMAIL, "same_as_email"),
    (NEW_EMAIL.upper(), "same_as_email"),
    ("x" * 257, "too_long"),
])
def test_weak_passwords_are_refused(anon_client, sent_emails, password, reason):
    res = _register(anon_client, password=password)
    assert res.status_code == 422
    assert res.json()["detail"] == f"weak_password:{reason}"
    assert sent_emails.sent == []


def test_verification_link_works_once(anon_client, sent_emails):
    _register(anon_client)
    token = token_from(sent_emails.sent[0])
    assert anon_client.post("/auth/password/verify", json={"token": token}).status_code == 204
    res = anon_client.post("/auth/password/verify", json={"token": token})
    assert (res.status_code, res.json()["detail"]) == (400, "invalid_token")


def test_expired_verification_link_is_refused(anon_client, db_session, sent_emails):
    _register(anon_client)
    db_session.execute(update(EmailToken).values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
    db_session.commit()
    res = anon_client.post("/auth/password/verify", json={"token": token_from(sent_emails.sent[0])})
    assert (res.status_code, res.json()["detail"]) == (400, "invalid_token")


def test_verified_but_uninvited_account_is_created_and_told_to_ask(anon_client, db_session, sent_emails, monkeypatch):
    monkeypatch.setattr(settings, "auth_allowed_emails", "")
    _register(anon_client)
    res = anon_client.post("/auth/password/verify", json={"token": token_from(sent_emails.sent[0])})
    assert (res.status_code, res.json()["detail"]) == (403, "not_invited")
    assert db_session.scalar(select(User).where(User.email == NEW_EMAIL)) is not None
    assert SESSION_COOKIE_NAME not in anon_client.cookies


# ── sign-in ───────────────────────────────────────────────────────────────────

def test_password_login_sets_a_password_session(anon_client, db_session):
    user = make_user(db_session, "cook@example.com")
    res = password_login(anon_client, "COOK@example.com ")   # normalised like every email field
    assert res.status_code == 204
    assert anon_client.cookies.get(SESSION_COOKIE_NAME)
    assert [s.auth_method for s in sessions_of(db_session, user.id)] == ["password"]


def test_wrong_password_and_unknown_email_fail_identically(anon_client, db_session):
    make_user(db_session, "cook@example.com")
    wrong = password_login(anon_client, "cook@example.com", "not the password")
    unknown = password_login(anon_client, "nobody@example.com")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.content == unknown.content
    assert wrong.json()["detail"] == "invalid_credentials"


@pytest.mark.parametrize("email", ["cook@example.com", "nobody@example.com"])
def test_sixth_failure_in_fifteen_minutes_is_throttled(anon_client, db_session, email):
    make_user(db_session, "cook@example.com")
    for _ in range(5):
        assert password_login(anon_client, email, "wrong password!").status_code == 401

    res = password_login(anon_client, email, PASSWORD)   # even the right password, for a known address

    assert res.status_code == 429
    assert res.json()["detail"] == "too_many_attempts"
    assert 0 < int(res.headers["Retry-After"]) <= 15 * 60


def test_login_rehashes_a_password_hashed_with_old_parameters(anon_client, db_session):
    user = make_user(db_session, "cook@example.com", password=None)
    old_hash = PasswordHasher(time_cost=1, memory_cost=8 * 1024, parallelism=1).hash(PASSWORD)
    db_session.add(PasswordCredential(user_id=user.id, password_hash=old_hash))
    db_session.commit()

    assert password_login(anon_client, "cook@example.com").status_code == 204

    db_session.expire_all()
    new_hash = db_session.get(PasswordCredential, user.id).password_hash
    assert new_hash != old_hash
    assert not passwords.PasswordHasherService().needs_rehash(new_hash)


# ── reset ─────────────────────────────────────────────────────────────────────

def test_reset_sets_the_password_and_ends_every_session(anon_client, db_session, sent_emails):
    user = make_user(db_session, "cook@example.com")
    assert password_login(anon_client, "cook@example.com").status_code == 204
    assert len(sessions_of(db_session, user.id)) == 1

    assert anon_client.post("/auth/password/forgot", json={"email": "cook@example.com"}).status_code == 202
    res = anon_client.post(
        "/auth/password/reset",
        json={"token": token_from(sent_emails.sent[0]), "password": "a brand new passphrase"},
    )

    assert res.status_code == 204
    assert sessions_of(db_session, user.id) == []
    assert anon_client.get("/auth/me").status_code == 401
    assert password_login(anon_client, "cook@example.com", "a brand new passphrase").status_code == 204


def test_weak_reset_password_keeps_the_link_usable(anon_client, db_session, sent_emails):
    make_user(db_session, "cook@example.com")
    anon_client.post("/auth/password/forgot", json={"email": "cook@example.com"})
    token = token_from(sent_emails.sent[0])
    weak = anon_client.post("/auth/password/reset", json={"token": token, "password": "short"})
    assert (weak.status_code, weak.json()["detail"]) == (422, "weak_password:too_short")
    assert anon_client.post(
        "/auth/password/reset", json={"token": token, "password": "a brand new passphrase"},
    ).status_code == 204


def test_forgot_for_an_unknown_address_sends_nothing(anon_client, sent_emails):
    res = anon_client.post("/auth/password/forgot", json={"email": "nobody@example.com"})
    assert res.status_code == 202
    assert sent_emails.sent == []


def test_fourth_account_email_in_an_hour_is_not_sent(anon_client, db_session, sent_emails):
    make_user(db_session, "cook@example.com")
    for _ in range(4):
        assert anon_client.post("/auth/password/forgot", json={"email": "cook@example.com"}).status_code == 202
    assert len(sent_emails.sent) == 3


def test_smtp_failure_is_502_and_the_token_survives(anon_client, db_session, sent_emails):
    make_user(db_session, "cook@example.com")
    sent_emails.fail = True

    res = anon_client.post("/auth/password/forgot", json={"email": "cook@example.com"})

    assert (res.status_code, res.json()["detail"]) == (502, "email_failed")
    # Committed before the send was attempted: the DB connection wasn't held across it.
    assert db_session.scalar(select(func.count()).select_from(EmailToken)) == 1


# ../infra's MailHog HTTP API, as its docker-compose.yml maps it to the host.
_MAILHOG_API = "http://127.0.0.1:8890/api/v2"


def _mailhog_running() -> bool:
    try:
        with urllib.request.urlopen(f"{_MAILHOG_API}/messages?limit=1", timeout=2):
            return True
    except (urllib.error.URLError, TimeoutError):
        return False


@pytest.mark.skipif(not _mailhog_running(), reason="MailHog (../infra) is not running")
def test_account_email_arrives_in_real_mailhog():
    """The real boundary: this app's settings.smtp_config talking SMTP to MailHog."""
    # A unique recipient, so this finds its own message among whatever MailHog holds.
    to = f"mailhog-{uuid.uuid4().hex[:12]}@example.com"
    link = f"{settings.public_url}/reset-password?token=t"

    AccountEmailService().send_password_reset(to, link)

    query = urllib.parse.urlencode({"kind": "to", "query": to})
    with urllib.request.urlopen(f"{_MAILHOG_API}/search?{query}", timeout=5) as response:
        (item,) = json.load(response)["items"]
    (raw_subject,) = item["Content"]["Headers"]["Subject"]   # MIME-encoded on the wire (the em dash)
    assert str(make_header(decode_header(raw_subject))) == "RecipeBox — Reset your password"
    body = quopri.decodestring(item["Content"]["Body"].encode()).decode()   # long lines arrive soft-wrapped
    assert link in body
