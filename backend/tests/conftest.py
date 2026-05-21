import os

from dotenv import load_dotenv

load_dotenv(override=True)

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/recipe_test",
)

# Must be set before any app module is imported so pydantic-settings picks
# up the test values instead of the local .env file values.
os.environ.setdefault("DATABASE_URL", TEST_DATABASE_URL)
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("R2_ACCOUNT_ID", "test-account")
os.environ.setdefault("R2_ACCESS_KEY_ID", "test-access-key")
os.environ.setdefault("R2_SECRET_ACCESS_KEY", "test-secret")
os.environ.setdefault("R2_BUCKET_NAME", "test-bucket")
os.environ.setdefault("R2_PUBLIC_URL", "https://cdn.example.com")
os.environ.setdefault("MINIO_ENDPOINT", "http://localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "test-access-key")
os.environ.setdefault("MINIO_SECRET_KEY", "test-secret")
os.environ.setdefault("MINIO_BUCKET_NAME", "test-bucket")
os.environ.setdefault("MINIO_PUBLIC_URL", "http://localhost:9000/test-bucket")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:5173")

from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app import models  # noqa: E402

_TestSession = sessionmaker(autocommit=False, autoflush=False)


@pytest.fixture(scope="session")
def engine():
    db_engine = create_engine(TEST_DATABASE_URL)
    Base.metadata.create_all(db_engine)
    yield db_engine
    Base.metadata.drop_all(db_engine)


@pytest.fixture()
def db_session(engine):
    _TestSession.configure(bind=engine)
    session = _TestSession()
    yield session
    session.close()
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())


@pytest.fixture()
def client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
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
