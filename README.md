# Recipe Organizer

Capture and organize recipes from web pages, photos, scans, and emails. Powered by Claude vision AI.

## Stack

| Layer | Technology |
|---|---|
| Frontend | React 18 + Vite 5 |
| Backend | Python 3.14 + FastAPI, managed with [uv](https://docs.astral.sh/uv/) |
| Database | PostgreSQL (local or managed, e.g. Neon) |
| Image Storage | MinIO (S3-compatible) |
| AI Extraction | Anthropic Claude API |
| ORM | SQLAlchemy 2 + Alembic |
| Dev routing | Caddy reverse proxy (`http://recipe-app.localhost`) |

---

## Running the App

### Prerequisites

- **uv** and **Node.js / npm** on `PATH`
- **PostgreSQL** reachable with the credentials in `backend/.env`
- The sibling **`../infra`** repo, checked out next to this one, with its stack running
  (`cd ../infra && docker-compose up -d`). It provides MinIO (`dev_minio`) and the shared
  dev Caddy. It also holds `zt-devkit` (`../infra/devkit`), the shared dev-runner and
  Caddy-registration helpers `main.py` uses; `uv sync` installs it into `backend/.venv` as an
  editable dev dependency, so `uv sync` fails if `../infra` is missing. The backend refuses
  to start if MinIO or its bucket is unreachable.

### 1. Install and configure

```bash
cd backend
uv sync                      # creates backend/.venv (Python 3.14, see .python-version) incl. dev deps
cp .env.example .env         # then fill in real values (see Configuration)
uv run alembic upgrade head  # create / migrate the database schema
```

The schema is managed only by Alembic — nothing creates tables automatically at startup.

### 2. Start

From the repo root:

```bash
backend/.venv/Scripts/python main.py       # terminal; Ctrl-C stops everything
backend/.venv/Scripts/python launcher.py   # small GUI window with Open Browser / Restart / Stop
```

`main.py` picks a free port for the backend and for Vite on every start, registers both
with Caddy, and prints a `[READY]` line when they're up.

### URLs

| What | URL |
|---|---|
| **App** | **http://recipe-app.localhost** |
| API (via Caddy) | http://recipe-app.localhost/api/... — Caddy strips `/api` before forwarding |
| API docs | `http://localhost:<backend port>/docs` — use the backend port from the `Direct:` line `main.py` prints |

The hostname comes from `CADDY_APP_NAME` in `backend/.env`. The ports change on each start,
so don't bookmark them.

The interactive API docs only work on the direct backend port. Through Caddy, the docs
page loads its schema from `/openapi.json` without the `/api` prefix, so the request
goes to the frontend and fails.

The frontend calls the API at the relative path `/api`, and Vite has no proxy for it,
so **the UI only works through Caddy**. Without Caddy, only the backend is usable
(directly on its port).

---

## Configuration

All settings live in `backend/.env`. Start from `backend/.env.example`, which lists every
key with comments. If `.env` is missing, the backend writes a template and exits. The groups are:

| Group | Keys | Notes |
|---|---|---|
| Database | `POSTGRES_*` or `DATABASE_URL` | Individual vars are assembled into a URL; set `POSTGRES_SSLMODE=require` for managed hosts such as Neon |
| Test database | `POSTGRES_TEST_*` | Used only by pytest — see [Running Tests](#running-tests) |
| Claude | `ANTHROPIC_API_KEY` | From https://console.anthropic.com |
| Image storage | `MINIO_*` | Endpoint, keys and bucket. The bucket stays private: images are served through the API (`GET /images/{key}`) |
| Households | `DEFAULT_TENANT_SLUG`, `API_PUBLIC_PREFIX` | Household every request acts for until login exists (default `default`); path the browser reaches the API under (default `/api`) |
| App | `SECRET_KEY`, `CORS_ORIGINS` | |
| Caddy | `CADDY_APP_NAME` | App hostname (`<name>.localhost`) |
| Email scanning | `GOOGLE_OAUTH_REDIRECT_URI`, `EMAIL_SCAN_*` | Gmail OAuth; credentials go in `backend/credentials/` |

---

## Running Tests

The backend has a pytest integration suite that runs against a **real PostgreSQL test
database** (no SQLite, no mocked DB). External services — Claude, MinIO, the web
scraper — are mocked.

### One-time setup

Create a dedicated role and database as a PostgreSQL superuser. The test user must
**own** the database, because each run drops and rebuilds the `public` schema:

```sql
CREATE USER recipe_test_app WITH PASSWORD 'choose-one';
CREATE DATABASE recipe_test OWNER recipe_test_app;
```

Then add to `backend/.env`:

```env
POSTGRES_TEST_HOST=localhost
POSTGRES_TEST_PORT=5432
POSTGRES_TEST_DB=recipe_test
POSTGRES_TEST_USER=recipe_test_app
POSTGRES_TEST_PASSWORD=choose-one
POSTGRES_TEST_SSLMODE=prefer   # local servers usually have SSL off; "require" will fail
```

Alternatively, set `TEST_DATABASE_URL` in the environment; it takes precedence.

### Run

```bash
cd backend
.venv/Scripts/python -m pytest
```

Each session rebuilds the schema with `alembic upgrade head`, and `tests/test_schema.py`
fails if autogenerate would find any difference between the models and that schema — so
a model change without a matching migration (or vice versa) can't slip through. Safety guards:

- The suite refuses to run unless the database name ends in `_test`.
- Only the `POSTGRES_TEST_*` keys are read from `.env`, so the real API keys and the
  main database never reach the test process.

### Pre-push gate

There's no hosted CI. Instead, `.githooks/pre-push` runs the backend tests and/or the
frontend lint + tests + build, depending on what the push changes. Enable it once per clone:

```bash
git config core.hooksPath .githooks
```

Skip it for one push with `git push --no-verify` (e.g. when the test database is down).

### Frontend checks

Vitest + React Testing Library component tests live next to the components
(`*.test.jsx`), with the API client mocked. Run all three after any `.jsx` change:

```bash
cd frontend
npm run lint    # ESLint: no-undef, rules-of-hooks, React Compiler purity rules
npm test        # Vitest (npm run test:watch while iterating)
npm run build
```

---

## Backing Up / Migrating Image Storage

`scripts/backup_minio.py` backs up whichever bucket `backend/.env`'s `MINIO_*`
settings point at.

```bash
cd backend

# Back up every object (bytes + content-type + metadata + tags) to local files
uv run python scripts/backup_minio.py backup
# -> backend/backups/minio/<bucket>-<UTC timestamp>/manifest.json + objects/

# Replay a backup into ANY S3-compatible store (a new MinIO, Garage, R2, ...) --
# this is the actual migration path if the old MinIO instance becomes unreachable.
uv run python scripts/backup_minio.py restore \
  --manifest backend/backups/minio/<bucket>-<timestamp> \
  --endpoint http://localhost:3900 \
  --access-key <key> --secret-key <secret> \
  --bucket recipe-images --create-bucket
```

`backup` only reads from the source bucket; `restore`'s target is always
given explicitly on the command line, never read from this app's own
`.env`, since the point is to populate a *different* store. After a
restore, point `MINIO_ENDPOINT`/`MINIO_ACCESS_KEY`/`MINIO_SECRET_KEY` at the new store.

### Future: Cloudflare R2

R2 is a possible future storage target; it is not wired up today. Because R2 is
S3-compatible, moving to it means restoring a backup into an R2 bucket (above) and
pointing the `MINIO_*` settings at the R2 endpoint. Bucket setup:

1. In [dash.cloudflare.com](https://dash.cloudflare.com) → **R2**, create a bucket (e.g. `recipe-images`)
2. Keep the bucket private: images are served through the API, which checks the household
3. **R2 → Manage R2 API tokens** → create a token with Object Read & Write
4. Use the account's S3 endpoint and the token's access key ID and secret

---

## API Reference

Paths below are the backend's own routes. Through Caddy, prefix them with
`http://recipe-app.localhost/api`.

### Key endpoints

| Method | Path | Description |
|---|---|---|
| GET | /health | Health check |
| GET | /recipes | List recipes (`skip`, `limit`) |
| GET | /recipes/{id} | Get single recipe |
| POST | /recipes | Create manually |
| PATCH | /recipes/{id} | Update recipe |
| DELETE | /recipes/{id} | Delete recipe (and its stored images) |
| POST | /capture/url | Capture from web URL |
| POST | /capture/html | Capture from page HTML the browser already loaded (for sites that block server fetches) |
| GET | /images/{key} | A stored recipe image, served only to the household that owns it |
| POST | /capture/image | Extract from image/scan (multipart upload) |
| POST | /capture/scan | List links on a page for bulk capture |
| GET | /tags | List tags (optional `category_id`) |
| POST | /tags | Create tag |
| POST | /tags/suggest | Claude tag suggestions for a recipe |
| GET | /tags/categories | List tag categories |
| POST | /tags/categories | Create tag category |
| GET | /search | Search + filter by tags |

Email scanning and watchlist endpoints are listed in the interactive docs.

### Search

- **`q`**: free text. It supports `AND`, `OR`, `NOT` / `-word`, parentheses, and `word*`
  prefix wildcards.
- **`tag_ids`**: comma-separated tag **IDs** (not slugs). Non-numeric entries are ignored.
- **`tag_mode`**: `and` (default; a recipe must have every listed tag) or `or` (any one of them).
- **`page`** and **`page_size`**: paging.

```
GET /search?q=ramen
GET /search?tag_ids=3,7
GET /search?tag_ids=3,7&tag_mode=or
GET /search?q=bread&tag_ids=2
```

---

## Tag System

Tags are organized into **categories** for cross-referencing:

| Category | Example Tags |
|---|---|
| Cuisine | Asian, Italian, Mexican, French |
| Course | Soup, Bread, Dessert, Appetizer |
| Diet | Vegetarian, Gluten-Free, Vegan |
| Ingredient | Chicken, Pasta, Mushroom |
| Source | Added automatically on web capture (site or publisher name) |

A recipe tagged `Asian` + `Soup` appears in searches for either tag on its own, or both
together. Tags and categories can be created in the UI or via the API.

### Seed tags via API

```bash
# Create a category
curl -X POST http://recipe-app.localhost/api/tags/categories \
  -H "Content-Type: application/json" \
  -d '{"name": "Cuisine", "slug": "cuisine"}'

# Create a tag in that category
curl -X POST http://recipe-app.localhost/api/tags \
  -H "Content-Type: application/json" \
  -d '{"name": "Asian", "slug": "asian", "category_id": 1}'
```

---

## Project Structure

```
Recipe App/
├── main.py                  # Dev entry point: free ports, uvicorn + Vite, Caddy registration
├── launcher.py              # Tkinter GUI wrapper around main.py
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI app, lifespan startup checks, routers
│   │   ├── config.py        # Settings from .env (pydantic-settings)
│   │   ├── schemas.py       # Pydantic request/response schemas
│   │   ├── database/        # SQLAlchemy engine, session, get_db
│   │   ├── models/          # ORM models
│   │   ├── routes/          # recipes, tags, capture, search, email_scan, watchlist
│   │   └── services/        # vision (Claude), storage (MinIO), scraper, sources,
│   │                        # tagger, gmail_client, recipe_capture, ...
│   ├── alembic/             # DB migrations
│   ├── tests/               # pytest integration suite
│   ├── scripts/             # backup_minio.py
│   ├── pyproject.toml       # dependencies (uv)
│   ├── uv.lock
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── api/client.js    # Axios client (baseURL /api)
│   │   ├── components/
│   │   ├── pages/           # Home, RecipeDetail, AddRecipe, Search, Settings
│   │   └── utils/
│   └── package.json
└── browser-extension/       # Chrome/Edge extension: capture the open tab via /capture/html
```
