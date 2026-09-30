# AI Agent Instructions — Recipe App

## Standards Files — Read These First

At the start of every session, re-read this file and each standards file below before
making any changes.

- `../Dev-Standards/COMMON_CODING_STANDARDS.md`
- `../Dev-Standards/PYTHON_STANDARDS.md`
- `../Dev-Standards/DATABASE_STANDARDS.md`
- `../Dev-Standards/REACT_STANDARDS.md`
- `../Dev-Standards/FASTAPI_STANDARDS.md`
- `../Dev-Standards/TESTING_STANDARDS.md`
- `../Dev-Standards/INFRASTRUCTURE_STANDARDS.md`
- `../Dev-Standards/CODEX_CODING_STANDARDS.md`
- `../Dev-Standards/CODEX_SESSION_RULES.md`
- `../Dev-Standards/CODEX_REVIEW_CHECKLIST.md`
- `../Dev-Standards/GEMINI_SESSION_STANDARDS.md`

---

## Project Overview

FastAPI backend (`backend/app/`) + React/Vite frontend (`frontend/src/`).
PostgreSQL via SQLAlchemy 2.0; migrations managed by Alembic.
Images stored in Cloudflare R2 (S3-compatible). Recipe extraction powered by the
Anthropic Claude API (vision + text). Local dev runs via Docker Compose.

Key files:

**Backend**
- `backend/app/main.py` — FastAPI app init, CORS middleware, router registration
- `backend/app/config.py` — Pydantic Settings (DB, Anthropic, R2, CORS)
- `backend/app/database/database.py` — SQLAlchemy engine and session factory (`get_db`)
- `backend/app/database/schemas.py` — Pydantic request/response schemas
- `backend/app/models/models.py` — ORM models: Recipe, Tag, TagCategory, recipe_tags join table
- `backend/app/routes/recipes.py` — Recipe CRUD endpoints
- `backend/app/routes/tags.py` — Tag and category endpoints
- `backend/app/routes/capture.py` — URL and image ingestion (`POST /capture/url`, `/capture/image`)
- `backend/app/routes/search.py` — Full-text + tag-filter search (PostgreSQL TSVECTOR)
- `backend/app/services/vision.py` — Claude API calls for structured recipe extraction
- `backend/app/services/scraper.py` — httpx + BeautifulSoup web page fetching
- `backend/app/services/storage.py` — R2 upload via boto3; generates originals + thumbnails

**Frontend**
- `frontend/src/App.jsx` — React Router v6 route definitions
- `frontend/src/api/client.js` — Axios instance (proxied to backend at `/api`)
- `frontend/src/pages/` — Home, RecipeDetail, AddRecipe, Search
- `frontend/src/components/` — Layout, RecipeCard, TagPicker

**Tests**
- `backend/tests/conftest.py` — pytest fixtures: DB session, TestClient, make_recipe/tag/category factories
