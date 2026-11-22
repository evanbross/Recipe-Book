# =============================================================================
# Copyright (c) 2026 ZombieTech LLC. All rights reserved.
#
# SPDX-License-Identifier: PolyForm-Strict-1.0.0
# See LICENSE in the project root for the full terms.
#
# Licensing inquiries: license@zombietech.biz
# =============================================================================
from dataclasses import replace
from unittest.mock import patch

from app.config import settings
from app.database import get_current_auth
from app.main import app
from app.models import SystemSetting
from app.services.system_settings import SystemSmtpSettings


# ai: gpt-5 | 2026-11-21
def _as_admin(signed_in_user):
    return replace(signed_in_user, is_admin=True)


# ai: gpt-5 | 2026-11-21
def test_non_admin_cannot_read_global_smtp_settings(client):
    response = client.get("/admin/smtp")
    assert (response.status_code, response.json()["detail"]) == (403, "admin_required")


# ai: gpt-5 | 2026-11-21
def test_admin_can_save_encrypted_smtp_settings(client, db_session, signed_in_user):
    app.dependency_overrides[get_current_auth] = lambda: _as_admin(signed_in_user)
    response = client.put(
        "/admin/smtp",
        headers={"origin": settings.public_url},
        json={
            "host": "smtp.example.com", "port": 587, "user": "mailer@example.com",
            "password": "top-secret-password", "use_tls": True,
            "from_address": "recipes@example.com",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "host": "smtp.example.com", "port": 587, "user": "mailer@example.com",
        "use_tls": True, "from_address": "recipes@example.com",
        "password_set": True, "source": "database",
    }
    stored = db_session.get(SystemSetting, "smtp")
    assert stored is not None
    assert "top-secret-password" not in stored.value
    assert SystemSmtpSettings(db_session).effective_config().password == "top-secret-password"


# ai: gpt-5 | 2026-11-21
def test_blank_password_keeps_existing_secret(client, db_session, signed_in_user):
    service = SystemSmtpSettings(db_session)
    service.save(
        host="old.example.com", port=587, user="old", password="existing-secret",
        use_tls=True, from_address="old@example.com",
    )
    db_session.commit()
    app.dependency_overrides[get_current_auth] = lambda: _as_admin(signed_in_user)

    response = client.put(
        "/admin/smtp", headers={"origin": settings.public_url},
        json={
            "host": "new.example.com", "port": 2525, "user": "new", "password": None,
            "use_tls": False, "from_address": "new@example.com",
        },
    )

    assert response.status_code == 200
    assert SystemSmtpSettings(db_session).effective_config().password == "existing-secret"


# ai: gpt-5 | 2026-11-21
def test_admin_can_send_test_email_to_their_own_address(client, signed_in_user):
    app.dependency_overrides[get_current_auth] = lambda: _as_admin(signed_in_user)
    with patch("app.routes.admin.send_email") as send:
        response = client.post("/admin/smtp/test", headers={"origin": settings.public_url})

    assert response.status_code == 204
    assert send.call_args.kwargs["to"] == "owner@example.com"
    assert send.call_args.kwargs["subject"] == "RecipeBox SMTP test"
