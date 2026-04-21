# Phase: Backend Testing

**Project:** Recipe App  
**Stack:** FastAPI + SQLAlchemy 2.x + PostgreSQL  
**Goal:** Implement a pytest-based integration test suite for all backend routes. No frontend tests in this phase.

---

## Overview

The test suite hits all HTTP endpoints using FastAPI's `TestClient` (synchronous, no event loop required). A real PostgreSQL test database is used — do not use SQLite. The `search_vector` column uses PostgreSQL's `TSVECTOR` type and `plainto_tsquery`, which are incompatible with SQLite.

External services (Anthropic Claude API, Cloudflare R2, web scraper) are mocked at the function level using `unittest.mock.patch`.

---

## Files to Create

```
backend/
  requirements-dev.txt          ← new file
  tests/
    __init__.py                 ← empty
    conftest.py                 ← fixtures: DB setup, TestClient, helper factories
    test_health.py              ← sanity check
    test_recipes.py             ← CRUD routes
    test_tags.py                ← tag + category routes
    test_search.py              ← search + filter logic
    test_capture.py             ← capture/url and capture/image routes
```

Do not create any other files or directories. Do not modify any existing files except `requirements-dev.txt` (which is new).

---

## `requirements-dev.txt`

```
pytest==8.3.5
pytest-cov==6.1.0
httpx==0.28.1
```

`httpx` is already in `requirements.txt` (runtime dep for the scraper), but it is listed here too so the dev install is self-contained.

---

## `tests/conftest.py`

This is the most critical file. Get every detail right.

### Database setup

- Read the `DATABASE_URL` from the environment variable `TEST_DATABASE_URL`. If not set, fall back to `postgresql://postgres:postgres@localhost:5432/recipe_test`.
- Create a SQLAlchemy engine from that URL.
- Call `Base.metadata.create_all(bind=engine)` once at session scope (before any test runs).
- Call `Base.metadata.drop_all(bind=engine)` once at session scope (after all tests complete).
- For each individual test, wrap the session in a transaction that is rolled back after the test. This keeps tests isolated without recreating the schema on every test.

The per-test DB isolation pattern:
```python
@pytest.fixture()
def db_session(engine):
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    yield session
    session.close()
    transaction.rollback()
    connection.close()
```

### TestClient setup

Override FastAPI's `get_db` dependency to use the test session:

```python
@pytest.fixture()
def client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
```

Import `app` from `app.main` and `get_db` from `app.database`.

### Helper factories

Include these fixtures to create test data without going through the HTTP layer:

```python
@pytest.fixture()
def make_category(db_session):
    """Returns a callable: make_category(name='Cuisine', slug='cuisine') -> TagCategory"""

@pytest.fixture()
def make_tag(db_session):
    """Returns a callable: make_tag(name='Italian', slug='italian', category_id=None) -> Tag"""

@pytest.fixture()
def make_recipe(db_session):
    """Returns a callable: make_recipe(**kwargs) -> Recipe. Sensible defaults for all fields."""
```

Default values for `make_recipe`:
- `title`: `"Test Recipe"`
- `source_type`: `"manual"`
- All other optional fields: `None`
- `tags`: `[]`

---

## `tests/test_health.py`

One test: `GET /health` returns 200 and `{"status": "ok"}`.

---

## `tests/test_recipes.py`

### `test_list_recipes_empty`
- `GET /recipes` with no data returns `200` and `[]`.

### `test_list_recipes_returns_items`
- Create 3 recipes via `make_recipe`.
- `GET /recipes` returns 200 and a list of 3 items.
- Each item has `id`, `title`, `source_type`, `tags`, `created_at`.
- Verify these fields come from `RecipeListOut` — do **not** expect `ingredients` or `instructions` (those are not in `RecipeListOut`).

### `test_list_recipes_pagination`
- Create 5 recipes. `GET /recipes?skip=2&limit=2` returns exactly 2 items.

### `test_get_recipe_success`
- Create a recipe via `make_recipe`. `GET /recipes/{id}` returns 200 with full `RecipeOut` fields including `ingredients` and `instructions`.

### `test_get_recipe_not_found`
- `GET /recipes/99999` returns 404.

### `test_create_recipe_minimal`
- `POST /recipes` with `{"title": "My Recipe", "source_type": "manual"}` returns 201.
- Response contains `id`, `title`, `tags: []`.

### `test_create_recipe_with_tags`
- Create a tag via `make_tag`. `POST /recipes` with `tag_ids: [tag.id]`.
- Response `tags` list contains the tag.

### `test_update_recipe_fields`
- Create a recipe. `PATCH /recipes/{id}` with `{"title": "Updated"}`.
- Returns 200. Response `title` equals `"Updated"`.

### `test_update_recipe_swap_tags`
- Create a recipe with tag A. `PATCH /recipes/{id}` with `tag_ids: [tag_b.id]`.
- Response `tags` contains only tag B.

### `test_update_recipe_not_found`
- `PATCH /recipes/99999` with `{"title": "x"}` returns 404.

### `test_delete_recipe_no_image`
- Create a recipe (no `image_key`). `DELETE /recipes/{id}` returns 204.
- Subsequent `GET /recipes/{id}` returns 404.

### `test_delete_recipe_with_image`
- Create a recipe with `image_key="originals/abc.jpg"` and `thumbnail_key="thumbnails/abc.jpg"`.
- Patch `app.services.storage.delete_image` so it does nothing.
- `DELETE /recipes/{id}` returns 204.
- Assert `delete_image` was called once with `("originals/abc.jpg", "thumbnails/abc.jpg")`.

### `test_delete_recipe_not_found`
- `DELETE /recipes/99999` returns 404.

---

## `tests/test_tags.py`

### `test_list_categories_empty`
- `GET /tags/categories` with no data returns 200 and `[]`.

### `test_create_category`
- `POST /tags/categories` with `{"name": "Cuisine", "slug": "cuisine"}` returns 201.
- Response has `id`, `name`, `slug`.

### `test_list_categories`
- Create 2 categories via `make_category`. `GET /tags/categories` returns both, ordered by name.

### `test_create_tag_no_category`
- `POST /tags` with `{"name": "Vegan", "slug": "vegan"}` returns 201.
- Response `category` is `null`.

### `test_create_tag_with_category`
- Create a category. `POST /tags` with `category_id` set. Response `category.id` matches.

### `test_list_tags`
- Create 3 tags (2 in category A, 1 in category B). `GET /tags` returns all 3.

### `test_list_tags_filtered_by_category`
- Same setup. `GET /tags?category_id={A.id}` returns exactly 2 items.

### `test_delete_tag`
- Create a tag. `DELETE /tags/{id}` returns 204. Verify it's gone via `GET /tags`.

### `test_delete_tag_not_found`
- `DELETE /tags/99999` returns 404.

---

## `tests/test_search.py`

> Note: `search_vector` is a PostgreSQL TSVECTOR column populated by a DB trigger or application code. In tests, it will be `NULL` for all recipes created via `make_recipe`, so full-text vector search won't match. The title `ILIKE` fallback in the search route will be used for text matching in tests. This is intentional and correct — do not attempt to populate `search_vector` manually.

### `test_search_empty_query`
- Create 2 recipes. `GET /search?q=` (empty) returns both. `total` equals 2.

### `test_search_by_title_ilike`
- Create a recipe with `title="Spicy Thai Noodles"`.
- `GET /search?q=thai` returns 1 result with the matching title.
- `total` equals 1.

### `test_search_no_match`
- Create a recipe with `title="Chocolate Cake"`.
- `GET /search?q=pizza` returns `total: 0` and `results: []`.

### `test_search_tag_filter_single`
- Create tag `italian`. Create 2 recipes: one tagged `italian`, one not.
- `GET /search?tags=italian` returns only the tagged recipe.

### `test_search_tag_filter_and_logic`
- Create tags `italian` and `vegetarian`. Create 3 recipes:
  - Recipe A: both tags
  - Recipe B: only `italian`
  - Recipe C: only `vegetarian`
- `GET /search?tags=italian,vegetarian` returns only recipe A.

### `test_search_tag_unknown_slug_ignored`
- Create 2 recipes (no tags). `GET /search?tags=nonexistent` returns both recipes (unknown slugs are silently skipped).

### `test_search_pagination`
- Create 5 recipes with distinct titles all containing "soup".
- `GET /search?q=soup&page=1&page_size=2` returns 2 results, `total` equals 5.
- `GET /search?q=soup&page=3&page_size=2` returns 1 result.

### `test_search_combined_text_and_tag`
- Create tag `asian`. Create recipe A (title "Ramen", tag `asian`) and recipe B (title "Ramen", no tag).
- `GET /search?q=ramen&tags=asian` returns only recipe A.

---

## `tests/test_capture.py`

Both capture routes call external services. Patch them at the module path where they are *used*, not where they are defined:

- Scraper: `app.routes.capture.scraper_svc.fetch_page_text`
- Vision (text): `app.routes.capture.vision_svc.extract_from_text`
- Vision (image): `app.routes.capture.vision_svc.extract_from_image_bytes`
- Storage: `app.routes.capture.storage_svc.upload_image`

### Shared fixture: `capture_result`

```python
@pytest.fixture()
def capture_result():
    return CaptureResult(
        title="Mocked Recipe",
        description="A test recipe",
        ingredients="1 cup flour\n2 eggs",
        instructions="Mix and bake.",
        servings="4",
        prep_time="10 minutes",
        cook_time="30 minutes",
    )
```

Import `CaptureResult` from `app.schemas`.

### `test_capture_url_success`
- Patch `fetch_page_text` to return `"some page text"`.
- Patch `extract_from_text` to return `capture_result`.
- `POST /capture/url` with `{"url": "https://example.com/recipe"}`.
- Returns 200. Response `title` equals `"Mocked Recipe"`, `source_type` equals `"web"`, `source_url` equals `"https://example.com/recipe"`.

### `test_capture_url_scraper_failure`
- Patch `fetch_page_text` to raise `Exception("timeout")`.
- `POST /capture/url` with any URL returns 422. Response `detail` contains `"Failed to fetch URL"`.

### `test_capture_url_vision_failure`
- Patch `fetch_page_text` to return `"text"`.
- Patch `extract_from_text` to raise `Exception("Claude error")`.
- Returns 422. Response `detail` contains `"Claude extraction failed"`.

### `test_capture_url_with_tags`
- Create a tag via `make_tag`. Patch both services to return valid data.
- `POST /capture/url` with `{"url": "...", "tag_ids": [tag.id]}`.
- Response `tags` list contains the tag.

### `test_capture_image_success`
- Patch `extract_from_image_bytes` to return `capture_result`.
- Patch `upload_image` to return:
  ```python
  {
      "image_key": "originals/test.jpg",
      "image_url": "https://cdn.example.com/originals/test.jpg",
      "thumbnail_key": "thumbnails/test.jpg",
      "thumbnail_url": "https://cdn.example.com/thumbnails/test.jpg",
  }
  ```
- `POST /capture/image` as multipart form with a small JPEG bytes payload and `content_type="image/jpeg"`.
- Returns 200. Response `source_type` equals `"image"`, `image_url` is populated.

### `test_capture_image_unsupported_media_type`
- `POST /capture/image` with `content_type="application/pdf"`.
- Returns 415. Response `detail` contains `"Unsupported media type"`.

### `test_capture_image_vision_failure`
- Patch `extract_from_image_bytes` to raise `Exception("vision error")`.
- Returns 422. Response `detail` contains `"Claude extraction failed"`.

### `test_capture_image_storage_failure`
- Patch `extract_from_image_bytes` to return valid `capture_result`.
- Patch `upload_image` to raise `Exception("R2 error")`.
- Returns 500. Response `detail` contains `"Storage upload failed"`.

---

## Key Constraints

1. **Never use SQLite.** `TSVECTOR`, `GIN` indexes, and `plainto_tsquery` require PostgreSQL.
2. **Never mock the database.** Use the real test PostgreSQL via the session rollback pattern in `conftest.py`.
3. **Mock only at the usage site.** Patch `app.routes.capture.vision_svc.extract_from_text`, not `app.services.vision.extract_from_text`.
4. **Check response fields against the actual schema.** `RecipeListOut` does not have `ingredients` or `instructions`. `RecipeOut` does. Verify before asserting.
5. **SQLAlchemy 2.x count pattern.** If any test or fixture needs a count query, use `select(func.count()).select_from(q.subquery())` — never `.with_only_columns(func.count())`.
6. **No bare `pass` in stubs.** If any fixture or helper is not yet implemented, use `raise NotImplementedError`.
7. **Do not populate `search_vector` in tests.** Rely on the `ILIKE` title fallback that already exists in the search route. Testing the tsvector path would require a DB trigger which is outside the scope of this phase.
8. **`make_recipe` must commit to the DB** so the recipe is visible through the TestClient's HTTP calls (which use the same session via the `get_db` override).

---

## Running Tests

```bash
cd backend
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/recipe_test \
  python -m pytest tests/ -v --cov=app --cov-report=term-missing
```

The test database (`recipe_test`) must exist before running. Create it with:
```bash
psql -U postgres -c "CREATE DATABASE recipe_test;"
```