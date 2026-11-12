import os
from pathlib import Path
from unittest.mock import patch

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/recipe_test",
)

BACKEND_DIR = Path(__file__).resolve().parent.parent


# ai: claude-opus-5-5 | 2026-11-11
# The session fixture drops the whole `public` schema and teardown deletes every
# row, so refuse to run against anything that isn't clearly a throwaway test DB.
_test_db_name = make_url(TEST_DATABASE_URL).database or ""
if not _test_db_name.endswith("_test"):
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
    "MINIO_PUBLIC_URL": "http://localhost:9000/test-bucket",
    "SECRET_KEY": "test-secret-key",
    "CORS_ORIGINS": "http://localhost:5173",
    "CAPTURE_LISTENER_ENABLED": "false",
}
os.environ.update(_TEST_ENV)

from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app import models  # noqa: E402

_TestSession = sessionmaker(autocommit=False, autoflush=False)


# ai: claude-opus-5-5 | 2026-11-11
def _alembic_config() -> Config:
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
    command.upgrade(_alembic_config(), "head")
    yield db_engine
    db_engine.dispose()


# ai: claude-opus-5-5 | 2026-11-11
@pytest.fixture()
def db_session(engine):
    """Per-test session; isolation is by deleting all rows afterwards.

    A wrap-in-transaction-and-roll-back pattern doesn't work here without extra
    savepoint plumbing, because the routes call db.commit() themselves.
    """
    _TestSession.configure(bind=engine)
    session = _TestSession()
    yield session
    session.close()
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())


# ai: claude-opus-5-5 | 2026-11-11
@pytest.fixture()
def client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    # The lifespan's MinIO check would sys.exit(1) — killing the whole run — when
    # MinIO isn't reachable. The DB check is left real: it hits the test DB.
    with patch("app.main.check_minio"), TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


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
