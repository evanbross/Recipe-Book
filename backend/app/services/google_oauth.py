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
Google OAuth plumbing shared by sign-in (routes/auth.py) and the Gmail
connection (routes/email_scan.py).

The OAuth client in backend/credentials/google_credentials.json is a Desktop
client, so Google only redirects back to http://localhost:<port>. The port is
the one uvicorn actually bound (settings.api_port, passed in by main.py), never
a fixed number: a fixed port silently drifts from the real one when main.py
picks a free port at startup.
"""
import secrets
import threading
import time
from dataclasses import dataclass

from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import id_token as google_id_token
from google_auth_oauthlib.flow import Flow

from app.config import GOOGLE_CREDENTIALS_FILE, settings

SIGN_IN_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]


class OAuthNotConfiguredError(RuntimeError):
    """The server can't start an OAuth flow (missing credentials file or API_PORT)."""


class PendingStore[T]:
    """Short-lived, single-use values keyed by a random token.

    Used for OAuth state (state -> PKCE verifier and context) and one-time
    sign-in tickets. In-process: fine for the single uvicorn worker this app
    runs, and an entry lost to a restart only means the user clicks sign-in again.
    """

    def __init__(self, ttl_seconds: float) -> None:
        self._ttl = ttl_seconds
        self._items: dict[str, tuple[float, T]] = {}
        self._lock = threading.Lock()

    def put(self, value: T) -> str:
        """Store value under a new random token and return the token."""
        token = secrets.token_urlsafe(32)
        self.add(token, value)
        return token

    def add(self, key: str, value: T) -> None:
        """Store value under a key the caller already has (e.g. the OAuth state
        authorization_url() generated alongside the PKCE verifier)."""
        now = time.monotonic()
        with self._lock:
            # Drop abandoned entries (a user who never finished the Google page).
            self._items = {k: v for k, v in self._items.items() if v[0] > now}
            self._items[key] = (now + self._ttl, value)

    def pop(self, token: str) -> T | None:
        """The value for token if it exists and hasn't expired; consumes it either way."""
        with self._lock:
            entry = self._items.pop(token, None)
        if entry is None or entry[0] <= time.monotonic():
            return None
        return entry[1]


def loopback_redirect_uri(path: str) -> str:
    if settings.api_port is None:
        raise OAuthNotConfiguredError(
            "API_PORT is not set, so Google can't redirect back to the API. Start the app "
            "with main.py, or set API_PORT to the port uvicorn listens on."
        )
    return f"http://localhost:{settings.api_port}{path}"


def build_flow(scopes: list[str], redirect_path: str) -> Flow:
    if not GOOGLE_CREDENTIALS_FILE.exists():
        raise OAuthNotConfiguredError(
            f"{GOOGLE_CREDENTIALS_FILE.name} not found in backend/credentials/. "
            "Download OAuth2 Desktop credentials from Google Cloud Console and save them there."
        )
    return Flow.from_client_secrets_file(
        str(GOOGLE_CREDENTIALS_FILE),
        scopes=scopes,
        redirect_uri=loopback_redirect_uri(redirect_path),
    )


@dataclass(frozen=True)
class GoogleIdentity:
    email: str          # lower-cased
    email_verified: bool
    name: str | None


def identity_from_flow(flow: Flow) -> GoogleIdentity:
    """Verify the ID token from a completed sign-in flow and return who signed in.

    Raises ValueError for a token that fails verification (signature, audience,
    issuer, expiry) and google.auth.exceptions.TransportError if Google's signing
    keys can't be fetched.
    """
    raw = flow.credentials.id_token
    if not raw:
        raise ValueError("Google returned no ID token; was the openid scope requested?")
    claims = google_id_token.verify_oauth2_token(raw, GoogleAuthRequest(), flow.client_config["client_id"])
    email = claims.get("email")
    if not email:
        raise ValueError("Google ID token has no email claim.")
    return GoogleIdentity(
        email=email.strip().lower(),
        email_verified=bool(claims.get("email_verified")),
        name=claims.get("name"),
    )
