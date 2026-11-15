# AI Agent Instructions — Recipe App

## Standards Files — Read These First

At the start of every session, re-read this file and each standards file below before
making any changes.

- `../Dev-Standards/COMMON_CODING_STANDARDS.md`
- `../Dev-Standards/PYTHON_STANDARDS.md`
- `../Dev-Standards/DATABASE_STANDARDS.md`
- `../Dev-Standards/JAVASCRIPT_TYPESCRIPT_STANDARDS.md`
- `../Dev-Standards/REACT_STANDARDS.md`
- `../Dev-Standards/FASTAPI_STANDARDS.md`
- `../Dev-Standards/TESTING_STANDARDS.md`
- `../Dev-Standards/CODEX_CODING_STANDARDS.md`
- `../Dev-Standards/CODEX_SESSION_RULES.md`
- `../Dev-Standards/CODEX_REVIEW_CHECKLIST.md`
- `../Dev-Standards/GEMINI_SESSION_STANDARDS.md`

---

## Project Overview

FastAPI backend (`backend/app/`) + React/Vite frontend (`frontend/src/`).
PostgreSQL via SQLAlchemy 2.0; migrations managed by Alembic.
Images stored in **MinIO** (S3-compatible, served by the sibling `../infra` stack).
Cloudflare R2 is a possible future target only — it is not wired up; do not write R2
code unless asked. Recipe extraction powered by the Anthropic Claude API (vision + text).
Recipes can also be harvested from Gmail newsletters and from a Tampermonkey userscript.

Local dev runs via the root `main.py` (picks free ports, starts uvicorn + Vite, registers
routes with Caddy at `http://recipe-app.localhost`). There is no Docker or hosted-CI setup.

Key files:

**Backend**
- `backend/app/main.py` — FastAPI app, lifespan startup checks, router registration
- `backend/app/config.py` — Pydantic Settings (DB, Anthropic, MinIO, CORS, capture listener, Gmail scan)
- `backend/app/database/database.py` — SQLAlchemy engine and session factory (`get_db`)
- `backend/app/schemas.py` — Pydantic request/response schemas (the only schemas module)
- `backend/app/models/models.py` — ORM models: Recipe, Tag, TagCategory, ScannedEmail,
  EmailRecipeCandidate, RecipeImageCandidate, EmailImagePreference, WatchedSite, AppSetting
- `backend/app/routes/recipes.py` — Recipe CRUD (`/recipes`)
- `backend/app/routes/tags.py` — Tags, categories, Claude tag suggestions (`/tags`)
- `backend/app/routes/capture.py` — URL / image / link-scan ingestion (`/capture`)
- `backend/app/routes/search.py` — Full-text + tag-filter search, PostgreSQL TSVECTOR (`/search`)
- `backend/app/routes/email_scan.py` — Gmail OAuth, scan control, settings, candidate review (`/email`)
- `backend/app/routes/watchlist.py` — Sites to revisit on a schedule (`/watchlist`)
- `backend/app/services/claude_client.py` — the only Claude caller: `CLAUDE_MODEL` setting, refusal fallbacks, text-block extraction
- `backend/app/services/vision.py` — Claude extraction from images or page text
- `backend/app/services/scraper.py` — httpx + BeautifulSoup page fetching
- `backend/app/services/sources.py` — Derives source tags from recipe URLs
- `backend/app/services/tagger.py` — Claude tag suggestions
- `backend/app/services/storage.py` — MinIO upload/delete via boto3; originals + thumbnails
- `backend/app/services/gmail_client.py` — Gmail API; raises `NotAuthenticatedError`, never starts OAuth
- `backend/app/services/email_link_extractor.py` — Heuristics for recipe URLs in email HTML
- `backend/app/services/recipe_email_parser.py` — Claude extraction from email bodies
- `backend/app/services/image_candidates.py` — Image scoring + per-sender image preference learning
- `backend/app/services/capture_listener.py` — Localhost HTTP listener for the Tampermonkey userscript
- `backend/scripts/backup_minio.py` — MinIO backup / restore to any S3-compatible store
- `backend/credentials/` — OAuth credentials and tokens; everything here is git-ignored

**Frontend**
- `frontend/src/App.jsx` — React Router v6 route definitions
- `frontend/src/api/client.js` — Axios instance (proxied to backend at `/api`)
- `frontend/src/pages/` — Home, RecipeDetail, AddRecipe, Search, Settings
- `frontend/src/components/` — Layout, RecipeCard, TagPicker, TagFilter, TagCategorizeDialog,
  EmailScanTab, ImagePickerDialog, WatchlistAlert

**Other**
- `tampermonkey/recipe-capture.user.js` — Userscript that posts pages to the capture listener
- `launcher.py` — Tkinter GUI wrapper around `main.py`

**Tests**
- `backend/tests/conftest.py` — pytest fixtures: real Postgres test DB (built from
  `POSTGRES_TEST_*` settings), TestClient, make_recipe/tag/category factories
- `backend/tests/test_schema.py` — fails if the models and the Alembic chain disagree;
  every model change needs a migration
- Full backend suite runs in ~10 s (`cd backend && uv run pytest`)
- Frontend: no tests; `cd frontend && npm run lint && npm run build` after any `.jsx` edit
