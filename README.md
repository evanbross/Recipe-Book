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
  dev Caddy. It also holds `zt-common` (`../infra/zt-common`), the shared dev-runner,
  Caddy-registration and SMTP code; `uv sync` installs it into `backend/.venv` as an
  editable runtime dependency, so `uv sync` fails if `../infra` is missing. The backend refuses
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

### Browser extension (capture from your browser)

Some sites (Serious Eats, Allrecipes and other Dotdash Meredith sites) block the app's
own page fetch with HTTP 402/403. The **Recipe App Capture** extension in
`browser-extension/` sends the page as your browser already loaded it to
`POST /capture/html` instead, so those sites work too.

Install it in Chrome or Edge (version 116 or later):

1. Open `chrome://extensions` (or `edge://extensions`) and turn on **Developer mode**.
2. Click **Load unpacked** and choose the `browser-extension/` folder.
3. Pin the extension, open a recipe page, click the icon, pick any tags and press
   **Capture recipe**. (The site's source tag is added automatically.)

The capture keeps running if you close the popup. The icon shows … while it works,
✓ when the recipe is saved, and ! on an error (open the popup to read it). It posts to
`http://recipe-app.localhost` by default; if `CADDY_APP_NAME` is different, set the
address under **Settings** in the popup, which also tests the connection. After you
change any file in `browser-extension/`, click the reload icon on the extension's card.
The extension uses your browser's Recipe App sign-in, so sign in to the app first.

### Signing in

The app uses Google sign-in, with the same Desktop OAuth client as Gmail
(`backend/credentials/google_credentials.json`). Nothing needs registering in Google
Cloud Console: Google redirects to `http://localhost:<backend port>`, which `main.py`
passes to the backend as `API_PORT`, and the backend then forwards you to the app.
If you start uvicorn yourself, set `API_PORT` to its port or sign-in is disabled.

Who can sign in:

- Emails in `AUTH_ALLOWED_EMAILS` (comma-separated). On first sign-in they join the
  default household, which holds all recipes from before sign-in existed. The first one
  to sign in becomes its **owner**.
- Anyone the owner invites under **Settings → Household**. The invite is accepted the
  next time that Google account signs in.

Once someone belongs to a household, the membership is what counts: removing them from
`AUTH_ALLOWED_EMAILS` doesn't lock them out. The owner removes them in Settings instead,
which signs them out immediately. Sessions last 30 days (`SESSION_LIFETIME_DAYS`).

Server administrators are listed separately in `AUTH_ADMIN_EMAILS`. They must still be
allowed or invited to sign in. Admin status is global and is not the same as being a
household owner; administrators can configure the outgoing SMTP relay under
**Settings → Outgoing Mail** and send themselves a test message.

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
| Households | `DEFAULT_TENANT_SLUG`, `API_PUBLIC_PREFIX` | Household allowlisted users join (default `default`); path the browser reaches the API under (default `/api`) |
| Sign-in | `AUTH_ALLOWED_EMAILS`, `AUTH_ADMIN_EMAILS`, `SESSION_LIFETIME_DAYS`, `APP_PUBLIC_URL` | See [Signing in](#signing-in). `APP_PUBLIC_URL` defaults to `http://<CADDY_APP_NAME>.localhost`. `API_PORT` is set by `main.py` |
| Outgoing mail | `SMTP_*` | Environment values are the initial fallback. An administrator can replace them under **Settings → Outgoing Mail**; the saved password is encrypted using `SECRET_KEY`, so keep that key stable |
| App | `SECRET_KEY`, `CORS_ORIGINS` | |
| Caddy | `CADDY_APP_NAME` | App hostname (`<name>.localhost`) |
| Email scanning | `EMAIL_SCAN_*` | Gmail OAuth uses the same credentials as sign-in, in `backend/credentials/` |

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
`http://recipe-app.localhost/api`. Everything except the routes marked public needs a
signed-in session cookie; without one the API answers 401.

### Key endpoints

| Method | Path | Description |
|---|---|---|
| GET | /health | Health check (public) |
| GET | /auth/login | Start Google sign-in (public; open in the browser) |
| GET | /auth/me | The signed-in user, household and role |
| POST | /auth/logout | End this session |
| GET | /household | Members and pending invites |
| POST | /household/invites | Invite an email (owner only) |
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
│   │   ├── routes/          # recipes, tags, capture, search, email_scan, watchlist, auth, households
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
