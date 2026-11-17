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
from datetime import datetime, timezone

from fastapi import Depends, Request
from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, event, select
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


# ai: claude-opus-5-5 | 2026-11-17
@dataclass(frozen=True)
class AuthContext:
    user_id: int
    tenant_id: int
    role: str


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
        select(UserSession.user_id, UserSession.tenant_id, TenantMembership.role)
        .join(
            TenantMembership,
            (TenantMembership.user_id == UserSession.user_id)
            & (TenantMembership.tenant_id == UserSession.tenant_id),
        )
        .where(UserSession.token_hash == hash_session_token(token), UserSession.expires_at > _utcnow())
    ).one_or_none()
    if row is None:
        raise NotSignedInError("Session expired, signed out, or no longer a member.")
    return AuthContext(user_id=row.user_id, tenant_id=row.tenant_id, role=row.role)


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
