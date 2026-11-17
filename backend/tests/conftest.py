import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from alembic import command
from alembic.config import Config
from dotenv import dotenv_values
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parent.parent


# ai: claude-opus-5-5 | 2026-11-11
def _resolve_test_database_url() -> str:
    """TEST_DATABASE_URL wins if set; otherwise build it from POSTGRES_TEST_* vars.

    Only the POSTGRES_TEST_* keys are read from backend/.env (dotenv_values does
    not touch os.environ), so the real app credentials never enter the test process.
    """
    explicit = os.getenv("TEST_DATABASE_URL")
    if explicit:
        return explicit

    env_file = {
        k: v for k, v in dotenv_values(BACKEND_DIR / ".env").items()
        if k.startswith("POSTGRES_TEST_")
    }

    def _get(key: str) -> str | None:
        return os.getenv(key) or env_file.get(key)

    host, db, user = _get("POSTGRES_TEST_HOST"), _get("POSTGRES_TEST_DB"), _get("POSTGRES_TEST_USER")
    if not all([host, db, user]):
        raise RuntimeError(
            "No test database configured. Set TEST_DATABASE_URL, or POSTGRES_TEST_HOST, "
            "POSTGRES_TEST_DB, POSTGRES_TEST_USER (and optionally _PASSWORD, _PORT, "
            "_SSLMODE) in the environment or backend/.env."
        )
    sslmode = _get("POSTGRES_TEST_SSLMODE")
    return URL.create(
        "postgresql",
        username=user,
        password=_get("POSTGRES_TEST_PASSWORD"),
        host=host,
        port=int(_get("POSTGRES_TEST_PORT") or 5432),
        database=db,
        query={"sslmode": sslmode} if sslmode else {},
    ).render_as_string(hide_password=False)


TEST_DATABASE_URL = _resolve_test_database_url()


# ai: claude-opus-5-5 | 2026-11-11
# The session fixture drops the whole `public` schema and teardown deletes every
# row, so refuse to run against anything that isn't clearly a throwaway test DB.
_test_db_name = make_url(TEST_DATABASE_URL).database or ""
if not _test_db_name.lower().endswith("_test"):
    raise RuntimeError(
        f"Refusing to run tests against database '{_test_db_name}': "
        "TEST_DATABASE_URL must name a database ending in '_test'."
    )

# ai: claude-opus-5-5 | 2026-11-11
# Force test values (not setdefault) before any app module is imported. Process
# env vars take precedence over pydantic-settings' env_file, so these win over
# whatever is in backend/.env — the real Anthropic/MinIO credentials and the dev
# database never reach the test process.
_TEST_ENV = {
    "DATABASE_URL": TEST_DATABASE_URL,
    "ANTHROPIC_API_KEY": "test-key",
    "MINIO_ENDPOINT": "http://localhost:9000",
    "MINIO_ACCESS_KEY": "test-access-key",
    "MINIO_SECRET_KEY": "test-secret",
    "MINIO_BUCKET_NAME": "test-bucket",
    "SECRET_KEY": "test-secret-key",
    "CORS_ORIGINS": "http://localhost:5173",
}
os.environ.update(_TEST_ENV)

from app.config import settings  # noqa: E402
from app.database import (  # noqa: E402
    ROLE_OWNER, AuthContext, Base, TenantMembership, User, bind_tenant, current_tenant_id,
    get_current_auth, get_db,
)
from app.main import app  # noqa: E402
from app import models  # noqa: E402

_TestSession = sessionmaker(autocommit=False, autoflush=False)


# ai: claude-opus-5-5 | 2026-11-11
def alembic_config() -> Config:
    """Alembic config built in code (no ini file) so env.py skips fileConfig(),
    which would otherwise reconfigure logging and disable the app's loggers."""
    cfg = Config()
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return cfg


# ai: claude-opus-5-5 | 2026-11-11
@pytest.fixture(scope="session")
def engine():
    """Build the schema from the real Alembic migrations, not create_all, so the
    tests catch drift between the models and the migration chain.

    The schema is reset at the start of the session rather than torn down at the
    end, so an interrupted run never leaves the next one with a stale schema.
    alembic/env.py reads settings.database_url, which is the test DB (forced above).
    """
    db_engine = create_engine(TEST_DATABASE_URL)
    with db_engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    command.upgrade(alembic_config(), "head")
    yield db_engine
    db_engine.dispose()


# ai: claude-opus-5-5 | 2026-11-11
@pytest.fixture()
def db_session(engine):
    """Per-test session bound to the default household (the one allowlisted users
    join, and the one `client` acts for); isolation is by deleting all rows afterwards.

    A wrap-in-transaction-and-roll-back pattern doesn't work here without extra
    savepoint plumbing, because the routes call db.commit() themselves.
    """
    _TestSession.configure(bind=engine)
    session = _TestSession()
    # ai: claude-opus-5-5 | 2026-11-16
    # Migration 007 creates the default household, but per-test cleanup deletes
    # every row, so get-or-create it each time.
    tenant = session.scalar(select(models.Tenant).where(models.Tenant.slug == settings.default_tenant_slug))
    if tenant is None:
        tenant = models.Tenant(name="Test household", slug=settings.default_tenant_slug)
        session.add(tenant)
        session.commit()
    bind_tenant(session, tenant.id)
    yield session
    session.close()
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())


# ai: claude-opus-5-5 | 2026-11-16
@pytest.fixture()
def other_household(engine, db_session):
    """A session bound to a second household, for cross-household isolation tests."""
    session = _TestSession()
    tenant = models.Tenant(name="Other household", slug="other")
    session.add(tenant)
    session.commit()
    bind_tenant(session, tenant.id)
    yield session
    session.close()


# ai: claude-opus-5-5 | 2026-11-17
@pytest.fixture()
def signed_in_user(db_session) -> AuthContext:
    """A real user who owns the default household, as route tests act for them."""
    user = User(email="owner@example.com", display_name="Owner")
    db_session.add(user)
    db_session.flush()
    tenant_id = current_tenant_id(db_session)
    db_session.add(TenantMembership(tenant_id=tenant_id, user_id=user.id, role=ROLE_OWNER))
    db_session.commit()
    return AuthContext(user_id=user.id, tenant_id=tenant_id, role=ROLE_OWNER)


# ai: claude-opus-5-5 | 2026-11-17
@pytest.fixture()
def client(db_session, signed_in_user):
    """A client acting as signed_in_user, on the test's db_session. The sign-in
    flow itself (cookies, sessions) is tested without these overrides in test_auth.py."""
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_auth] = lambda: signed_in_user
    # The lifespan's MinIO check would sys.exit(1) — killing the whole run — when
    # MinIO isn't reachable. The DB check is left real: it hits the test DB.
    with patch("app.main.check_minio"), TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ai: claude-opus-5-5 | 2026-11-17
@pytest.fixture()
def anon_client(db_session):
    """A client with no dependency overrides: requests go through the real
    sign-in check and their own DB sessions (on the test database)."""
    with patch("app.main.check_minio"), TestClient(app) as c:
        yield c


@pytest.fixture()
def make_category(db_session):
    def _make_category(name: str = "Cuisine", slug: str = "cuisine"):
        category = models.TagCategory(name=name, slug=slug)
        db_session.add(category)
        db_session.commit()
        db_session.refresh(category)
        return category

    return _make_category


@pytest.fixture()
def make_tag(db_session):
    def _make_tag(name: str = "Italian", slug: str = "italian", category_id: int | None = None):
        tag = models.Tag(name=name, slug=slug, category_id=category_id)
        db_session.add(tag)
        db_session.commit()
        db_session.refresh(tag)
        return tag

    return _make_tag


@pytest.fixture()
def make_recipe(db_session):
    def _make_recipe(**kwargs):
        data = {
            "title": "Test Recipe",
            "description": None,
            "ingredients": None,
            "instructions": None,
            "servings": None,
            "prep_time": None,
            "cook_time": None,
            "source_url": None,
            "source_type": "manual",
            "image_key": None,
            "image_url": None,
            "thumbnail_key": None,
            "thumbnail_url": None,
        }
        tags = kwargs.pop("tags", [])
        data.update(kwargs)
        recipe = models.Recipe(**data)
        recipe.tags = tags
        db_session.add(recipe)
        db_session.commit()
        db_session.refresh(recipe)
        return recipe

    return _make_recipe


# ai: claude-opus-5-5 | 2026-11-17
@pytest.fixture()
def fake_google_credentials(tmp_path):
    """A Desktop-type OAuth client file, so OAuth tests never read the real one."""
    path = tmp_path / "google_credentials.json"
    path.write_text(json.dumps({"installed": {
        "client_id": "test-client.apps.googleusercontent.com",
        "client_secret": "test-secret",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost"],
    }}))
    with patch("app.services.google_oauth.GOOGLE_CREDENTIALS_FILE", path):
        yield path
