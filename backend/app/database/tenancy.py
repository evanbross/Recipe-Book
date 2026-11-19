# =============================================================================
# Copyright (c) 2026 ZombieTech LLC. All rights reserved.
#
# SPDX-License-Identifier: PolyForm-Strict-1.0.0
# See LICENSE in the project root for the full terms.
#
# Licensing inquiries: license@zombietech.biz
# =============================================================================
# ai: claude-opus-5-5 | 2026-11-16
"""
Multi-tenancy: a tenant is a household. Every household-owned row carries
tenant_id, and every ORM session is bound to exactly one household.

Isolation is enforced centrally rather than per query, so a forgotten filter
can't leak another household's data:

- do_orm_execute adds ``tenant_id = <session's tenant>`` to every ORM SELECT,
  UPDATE and DELETE touching a TenantScoped model (including relationship
  loads and Session.get()).
- before_flush stamps tenant_id on new TenantScoped rows, and refuses a row
  that names a different household.
- Fail closed: a session with no tenant raises TenantNotSetError the moment
  it touches household data, instead of silently seeing every household.
  System work that genuinely spans households opts in with all_tenants_session().

Not covered (keep these explicit): Core statements such as pg_insert(...)
must set tenant_id themselves, and raw SQL text() is not filtered.

Requests act for the household of the signed-in user's session
(get_current_auth): the session cookie names a UserSession row, which names
the user and their active household. The lookup joins through
TenantMembership, so removing a member ends their access on the next request.
"""
import hashlib
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import (
    BigInteger, Boolean, DateTime, ForeignKey, Index, LargeBinary, String, UniqueConstraint, event, func,
    select, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import (
    Mapped, ORMExecuteState, Session, mapped_column, with_loader_criteria,
)

from app.config import settings
from app.database.database import Base, SessionLocal

TENANT_ID_KEY = "tenant_id"
_ALL_TENANTS_KEY = "all_tenants"


class TenantNotSetError(RuntimeError):
    """A session touched household data without being bound to a household."""


class TenantMismatchError(RuntimeError):
    """A new row names a different household than the session it was added to."""


# ai: claude-opus-5-5 | 2026-11-17
class NotSignedInError(RuntimeError):
    """The request has no valid sign-in session (main.py turns this into a 401)."""


ROLE_OWNER = "owner"
ROLE_MEMBER = "member"
SESSION_COOKIE_NAME = "recipe_session"
# ai: claude-opus-5-5 | 2026-11-19
# UserSession.auth_method / UserIdentity.provider values.
AUTH_METHOD_PASSWORD = "password"
AUTH_METHOD_PASSKEY = "passkey"
AUTH_METHOD_GOOGLE = "google"
PROVIDER_GOOGLE = AUTH_METHOD_GOOGLE
# EmailToken.purpose values.
EMAIL_TOKEN_REGISTER = "register"
EMAIL_TOKEN_PASSWORD_RESET = "password_reset"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Tenant(Base):
    """A household: the unit that owns recipes, tags, settings and email state."""
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class User(Base):
    """A person who can sign in. Belongs to households through TenantMembership."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)   # stored lower-cased
    display_name: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    # ai: claude-opus-5-5 | 2026-11-19
    # When the user proved they own the email address (Google said so, or they
    # followed a verification link). Password sign-in requires it.
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Random 32 bytes passkeys know the account by; created with the first passkey.
    # Never the numeric id, which would leak account order to the authenticator.
    webauthn_user_handle: Mapped[bytes | None] = mapped_column(LargeBinary, unique=True)


class TenantMembership(Base):
    """User <-> household, with the user's role in that household."""
    __tablename__ = "tenant_memberships"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True)
    role: Mapped[str] = mapped_column(String(20), default="member")   # "owner" | "member"
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


# ai: claude-opus-5-5 | 2026-11-17
class UserSession(Base):
    """A signed-in browser. The cookie holds a random token; only its SHA-256
    is stored, so a database leak doesn't hand out live sessions."""
    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # The household this session acts for. Not TenantScoped: it is looked up
    # before the request knows its household.
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # ai: claude-opus-5-5 | 2026-11-19
    # How this session signed in ("password" | "passkey" | "google"), and when it
    # last proved who the user is. Changing sign-in methods needs a recent proof.
    auth_method: Mapped[str] = mapped_column(String(20), server_default=AUTH_METHOD_GOOGLE)
    authenticated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now(),
    )


# ai: claude-opus-5-5 | 2026-11-19
class UserIdentity(Base):
    """An outside account (Google today) linked to a user, found by the provider's
    stable subject id, never by email."""
    __tablename__ = "user_identities"
    __table_args__ = (UniqueConstraint("provider", "subject", name="user_identities_provider_subject_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(20))
    subject: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(320))   # at link time, lower-cased; display only
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


# ai: claude-opus-5-5 | 2026-11-19
class PasswordCredential(Base):
    """A user's one password, as an argon2id hash."""
    __tablename__ = "password_credentials"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


# ai: claude-opus-5-5 | 2026-11-19
class WebAuthnCredential(Base):
    """A passkey: the public half of a key pair held by the user's authenticator."""
    __tablename__ = "webauthn_credentials"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    credential_id: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    public_key: Mapped[bytes] = mapped_column(LargeBinary)
    sign_count: Mapped[int] = mapped_column(BigInteger)
    transports: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    name: Mapped[str] = mapped_column(String(100))
    backed_up: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ai: claude-opus-5-5 | 2026-11-19
class EmailToken(Base):
    """A single-use link sent by email (verify a new account, reset a password).
    Only the SHA-256 of the token is stored; the raw token exists only in the email."""
    __tablename__ = "email_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    purpose: Mapped[str] = mapped_column(String(20))   # EMAIL_TOKEN_REGISTER | EMAIL_TOKEN_PASSWORD_RESET
    email: Mapped[str] = mapped_column(String(320), index=True)   # lower-cased
    # Set for password resets; NULL for registrations (the user doesn't exist yet).
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # Registration only: what was chosen at sign-up, so it needn't be typed again.
    password_hash: Mapped[str | None] = mapped_column(String(255))
    display_name: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ai: claude-opus-5-5 | 2026-11-19
class LoginAttempt(Base):
    """One password sign-in attempt, for throttling. Recorded for unknown
    addresses too, so the throttle doesn't reveal which addresses have accounts."""
    __tablename__ = "login_attempts"
    __table_args__ = (Index("ix_login_attempts_email_created_at", "email", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str] = mapped_column(String(320))   # lower-cased
    succeeded: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


# ai: claude-opus-5-5 | 2026-11-17
def hash_session_token(token: str) -> str:
    # The token is 256 random bits, so a fast hash is enough: there is nothing to brute-force.
    return hashlib.sha256(token.encode()).hexdigest()


class TenantScoped:
    """Mixin for household-owned tables. Not indexed here: each table indexes
    tenant_id itself, or leads a composite unique/PK with it, so no table gets
    a redundant second index."""

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))


# ai: claude-opus-5-5 | 2026-11-17
class TenantInvite(TenantScoped, Base):
    """An email invited to join a household. Accepted (and deleted) the next
    time that email signs in with Google."""
    __tablename__ = "tenant_invites"
    __table_args__ = (UniqueConstraint("tenant_id", "email", name="tenant_invites_tenant_email_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), index=True)   # stored lower-cased
    invited_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


# ── session binding ───────────────────────────────────────────────────────────

def bind_tenant(db: Session, tenant_id: int) -> Session:
    db.info[TENANT_ID_KEY] = tenant_id
    db.info.pop(_ALL_TENANTS_KEY, None)
    return db


def current_tenant_id(db: Session) -> int:
    """The household this session is bound to. Raises TenantNotSetError if unbound."""
    tenant_id = db.info.get(TENANT_ID_KEY)
    if tenant_id is None:
        raise TenantNotSetError("This session is not bound to a household.")
    return tenant_id


def resolve_default_tenant_id(db: Session) -> int:
    tenant_id = db.scalar(select(Tenant.id).where(Tenant.slug == settings.default_tenant_slug))
    if tenant_id is None:
        raise TenantNotSetError(
            f"Default household '{settings.default_tenant_slug}' does not exist; run the migrations."
        )
    return tenant_id


# ai: claude-opus-5-5 | 2026-11-19
@dataclass(frozen=True)
class AuthContext:
    user_id: int
    tenant_id: int
    role: str
    session_id: int
    authenticated_at: datetime   # when this session last proved who the user is

    @property
    def reauth_valid_until(self) -> datetime:
        return self.authenticated_at + timedelta(minutes=settings.reauth_window_minutes)


def get_request_session() -> Generator[Session, None, None]:
    """FastAPI dependency: the request's one DB session, not yet bound to a household.
    FastAPI caches it per request, so get_current_auth and get_db share it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_auth(request: Request, db: Session = Depends(get_request_session)) -> AuthContext:
    """FastAPI dependency: who is signed in, and the household they act for."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise NotSignedInError("No session cookie.")
    row = db.execute(
        select(  # ai: claude-opus-5-5 | 2026-11-19
            UserSession.id, UserSession.user_id, UserSession.tenant_id, UserSession.authenticated_at,
            TenantMembership.role,
        )
        .join(
            TenantMembership,
            (TenantMembership.user_id == UserSession.user_id)
            & (TenantMembership.tenant_id == UserSession.tenant_id),
        )
        .where(UserSession.token_hash == hash_session_token(token), UserSession.expires_at > _utcnow())
    ).one_or_none()
    if row is None:
        raise NotSignedInError("Session expired, signed out, or no longer a member.")
    return AuthContext(  # ai: claude-opus-5-5 | 2026-11-19
        user_id=row.user_id, tenant_id=row.tenant_id, role=row.role,
        session_id=row.id, authenticated_at=row.authenticated_at,
    )


# ai: claude-opus-5-5 | 2026-11-19
REAUTH_REQUIRED = "reauth_required"   # the frontend keys on this exact detail string


# ai: claude-opus-5-5 | 2026-11-19
def require_recent_auth(auth: AuthContext = Depends(get_current_auth)) -> AuthContext:
    """FastAPI dependency: the signed-in user proved who they are within the
    re-auth window. Guards every change to how someone signs in, so a session
    left open on a shared computer can't add the attacker's passkey."""
    if _utcnow() > auth.reauth_valid_until:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=REAUTH_REQUIRED)
    return auth


# ai: claude-opus-5-5 | 2026-11-19
def require_app_origin(request: Request, _auth: AuthContext = Depends(get_current_auth)) -> None:
    """FastAPI dependency: the request comes from the app's own pages.

    The global origin middleware lets chrome-extension:// origins write, which
    recipe capture needs; changing sign-in methods must not be reachable that way.
    Browsers send Origin on every cross-origin and every same-origin non-GET
    fetch, so a missing Origin is refused too.

    Depends on get_current_auth so a signed-out request gets 401, not this 403:
    route-level dependencies run before the endpoint's own.
    """
    if request.headers.get("origin") != settings.public_url:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="untrusted_origin")


def get_db(
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_request_session),
) -> Session:
    """FastAPI dependency: the request's session, bound to the signed-in household."""
    return bind_tenant(db, auth.tenant_id)


@contextmanager
def tenant_session(tenant_id: int) -> Iterator[Session]:
    """A session bound to a household, for work outside a request (background threads)."""
    db = bind_tenant(SessionLocal(), tenant_id)
    try:
        yield db
    finally:
        db.close()


@contextmanager
def all_tenants_session() -> Iterator[Session]:
    """An explicitly unscoped session, for system work that spans households."""
    db = SessionLocal()
    db.info[_ALL_TENANTS_KEY] = True
    try:
        yield db
    finally:
        db.close()


# ── enforcement ───────────────────────────────────────────────────────────────

def _touches_tenant_data(state: ORMExecuteState) -> bool:
    return any(issubclass(m.class_, TenantScoped) for m in state.all_mappers)


@event.listens_for(Session, "do_orm_execute")
def _scope_to_tenant(state: ORMExecuteState) -> None:
    if not (state.is_select or state.is_update or state.is_delete):
        return
    if state.is_column_load or state.is_relationship_load:
        # Already covered: the criteria below propagate to these loaders.
        return
    if state.session.info.get(_ALL_TENANTS_KEY):
        return
    tenant_id = state.session.info.get(TENANT_ID_KEY)
    if tenant_id is None:
        if _touches_tenant_data(state):
            raise TenantNotSetError("Query on household data from a session not bound to a household.")
        return
    state.statement = state.statement.options(
        with_loader_criteria(
            TenantScoped,
            lambda cls: cls.tenant_id == tenant_id,
            include_aliases=True,
        )
    )


@event.listens_for(Session, "before_flush")
def _stamp_tenant(session: Session, _flush_context: object, _instances: object) -> None:
    tenant_id = session.info.get(TENANT_ID_KEY)
    for obj in session.new:
        if not isinstance(obj, TenantScoped):
            continue
        if obj.tenant_id is None:
            if tenant_id is None:
                raise TenantNotSetError(f"New {type(obj).__name__} has no household and the session has none.")
            obj.tenant_id = tenant_id
        elif tenant_id is not None and obj.tenant_id != tenant_id:
            raise TenantMismatchError(
                f"New {type(obj).__name__} belongs to household {obj.tenant_id}, session is bound to {tenant_id}."
            )
