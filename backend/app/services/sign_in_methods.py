# =============================================================================
# Copyright (c) 2026 ZombieTech LLC. All rights reserved.
#
# SPDX-License-Identifier: PolyForm-Strict-1.0.0
# See LICENSE in the project root for the full terms.
#
# Licensing inquiries: license@zombietech.biz
# =============================================================================
# ai: claude-opus-5-5 | 2026-11-19
"""
Sign-in methods: a password, passkeys and linked Google accounts, any mix of
them on one user.

Rules every service here keeps:

- A method is added only by a signed-in user (routes require a recent re-auth);
  two methods are never merged because they share an email address. The one
  exception is adopting a legacy Google user who has no methods at all.
- A user always keeps at least one method (MethodSummary.require_another_method).
- Failures don't reveal whether an address has an account: unknown email and
  wrong password behave identically, including timing (DUMMY_HASH).

Services flush, routes commit. Emails are returned as EmailToSend for the
route to send after committing, never sent while a DB session is open.

These services read only user-level tables (not TenantScoped), so they work on
a request session before it is bound to a household.
"""
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from webauthn import (
    generate_authentication_options, generate_registration_options, verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, options_to_json_dict
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria, AuthenticatorTransport, PublicKeyCredentialDescriptor,
    ResidentKeyRequirement, UserVerificationRequirement,
)

from app.config import settings
from app.database import (
    EMAIL_TOKEN_PASSWORD_RESET, EMAIL_TOKEN_REGISTER, PROVIDER_GOOGLE, EmailToken, LoginAttempt,
    PasswordCredential, User, UserIdentity, WebAuthnCredential, hash_session_token,
)
from app.schemas import LinkedGoogleOut, PasskeyOut, SignInMethodsOut
from app.services.account_email import EmailToSend, reset_password_link, verify_email_link
from app.services.google_oauth import GoogleIdentity, PendingStore
from app.services.passwords import DUMMY_HASH, PasswordHasherService
from app.services.sessions import SessionService

logger = logging.getLogger(__name__)

RP_NAME = "RecipeBox"
# TODO(per-ip-throttle): these limits are per email address only. Per-IP limits
# need uvicorn to trust Caddy's X-Forwarded-For first; until then every request
# arrives from the Docker gateway IP and an IP limit would lump all users together.
LOGIN_FAILURE_LIMIT = 5
LOGIN_FAILURE_WINDOW = timedelta(minutes=15)
EMAIL_LIMIT_PER_HOUR = 3
REGISTER_TOKEN_LIFETIME = timedelta(hours=24)
RESET_TOKEN_LIFETIME = timedelta(hours=1)
PASSKEY_FLOW_SECONDS = 300
_TRANSPORTS = frozenset(t.value for t in AuthenticatorTransport)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── errors ────────────────────────────────────────────────────────────────────

# ai: claude-opus-5-5 | 2026-11-19
class InvalidCredentialsError(Exception):
    """Wrong password, unknown email, or a passkey response that didn't verify.
    Deliberately one error, so callers can't tell which."""


# ai: claude-opus-5-5 | 2026-11-19
class ThrottledError(Exception):
    """Too many failed password attempts for this address recently."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(f"retry after {retry_after_seconds}s")
        self.retry_after_seconds = retry_after_seconds


# ai: claude-opus-5-5 | 2026-11-19
class InvalidTokenError(Exception):
    """An email link's token is unknown, already used, or expired."""


# ai: claude-opus-5-5 | 2026-11-19
class UnverifiedEmailError(Exception):
    """The password was right, but the account's email was never verified."""


# ai: claude-opus-5-5 | 2026-11-19
class LinkRequiredError(Exception):
    """A Google account's email matches a user who signs in another way. The
    user must sign in that way and link Google from Settings."""


# ai: claude-opus-5-5 | 2026-11-19
class AlreadyLinkedError(Exception):
    """This Google account is already linked (to this user or someone else)."""


# ai: claude-opus-5-5 | 2026-11-19
class LastMethodError(Exception):
    """Removing this method would leave the user no way to sign in."""


# ai: claude-opus-5-5 | 2026-11-19
class MethodNotFoundError(LookupError):
    """No such method on this user. Someone else's row is reported the same way."""


# ── shared ────────────────────────────────────────────────────────────────────

# ai: claude-opus-5-5 | 2026-11-19
class MethodSummary:
    """What sign-in methods a user has. The one place that counts them, so every
    "can't remove the last one" check agrees on what counts."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def count_methods(self, user_id: int) -> int:
        passwords = self._db.scalar(
            select(func.count()).select_from(PasswordCredential).where(PasswordCredential.user_id == user_id)
        )
        passkeys = self._db.scalar(
            select(func.count()).select_from(WebAuthnCredential).where(WebAuthnCredential.user_id == user_id)
        )
        identities = self._db.scalar(
            select(func.count()).select_from(UserIdentity).where(UserIdentity.user_id == user_id)
        )
        return (passwords or 0) + (passkeys or 0) + (identities or 0)

    def require_another_method(self, user_id: int) -> None:
        """Raise LastMethodError unless the user has a method besides the one being removed.

        Locks the user row first, so two removals racing from two tabs can't both
        see "2 methods" and together leave zero.
        """
        self._db.execute(select(User.id).where(User.id == user_id).with_for_update())
        if self.count_methods(user_id) <= 1:
            raise LastMethodError()

    def methods_for(self, user_id: int, reauth_valid_until: datetime) -> SignInMethodsOut:
        has_password = self._db.get(PasswordCredential, user_id) is not None
        passkeys = self._db.scalars(
            select(WebAuthnCredential).where(WebAuthnCredential.user_id == user_id).order_by(WebAuthnCredential.id)
        ).all()
        identities = self._db.scalars(
            select(UserIdentity)
            .where(UserIdentity.user_id == user_id, UserIdentity.provider == PROVIDER_GOOGLE)
            .order_by(UserIdentity.id)
        ).all()
        return SignInMethodsOut(
            has_password=has_password,
            passkeys=[PasskeyOut.model_validate(p) for p in passkeys],
            google=[LinkedGoogleOut.model_validate(i) for i in identities],
            reauth_valid_until=reauth_valid_until,
        )


# ── Google identities ─────────────────────────────────────────────────────────

# ai: claude-opus-5-5 | 2026-11-19
class IdentityService:
    """Finds users by a provider's stable subject id and links new identities."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def user_for_google(self, identity: GoogleIdentity) -> User | None:
        """The user this Google account signs in as, or None for someone new.

        A user created by the earlier Google flow has no stored subject. If the
        verified email matches such a user, and they have no other methods, adopt
        them (store the identity). Any other email match must link from Settings.
        """
        user = self._db.scalar(
            select(User)
            .join(UserIdentity, UserIdentity.user_id == User.id)
            .where(UserIdentity.provider == PROVIDER_GOOGLE, UserIdentity.subject == identity.subject)
        )
        if user is not None:
            return user
        user = self._db.scalar(select(User).where(User.email == identity.email))
        if user is None:
            return None
        if not identity.email_verified or MethodSummary(self._db).count_methods(user.id) > 0:
            raise LinkRequiredError()
        self._insert_google(user.id, identity)
        logger.info("Adopted legacy Google user %d by its verified email.", user.id)
        return user

    def link_google(self, user_id: int, identity: GoogleIdentity) -> UserIdentity:
        """Link a Google account to a signed-in user. AlreadyLinkedError if it is
        linked to anyone, this user included."""
        try:
            return self._insert_google(user_id, identity)
        except IntegrityError as exc:
            raise AlreadyLinkedError() from exc

    def create_google_identity(self, user_id: int, identity: GoogleIdentity) -> UserIdentity:
        """Record the Google account a brand-new user signed up with."""
        return self._insert_google(user_id, identity)

    def unlink(self, user_id: int, identity_id: int) -> None:
        row = self._db.scalar(
            select(UserIdentity).where(UserIdentity.id == identity_id, UserIdentity.user_id == user_id)
        )
        if row is None:
            raise MethodNotFoundError()
        MethodSummary(self._db).require_another_method(user_id)
        self._db.delete(row)
        self._db.flush()

    def _insert_google(self, user_id: int, identity: GoogleIdentity) -> UserIdentity:
        # Insert and let the unique constraint arbitrate, rather than SELECT-then-INSERT:
        # two callbacks for the same Google account can arrive together.
        # Raises IntegrityError when (google, subject) is already taken.
        row = UserIdentity(user_id=user_id, provider=PROVIDER_GOOGLE, subject=identity.subject, email=identity.email)
        with self._db.begin_nested():
            self._db.add(row)
            self._db.flush()
        return row


# ── passwords ─────────────────────────────────────────────────────────────────

# ai: claude-opus-5-5 | 2026-11-19
class PasswordService:
    """Password sign-in, registration by verified email, reset, set and remove."""

    def __init__(self, db: Session, hasher: PasswordHasherService | None = None) -> None:
        self._db = db
        self._hasher = hasher or PasswordHasherService()

    # sign-in and re-auth

    def authenticate(self, email: str, password: str) -> int:
        """Return the user id for a correct email + password.

        Raises ThrottledError, InvalidCredentialsError (unknown email and wrong
        password alike) or UnverifiedEmailError. Records the attempt either way;
        the caller must commit even when this raises InvalidCredentialsError, or
        the throttle never sees the failure.
        """
        user = self._db.scalar(select(User).where(User.email == email))
        return self._check(email, user, password)

    def authenticate_user(self, user_id: int, password: str) -> None:
        """Re-auth: the signed-in user's own password. Throttled like sign-in."""
        user = self._db.get(User, user_id)
        if user is None:
            raise InvalidCredentialsError()
        self._check(user.email, user, password)

    def _check(self, email: str, user: User | None, password: str) -> int:
        self._raise_if_throttled(email)
        credential = self._db.get(PasswordCredential, user.id) if user is not None else None
        # Always run one argon2 verify, so an unknown address costs the same time as a wrong password.
        ok = self._hasher.verify(credential.password_hash if credential else DUMMY_HASH, password)
        ok = ok and credential is not None
        self._db.add(LoginAttempt(email=email, succeeded=ok))
        self._db.flush()
        if not ok or user is None or credential is None:
            raise InvalidCredentialsError()
        if self._hasher.needs_rehash(credential.password_hash):
            credential.password_hash = self._hasher.hash(password)
            logger.info("Rehashed the password of user %d with current parameters.", user.id)
        if user.email_verified_at is None:
            raise UnverifiedEmailError()
        return user.id

    def _raise_if_throttled(self, email: str) -> None:
        # A soft limit: two attempts racing past the check can make it 6, not 5.
        # Good enough for slowing guessing; not worth serialising every sign-in.
        since = _utcnow() - LOGIN_FAILURE_WINDOW
        failures = self._db.scalars(
            select(LoginAttempt.created_at)
            .where(LoginAttempt.email == email, LoginAttempt.succeeded.is_(False), LoginAttempt.created_at > since)
            .order_by(LoginAttempt.created_at.desc())
            .limit(LOGIN_FAILURE_LIMIT)
        ).all()
        if len(failures) < LOGIN_FAILURE_LIMIT:
            return
        # Allowed again once the oldest of the last LIMIT failures leaves the window.
        reopens_at = failures[-1] + LOGIN_FAILURE_WINDOW
        retry_after = max(1, int((reopens_at - _utcnow()).total_seconds()) + 1)
        logger.info("Password sign-in throttled for an address (%d failures).", len(failures))
        raise ThrottledError(retry_after)

    # registration

    def start_registration(self, email: str, password: str, display_name: str | None) -> EmailToSend | None:
        """Validate the password and decide which email to send. None when this
        address has had its hourly share of emails (the route still says 202)."""
        self._hasher.validate_new(password, email)
        # Hash before branching, so both branches cost the same time.
        password_hash = self._hasher.hash(password)
        if not self._email_quota_left(email):
            return None
        user = self._db.scalar(select(User).where(User.email == email))
        if user is not None:
            token = self._new_token(EMAIL_TOKEN_PASSWORD_RESET, email, RESET_TOKEN_LIFETIME, user_id=user.id)
            return EmailToSend(kind="already_registered", to=email, link=reset_password_link(token))
        token = self._new_token(
            EMAIL_TOKEN_REGISTER, email, REGISTER_TOKEN_LIFETIME,
            password_hash=password_hash, display_name=display_name or None,
        )
        return EmailToSend(kind="verification", to=email, link=verify_email_link(token))

    def complete_registration(self, token: str) -> int:
        """Follow a verification link: create the user and their password. Returns the user id.

        If the address got an account in the meantime (e.g. through Google), the
        password is added to it only when it has none; otherwise InvalidTokenError.
        """
        row = self._consume(token, EMAIL_TOKEN_REGISTER)
        if row.password_hash is None:
            raise InvalidTokenError()
        now = _utcnow()
        user = User(email=row.email, display_name=row.display_name, email_verified_at=now)
        try:
            with self._db.begin_nested():
                self._db.add(user)
                self._db.flush()
        except IntegrityError:
            user = self._db.scalar(select(User).where(User.email == row.email).with_for_update())
            if user is None or self._db.get(PasswordCredential, user.id) is not None:
                raise InvalidTokenError()
            if user.email_verified_at is None:
                user.email_verified_at = now
        self._db.add(PasswordCredential(user_id=user.id, password_hash=row.password_hash))
        self._db.flush()
        logger.info("User %d completed password registration.", user.id)
        return user.id

    # reset

    def start_reset(self, email: str) -> EmailToSend | None:
        """A reset email for an existing account; None for an unknown address or
        an exhausted email quota (the route says 202 either way)."""
        user = self._db.scalar(select(User).where(User.email == email))
        if user is None or not self._email_quota_left(email):
            return None
        token = self._new_token(EMAIL_TOKEN_PASSWORD_RESET, email, RESET_TOKEN_LIFETIME, user_id=user.id)
        return EmailToSend(kind="password_reset", to=email, link=reset_password_link(token))

    def complete_reset(self, token: str, new_password: str) -> int:
        """Set a new password from a reset link and sign the user out everywhere.
        Raises InvalidTokenError or WeakPasswordError (the caller rolls back, so a
        weak password doesn't use up the link)."""
        row = self._consume(token, EMAIL_TOKEN_PASSWORD_RESET)
        user = self._db.get(User, row.user_id) if row.user_id is not None else None
        if user is None:
            raise InvalidTokenError()
        self._hasher.validate_new(new_password, user.email)
        self._store_password(user.id, new_password)
        if user.email_verified_at is None:
            # Following the link proved they read this inbox.
            user.email_verified_at = _utcnow()
        # Any other reset link still in that inbox is now stale.
        self._db.execute(
            update(EmailToken)
            .where(
                EmailToken.user_id == user.id,
                EmailToken.purpose == EMAIL_TOKEN_PASSWORD_RESET,
                EmailToken.used_at.is_(None),
            )
            .values(used_at=_utcnow())
        )
        SessionService(self._db).delete_all_for_user(user.id)
        self._db.flush()
        logger.info("User %d reset their password; all sessions ended.", user.id)
        return user.id

    # managing from Settings

    def set_password(self, user_id: int, new_password: str) -> None:
        user = self._db.get(User, user_id)
        if user is None:
            raise MethodNotFoundError()
        self._hasher.validate_new(new_password, user.email)
        self._store_password(user_id, new_password)
        self._db.flush()

    def remove_password(self, user_id: int) -> None:
        credential = self._db.get(PasswordCredential, user_id)
        if credential is None:
            raise MethodNotFoundError()
        MethodSummary(self._db).require_another_method(user_id)
        self._db.delete(credential)
        self._db.flush()

    # helpers

    def _store_password(self, user_id: int, password: str) -> None:
        password_hash = self._hasher.hash(password)
        credential = self._db.get(PasswordCredential, user_id)
        if credential is None:
            self._db.add(PasswordCredential(user_id=user_id, password_hash=password_hash))
        else:
            credential.password_hash = password_hash

    def _email_quota_left(self, email: str) -> bool:
        # Every account email carries a token, so the token table doubles as the send log.
        sent = self._db.scalar(
            select(func.count()).select_from(EmailToken)
            .where(EmailToken.email == email, EmailToken.created_at > _utcnow() - timedelta(hours=1))
        ) or 0
        if sent >= EMAIL_LIMIT_PER_HOUR:
            logger.warning("Account email not sent: hourly limit reached for an address.")
            return False
        return True

    def _new_token(
        self, purpose: str, email: str, lifetime: timedelta, *,
        user_id: int | None = None, password_hash: str | None = None, display_name: str | None = None,
    ) -> str:
        token = secrets.token_urlsafe(32)
        now = _utcnow()
        self._db.add(EmailToken(
            token_hash=hash_session_token(token), purpose=purpose, email=email, user_id=user_id,
            password_hash=password_hash, display_name=display_name, created_at=now, expires_at=now + lifetime,
        ))
        self._db.flush()
        return token

    def _consume(self, token: str, purpose: str) -> EmailToken:
        """Mark a token used, atomically: of two clicks racing, exactly one wins."""
        now = _utcnow()
        token_id = self._db.scalar(
            update(EmailToken)
            .where(
                EmailToken.token_hash == hash_session_token(token),
                EmailToken.purpose == purpose,
                EmailToken.used_at.is_(None),
                EmailToken.expires_at > now,
            )
            .values(used_at=now)
            .returning(EmailToken.id)
        )
        if token_id is None:
            raise InvalidTokenError()
        row = self._db.get(EmailToken, token_id)
        if row is None:
            raise InvalidTokenError()
        return row


# ── passkeys ──────────────────────────────────────────────────────────────────

# ai: claude-opus-5-5 | 2026-11-19
@dataclass(frozen=True)
class PasskeyFlow:
    """A WebAuthn ceremony in progress: the challenge we issued and for whom.
    user_id is None only for a sign-in, where the passkey itself names the user."""
    purpose: Literal["register", "authenticate"]
    challenge: bytes
    user_id: int | None


# One in-process store, like the Google OAuth state (single uvicorn worker).
_passkey_flows: PendingStore[PasskeyFlow] = PendingStore(ttl_seconds=PASSKEY_FLOW_SECONDS)


# ai: claude-opus-5-5 | 2026-11-19
class PasskeyService:
    """Registering passkeys and signing in with them (WebAuthn via py_webauthn).

    Resident keys are required, so sign-in needs no username: the authenticator
    offers the passkeys it holds for this site. Attestation is "none": we don't
    restrict which authenticator makes the passkey.
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    def registration_options(self, user: User) -> tuple[str, dict]:
        if user.webauthn_user_handle is None:
            user.webauthn_user_handle = secrets.token_bytes(32)
            self._db.flush()
        existing = self._db.scalars(select(WebAuthnCredential).where(WebAuthnCredential.user_id == user.id)).all()
        options = generate_registration_options(
            rp_id=settings.webauthn_rp_id,
            rp_name=RP_NAME,
            user_name=user.email,
            user_id=user.webauthn_user_handle,
            user_display_name=user.display_name or user.email,
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.REQUIRED,
                user_verification=UserVerificationRequirement.PREFERRED,
            ),
            # Stops the browser making a second passkey on an authenticator that has one.
            exclude_credentials=[_descriptor(c) for c in existing],
        )
        flow_id = _passkey_flows.put(PasskeyFlow("register", options.challenge, user.id))
        return flow_id, options_to_json_dict(options)

    def register(self, user_id: int, flow_id: str, credential: dict, name: str | None) -> WebAuthnCredential:
        flow = _passkey_flows.pop(flow_id)
        if flow is None or flow.purpose != "register" or flow.user_id != user_id:
            raise InvalidCredentialsError()
        try:
            verified = verify_registration_response(
                credential=credential,
                expected_challenge=flow.challenge,
                expected_rp_id=settings.webauthn_rp_id,
                expected_origin=settings.public_url,
            )
        except WebAuthnException as exc:
            logger.info("Passkey registration did not verify: %s", type(exc).__name__)
            raise InvalidCredentialsError() from exc
        now = _utcnow()
        row = WebAuthnCredential(
            user_id=user_id,
            credential_id=verified.credential_id,
            public_key=verified.credential_public_key,
            sign_count=verified.sign_count,
            transports=_transports_of(credential),
            name=name or f"Passkey {now:%Y-%m-%d}",
            backed_up=verified.credential_backed_up,
            created_at=now,
        )
        try:
            with self._db.begin_nested():
                self._db.add(row)
                self._db.flush()
        except IntegrityError as exc:
            # The same authenticator credential registered twice.
            raise InvalidCredentialsError() from exc
        logger.info("User %d registered passkey %d.", user_id, row.id)
        return row

    def authentication_options(self, user_id: int | None) -> tuple[str, dict]:
        """Sign-in (user_id None): no allow-list, the authenticator offers what it
        has. Re-auth: only the signed-in user's passkeys."""
        allow = None
        if user_id is not None:
            allow = [_descriptor(c) for c in self._db.scalars(
                select(WebAuthnCredential).where(WebAuthnCredential.user_id == user_id)
            )]
        options = generate_authentication_options(
            rp_id=settings.webauthn_rp_id,
            allow_credentials=allow,
            user_verification=UserVerificationRequirement.PREFERRED,
        )
        flow_id = _passkey_flows.put(PasskeyFlow("authenticate", options.challenge, user_id))
        return flow_id, options_to_json_dict(options)

    def authenticate(self, flow_id: str, credential: dict, expected_user_id: int | None) -> int:
        """Verify a passkey assertion and return its user's id.

        expected_user_id is None for sign-in, the session's user for re-auth; a
        flow started for one can't be finished as the other.
        """
        flow = _passkey_flows.pop(flow_id)
        if flow is None or flow.purpose != "authenticate" or flow.user_id != expected_user_id:
            raise InvalidCredentialsError()
        try:
            raw_id = base64url_to_bytes(credential["rawId"])
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidCredentialsError() from exc
        row = self._db.scalar(select(WebAuthnCredential).where(WebAuthnCredential.credential_id == raw_id))
        if row is None or (expected_user_id is not None and row.user_id != expected_user_id):
            raise InvalidCredentialsError()
        self._check_user_handle(row, credential)
        try:
            verified = verify_authentication_response(
                credential=credential,
                expected_challenge=flow.challenge,
                expected_rp_id=settings.webauthn_rp_id,
                expected_origin=settings.public_url,
                credential_public_key=row.public_key,
                credential_current_sign_count=row.sign_count,
            )
        except WebAuthnException as exc:
            # Includes py_webauthn's own refusal of a signature counter that didn't
            # go up (a possible cloned authenticator); its message says so, and
            # names no secrets, so it goes in the log as is.
            logger.warning("Passkey %d sign-in did not verify: %s: %s", row.id, type(exc).__name__, exc)
            raise InvalidCredentialsError() from exc
        row.sign_count = verified.new_sign_count
        row.backed_up = verified.credential_backed_up
        row.last_used_at = _utcnow()
        self._db.flush()
        return row.user_id

    def _check_user_handle(self, row: WebAuthnCredential, credential: dict) -> None:
        # py_webauthn doesn't check userHandle. A discoverable passkey returns the
        # handle it was created with; it must be this credential's owner's handle.
        response = credential.get("response")
        handle = response.get("userHandle") if isinstance(response, dict) else None
        if not handle:
            return
        owner_handle = self._db.scalar(select(User.webauthn_user_handle).where(User.id == row.user_id))
        try:
            matches = base64url_to_bytes(handle) == owner_handle
        except (TypeError, ValueError):
            matches = False
        if not matches:
            raise InvalidCredentialsError()

    def rename(self, user_id: int, credential_pk: int, name: str) -> WebAuthnCredential:
        row = self._owned(user_id, credential_pk)
        row.name = name
        self._db.flush()
        return row

    def remove(self, user_id: int, credential_pk: int) -> None:
        row = self._owned(user_id, credential_pk)
        MethodSummary(self._db).require_another_method(user_id)
        self._db.delete(row)
        self._db.flush()

    def _owned(self, user_id: int, credential_pk: int) -> WebAuthnCredential:
        row = self._db.scalar(
            select(WebAuthnCredential).where(WebAuthnCredential.id == credential_pk, WebAuthnCredential.user_id == user_id)
        )
        if row is None:
            raise MethodNotFoundError()
        return row


def _descriptor(row: WebAuthnCredential) -> PublicKeyCredentialDescriptor:
    return PublicKeyCredentialDescriptor(
        id=row.credential_id,
        transports=[AuthenticatorTransport(t) for t in row.transports if t in _TRANSPORTS],
    )


def _transports_of(credential: dict) -> list[str]:
    # Browser-supplied hints for re-auth's allowCredentials; keep only known values.
    response = credential.get("response")
    transports = response.get("transports") if isinstance(response, dict) else None
    if not isinstance(transports, list):
        return []
    return [t for t in transports if isinstance(t, str) and t in _TRANSPORTS]
