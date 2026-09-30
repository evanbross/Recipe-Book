# Recipe Organizer

Capture and organize recipes from web pages, photos, and scans. Powered by Claude vision AI.

## Stack

| Layer | Technology |
|---|---|
| Frontend | React 18 + Vite |
| Backend | Python 3.12 + FastAPI |
| Database | PostgreSQL 16 |
| Image Storage | Cloudflare R2 |
| AI Extraction | Anthropic Claude API |
| ORM | SQLAlchemy 2 + Alembic |

---

## Quick Start (Docker)

### 1. Clone and configure

```bash
cd backend
cp .env.example .env
# Edit .env with your real keys (see Configuration below)
```

### 2. Start everything

```bash
docker-compose up --build
```

- Frontend: http://localhost:5173  
- Backend API: http://localhost:8000  
- API docs: http://localhost:8000/docs

---

## Local Development (without Docker)

### PostgreSQL

Install PostgreSQL and create the database:

```sql
CREATE USER recipe_user WITH PASSWORD 'recipe_pass';
CREATE DATABASE recipe_db OWNER recipe_user;
```

### Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

pip install -r requirements.txt
cp .env.example .env          # fill in your keys

uvicorn app.main:app --reload
```

Tables are created automatically on first run via `Base.metadata.create_all()`.

For production migrations use Alembic:

```bash
alembic revision --autogenerate -m "initial"
alembic upgrade head
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

---

## Configuration

Edit `backend/.env`:

```env
# PostgreSQL connection
DATABASE_URL=postgresql://recipe_user:recipe_pass@localhost:5432/recipe_db

# Get from https://console.anthropic.com
ANTHROPIC_API_KEY=sk-ant-...

# Cloudflare R2 — see setup below
R2_ACCOUNT_ID=...
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
R2_BUCKET_NAME=recipe-images
R2_PUBLIC_URL=https://your-bucket.your-account.r2.dev

# Any random string for JWT signing
SECRET_KEY=change-me

# Comma-separated allowed origins for CORS
CORS_ORIGINS=http://localhost:5173
```

---

## Cloudflare R2 Setup

1. Log in to [dash.cloudflare.com](https://dash.cloudflare.com) → **R2**
2. Create a bucket named `recipe-images`
3. Enable **Public Access** on the bucket (or use a custom domain)
4. Go to **R2 → Manage R2 API tokens** → Create token with Object Read & Write
5. Copy `Account ID`, `Access Key ID`, `Secret Access Key` into `.env`
6. Set `R2_PUBLIC_URL` to the bucket's public URL shown in the dashboard

---

## API Reference

Full interactive docs at http://localhost:8000/docs when running.

### Key endpoints

| Method | Path | Description |
|---|---|---|
| GET | /recipes | List all recipes |
| GET | /recipes/{id} | Get single recipe |
| POST | /recipes | Create manually |
| PATCH | /recipes/{id} | Update recipe |
| DELETE | /recipes/{id} | Delete recipe |
| POST | /capture/url | Capture from web URL |
| POST | /capture/image | Extract from image/scan |
| GET | /tags | List all tags |
| GET | /tags/categories | List tag categories |
| POST | /tags | Create tag |
| POST | /tags/categories | Create tag category |
| GET | /search | Search + filter by tags |

### Search examples

```
GET /search?q=ramen
GET /search?tags=asian,soup
GET /search?q=bread&tags=italian
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

A recipe tagged `Asian` + `Soup` appears in searches for either `Asian` or `Soup` individually,
or both together. Tag categories are created via the API or a future admin UI.

### Seed tags via API

```bash
# Create a category
curl -X POST http://localhost:8000/tags/categories \
  -H "Content-Type: application/json" \
  -d '{"name": "Cuisine", "slug": "cuisine"}'

# Create a tag in that category
curl -X POST http://localhost:8000/tags \
  -H "Content-Type: application/json" \
  -d '{"name": "Asian", "slug": "asian", "category_id": 1}'
```

---

## Project Structure

```
recipe-app/
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI app + middleware
│   │   ├── config.py        # Settings from .env
│   │   ├── database.py      # SQLAlchemy engine + session
│   │   ├── models.py        # ORM models (Recipe, Tag, TagCategory)
│   │   ├── schemas.py       # Pydantic request/response schemas
│   │   ├── routes/
│   │   │   ├── recipes.py   # CRUD
│   │   │   ├── tags.py      # Tag + category management
│   │   │   ├── capture.py   # Web URL + image ingestion
│   │   │   └── search.py    # Full-text + tag search
│   │   └── services/
│   │       ├── vision.py    # Claude API extraction
│   │       ├── storage.py   # Cloudflare R2 upload/delete
│   │       └── scraper.py   # Web page fetch + clean
│   ├── alembic/             # DB migrations
│   ├── Dockerfile
│   ├── requirements.txt
│   └── .env.example
│
├── frontend/
│   ├── src/
│   │   ├── api/client.js    # Axios API calls
│   │   ├── components/
│   │   │   ├── Layout.jsx   # Nav + shell
│   │   │   ├── RecipeCard.jsx
│   │   │   └── TagPicker.jsx
│   │   └── pages/
│   │       ├── Home.jsx
│   │       ├── RecipeDetail.jsx
│   │       ├── AddRecipe.jsx
│   │       └── Search.jsx
│   ├── Dockerfile
│   └── package.json
│
└── docker-compose.yml
```
