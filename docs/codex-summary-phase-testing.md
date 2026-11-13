# Codex Summary: Phase Testing

> **Status (2026-11-13):** historical record. The PostgreSQL authentication failure
> described under *Verification Run* was resolved when the test DB URL moved to the
> `POSTGRES_TEST_*` settings (commit `ea0657c`); the suite now runs green. See the
> README's *Running Tests* section for current setup.

## Implemented Files

Created exactly the files requested by the phase spec:

- `backend/requirements-dev.txt`
- `backend/tests/__init__.py`
- `backend/tests/conftest.py`
- `backend/tests/test_health.py`
- `backend/tests/test_recipes.py`
- `backend/tests/test_tags.py`
- `backend/tests/test_search.py`
- `backend/tests/test_capture.py`

## What Was Implemented

- Added dev test dependencies in `backend/requirements-dev.txt`:
  - `pytest==8.3.5`
  - `pytest-cov==6.1.0`
  - `httpx==0.28.1`

- Built integration-test infrastructure in `backend/tests/conftest.py`:
  - Uses `TEST_DATABASE_URL` with fallback to `postgresql://postgres:postgres@localhost:5432/recipe_test`.
  - Session-scope schema setup/teardown using `Base.metadata.create_all/drop_all`.
  - Per-test transaction rollback fixture for DB isolation.
  - FastAPI `TestClient` fixture with `get_db` dependency override.
  - Helper factory fixtures:
    - `make_category`
    - `make_tag`
    - `make_recipe` (with defaults from the spec, commits to DB, supports tags)
  - Included a bootstrap layer in tests to align the current package export wiring (`app.database`, `app.models`, `app.schemas`) so the app can be imported and exercised via `TestClient` without changing application source files.

- Added endpoint coverage tests:
  - `test_health.py`: `/health` sanity check.
  - `test_recipes.py`: full CRUD behavior, pagination, tag assignment/swap, delete behavior with and without image, and storage delete call assertion.
  - `test_tags.py`: category/tag create/list/filter/delete behavior and ordering checks.
  - `test_search.py`: empty query behavior, title `ILIKE` matching, no-match case, single and AND tag filters, unknown slug handling, pagination, combined text+tag filter.
  - `test_capture.py`: URL/image capture success and failure paths with external service patching at usage sites:
    - `app.routes.capture.scraper_svc.fetch_page_text`
    - `app.routes.capture.vision_svc.extract_from_text`
    - `app.routes.capture.vision_svc.extract_from_image_bytes`
    - `app.routes.capture.storage_svc.upload_image`

## Verification Run

Executed:

```bash
cd backend
python -m pytest tests/ -v --cov=app --cov-report=term-missing
```

### Result

Test suite is implemented but could not complete in this environment due PostgreSQL authentication failure at import/startup:

- `psycopg2.OperationalError: password authentication failed for user "postgres"`
- Target: `localhost:5432` using fallback `recipe_test` URL.

## Environment Actions Performed

To enable test execution tooling in the project venv, installed:

- `pytest`
- `pytest-cov`
- `psycopg2-binary`
- `python-multipart`

These were environment installs only (no additional repo files were created beyond the requested phase files).
