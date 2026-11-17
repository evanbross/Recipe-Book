# =============================================================================
# Copyright (c) 2026 ZombieTech LLC. All rights reserved.
#
# SPDX-License-Identifier: PolyForm-Strict-1.0.0
# See LICENSE in the project root for the full terms.
#
# Licensing inquiries: license@zombietech.biz
# =============================================================================

# ai: claude-opus-5-5 | 2026-11-13
"""Integration tests for the /email routes against the real test database.

Gmail, the OAuth token/credential files, and the scan thread are stubbed; the
module-level scan status dict is restored after each test via patch.dict."""
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest

from app import models
from app.config import settings

_SCAN_STATUS = "app.routes.email_scan._scan_status"
_TOKEN_FILE = "app.routes.email_scan.GOOGLE_TOKEN_FILE"


@pytest.fixture()
def token_file(tmp_path):
    """A present Gmail token file, so scan endpoints treat Gmail as connected."""
    path = tmp_path / "gmail_token.json"
    path.write_text("{}")
    with patch(_TOKEN_FILE, path):
        yield path


@pytest.fixture()
def idle_scan():
    with patch.dict(_SCAN_STATUS, {"running": False}):
        yield


@pytest.fixture()
def no_thread():
    """Replace the scan thread so starting a scan runs nothing in the background."""
    with patch("app.routes.email_scan.threading.Thread") as thread_cls:
        yield thread_cls


@pytest.fixture()
def make_candidate(db_session):
    counter = iter(range(1, 10_000))

    def _make(title: str = "Soup", status: str = "pending") -> models.EmailRecipeCandidate:
        n = next(counter)
        email = models.ScannedEmail(gmail_message_id=f"msg-{n}", subject=f"Subject {n}",
                                    sender="News <hi@a.com>", disposition="candidate")
        db_session.add(email)
        db_session.flush()
        cand = models.EmailRecipeCandidate(
            scanned_email_id=email.id, title=title, ingredients="water", instructions="boil",
            source_sender="News <hi@a.com>", source_subject=f"Subject {n}", status=status,
        )
        db_session.add(cand)
        db_session.commit()
        db_session.refresh(cand)
        return cand

    return _make


# ── Settings ──────────────────────────────────────────────────────────────────

def test_settings_defaults_when_nothing_stored(client):
    body = client.get("/email/settings").json()
    assert body["auto_import"] is True
    assert body["scan_inbox"] is False
    assert body["labels"]


def test_settings_patch_round_trips_and_updates_existing_rows(client, db_session):
    first = client.patch("/email/settings", json={"labels": ["Cooking", "Baking"], "max_per_folder": 10})
    assert first.status_code == 200
    second = client.patch("/email/settings", json={"labels": ["Dinner"], "auto_import": False})
    body = second.json()
    assert body["labels"] == ["Dinner"]
    assert body["auto_import"] is False
    assert body["max_per_folder"] == 10
    assert db_session.query(models.AppSetting).filter_by(key="email_scan_labels").count() == 1


def test_settings_max_per_folder_zero_means_unlimited_and_is_accepted(client):
    res = client.patch("/email/settings", json={"max_per_folder": 0})
    assert res.status_code == 200
    assert res.json()["max_per_folder"] == 0


@pytest.mark.parametrize("payload", [
    {"max_per_folder": -1},
    {"inbox_lookback_days": 0},
])
def test_settings_rejects_out_of_range_numbers(client, payload):
    assert client.patch("/email/settings", json=payload).status_code == 422


# ── Candidates ────────────────────────────────────────────────────────────────

def test_list_candidates_returns_only_pending(client, make_candidate):
    make_candidate("Keep me")
    make_candidate("Already done", status="imported")
    titles = [c["title"] for c in client.get("/email/candidates").json()]
    assert titles == ["Keep me"]


def test_discard_candidate_updates_candidate_and_email(client, db_session, make_candidate):
    cand = make_candidate()
    assert client.delete(f"/email/candidates/{cand.id}").status_code == 204
    db_session.expire_all()
    cand = db_session.get(models.EmailRecipeCandidate, cand.id)
    assert cand.status == "discarded"
    assert cand.scanned_email.disposition == "discarded"


def test_import_candidate_creates_recipe_once(client, db_session, make_candidate):
    cand = make_candidate("Lentil Soup")
    gmail = MagicMock()
    gmail.extract_html.return_value = ""   # no HTML -> no image candidates, no fetches
    with patch("app.routes.email_scan.GmailClient", gmail):
        res = client.post(f"/email/candidates/{cand.id}/import")
        assert res.status_code == 201
        assert res.json()["title"] == "Lentil Soup"
        assert res.json()["source_type"] == "email"

        again = client.post(f"/email/candidates/{cand.id}/import")
        assert again.status_code == 409

    db_session.expire_all()
    cand = db_session.get(models.EmailRecipeCandidate, cand.id)
    assert cand.status == "imported"
    assert cand.recipe_id == res.json()["id"]
    assert cand.scanned_email.disposition == "imported"
    assert db_session.query(models.Recipe).count() == 1


@pytest.mark.parametrize("method,path", [
    ("post", "/email/candidates/999999/import"),
    ("delete", "/email/candidates/999999"),
])
def test_missing_candidate_returns_404(client, method, path):
    assert getattr(client, method)(path).status_code == 404


# ── Scan control ──────────────────────────────────────────────────────────────

def test_start_scan_requires_gmail_token(client, tmp_path, idle_scan, no_thread):
    with patch(_TOKEN_FILE, tmp_path / "missing.json"):
        assert client.post("/email/scan").status_code == 401
    no_thread.assert_not_called()


def test_start_scan_starts_thread_with_stored_settings(client, db_session, token_file, idle_scan, no_thread):
    client.patch("/email/settings", json={"labels": ["Baking"], "max_per_folder": 5})
    res = client.post("/email/scan")
    assert res.status_code == 202
    no_thread.return_value.start.assert_called_once()
    args = no_thread.call_args.kwargs["args"]
    # ai: claude-opus-5-5 | 2026-11-16 -- args[0] is the household the scan runs for
    assert args[0] == db_session.info["tenant_id"]
    assert args[2] == ["Baking"] and args[5] == 5
    assert client.get("/email/scan/status").json()["running"] is True


def test_start_scan_while_running_returns_409(client, token_file, idle_scan, no_thread):
    assert client.post("/email/scan").status_code == 202
    assert client.post("/email/scan").status_code == 409
    no_thread.assert_called_once()


def test_bad_stored_setting_does_not_leave_scan_stuck_running(client, db_session, token_file,
                                                              idle_scan, no_thread):
    db_session.add(models.AppSetting(key="email_inbox_lookback_days", value="not-a-number"))
    db_session.commit()
    with pytest.raises(ValueError):
        client.post("/email/scan")
    assert client.get("/email/scan/status").json()["running"] is False


def test_reset_history_deletes_rows_and_is_blocked_while_running(client, db_session, make_candidate):
    make_candidate()
    make_candidate()
    with patch.dict(_SCAN_STATUS, {"running": True}):
        assert client.delete("/email/admin/reset-scan-history").status_code == 409
    with patch.dict(_SCAN_STATUS, {"running": False}):
        res = client.delete("/email/admin/reset-scan-history")
    assert res.json() == {"deleted": 2}
    assert db_session.query(models.EmailRecipeCandidate).count() == 0


# ── OAuth ─────────────────────────────────────────────────────────────────────

def test_connect_without_credentials_names_the_configured_file(client, tmp_path):
    missing = tmp_path / "google_credentials.json"
    with patch("app.services.google_oauth.GOOGLE_CREDENTIALS_FILE", missing):  # ai: claude-opus-5-5 | 2026-11-17
        res = client.get("/email/auth/connect")
    assert res.status_code == 400
    assert "google_credentials.json" in res.json()["detail"]


# ai: claude-opus-5-5 | 2026-11-17
def test_connect_redirects_to_the_bound_api_port(client, monkeypatch, fake_google_credentials):
    """The redirect URI follows API_PORT (the port main.py bound), not a fixed port."""
    monkeypatch.setattr(settings, "api_port", 54321)
    res = client.get("/email/auth/connect")
    assert res.status_code == 200
    query = parse_qs(urlparse(res.json()["auth_url"]).query)
    assert query["redirect_uri"] == ["http://localhost:54321/email/auth/callback"]
    assert query["code_challenge_method"] == ["S256"]


# ai: claude-opus-5-5 | 2026-11-17
def test_connect_without_api_port_explains_why(client, monkeypatch, fake_google_credentials):
    monkeypatch.setattr(settings, "api_port", None)
    res = client.get("/email/auth/connect")
    assert res.status_code == 400
    assert "API_PORT" in res.json()["detail"]


@pytest.mark.parametrize("query", ["?error=access_denied", "", "?code=abc&state=unknown-state"])
def test_callback_failures_redirect_with_error(client, query):
    res = client.get(f"/email/auth/callback{query}", follow_redirects=False)
    assert res.status_code in (302, 307)
    assert res.headers["location"].endswith("/add?email_auth=error")
