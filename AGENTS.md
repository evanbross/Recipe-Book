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
Recipes can also be harvested from Gmail newsletters and from the browser extension (`browser-extension/`), which
sends the page HTML the user's browser loaded to `/capture/html`.

**Multi-tenant (households).** Every household-owned table has `tenant_id`, and every ORM
session is bound to one household (`backend/app/database/tenancy.py`). Queries are scoped
automatically (`do_orm_execute` + `with_loader_criteria`) and new rows are stamped on flush,
so routes and services do **not** filter by tenant by hand. Rules when adding code:
- New household-owned model → inherit `TenantScoped`, add a migration, and make any
  uniqueness rule start with `tenant_id`.
- Core statements (`pg_insert(...)`, `text(...)`) are **not** auto-scoped: set/filter
  `tenant_id` explicitly (`current_tenant_id(db)`).
- Work outside a request (background threads) opens `tenant_session(tenant_id)`; a session with no household fails closed (`TenantNotSetError`).
  `all_tenants_session()` is the explicit opt-out for system work spanning households.
- Requests act for the signed-in session's household (`get_current_auth` → `get_db`).
  `main.py` includes every data router with the sign-in dependency; only `/health`,
  `/auth/*` sign-in hops and the two OAuth callbacks are public, and
  `tests/test_auth.py` fails if any other route answers without a session. A new
  router must be added to that list in `main.py`. Gmail is still one connection per server.
- Sign-in is Google OAuth with the *Desktop* client: Google redirects to
  `http://localhost:<API_PORT>` (passed in by root `main.py`), and a one-time ticket hop
  sets the cookie on the app's host. See `routes/auth.py`. Who may sign in:
  `AUTH_ALLOWED_EMAILS` (joins the default household) or a household invite.
- Stored images: keys under `tenants/<id>/`, served via `GET /images/{key}`; never return
  MinIO URLs. `tests/test_tenancy.py` holds the cross-household isolation tests.

Local dev runs via the root `main.py` (picks free ports, starts uvicorn + Vite, registers
routes with Caddy at `http://recipe-app.localhost`). There is no Docker or hosted-CI setup.

Key files:

**Backend**
- `backend/app/main.py` — FastAPI app, lifespan startup checks, router registration
- `backend/app/config.py` — Pydantic Settings (DB, Anthropic, MinIO, CORS, Gmail scan)
- `backend/app/database/database.py` — SQLAlchemy engine and session factory
- `backend/app/database/tenancy.py` — Tenant/User/TenantMembership models, `TenantScoped` mixin, household scoping hooks, `get_db`
- `backend/app/schemas.py` — Pydantic request/response schemas (the only schemas module)
- `backend/app/models/models.py` — ORM models: Recipe, Tag, TagCategory, ScannedEmail,
  EmailRecipeCandidate, RecipeImageCandidate, EmailImagePreference, WatchedSite, AppSetting
- `backend/app/routes/recipes.py` — Recipe CRUD (`/recipes`)
- `backend/app/routes/tags.py` — Tags, categories, Claude tag suggestions (`/tags`)
- `backend/app/routes/capture.py` — URL / image / link-scan ingestion (`/capture`)
- `backend/app/routes/search.py` — Full-text + tag-filter search, PostgreSQL TSVECTOR (`/search`)
- `backend/app/routes/images.py` — Household-checked image serving from MinIO (`/images/{key}`)
- `backend/app/routes/auth.py` — Google sign-in, sessions, `/auth/me`, logout (`/auth`)
- `backend/app/routes/households.py` — Members and invites of the signed-in household (`/household`)
- `backend/app/routes/email_scan.py` — Gmail OAuth, scan control, settings, candidate review (`/email`)
- `backend/app/routes/watchlist.py` — Sites to revisit on a schedule (`/watchlist`)
- `backend/app/services/claude_client.py` — the only Claude caller: `CLAUDE_MODEL` setting, refusal fallbacks, text-block extraction
- `backend/app/services/vision.py` — Claude extraction from images or page text
- `backend/app/services/recipe_capture.py` — `RecipeCaptureService`: the one web-page capture pipeline (server fetch or browser-supplied HTML) behind `/capture/url` and `/capture/html`
- `backend/app/services/scraper.py` — httpx + BeautifulSoup page fetching; `parse_page_html` parses HTML from any source
- `backend/app/services/sources.py` — Derives source tags from recipe URLs
- `backend/app/services/tagger.py` — Claude tag suggestions
- `backend/app/services/storage.py` — MinIO upload/delete via boto3; originals + thumbnails
- `backend/app/services/google_oauth.py` — Shared Google OAuth: loopback redirect URI from `API_PORT`, `Flow`, ID-token check, `PendingStore`
- `backend/app/services/auth.py` — `SignInService` (who may sign in, invites, allowlist) and `SessionService`
- `backend/app/services/households.py` — `HouseholdService`: members, invites, removal
- `backend/app/services/gmail_client.py` — Gmail API; raises `NotAuthenticatedError`, never starts OAuth
- `backend/app/services/email_link_extractor.py` — Heuristics for recipe URLs in email HTML
- `backend/app/services/recipe_email_parser.py` — Claude extraction from email bodies
- `backend/app/services/image_candidates.py` — Image scoring + per-sender image preference learning
- `backend/app/services/media_types.py` — The image media types accepted everywhere (= what Claude vision accepts)
- `backend/scripts/backup_minio.py` — MinIO backup / restore to any S3-compatible store
- `backend/credentials/` — OAuth credentials and tokens; everything here is git-ignored

**Frontend**
- `frontend/src/App.jsx` — React Router v7 route definitions
- `frontend/src/api/client.js` — Axios instance (proxied to backend at `/api`)
- `frontend/src/pages/` — Home, RecipeDetail, AddRecipe, Search, Settings
- `frontend/src/components/` — Layout, RecipeCard, TagPicker, TagFilter, TagCategorizeDialog,
  EmailScanTab, ImagePickerDialog, WatchlistAlert

**Other**
- `browser-extension/` — Chrome/Edge MV3 extension: captures the open tab's HTML and posts it to `/capture/html`
- `launcher.py` — Tkinter GUI wrapper around `main.py`

**Tests**
- `backend/tests/conftest.py` — pytest fixtures: real Postgres test DB (built from
  `POSTGRES_TEST_*` settings), TestClient, make_recipe/tag/category factories
- `backend/tests/test_schema.py` — fails if the models and the Alembic chain disagree;
  every model change needs a migration
- Full backend suite runs in ~10 s (`cd backend && uv run pytest`)
- Frontend: Vitest component tests beside each component (`*.test.jsx`, API client mocked via
  `vi.mock('../api/client')`, `src/test/render.jsx` for providers);
  `cd frontend && npm run lint && npm test && npm run build` after any `.jsx` edit
- Tag/category slugs are derived server-side only (`app/services/slugs.py`); clients send names
