import logging
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from app.config import settings
from app.database import Base, engine
from app.routes import recipes, tags, capture, search
from app.services.storage import check_connectivity as check_minio

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d): %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def _check_database() -> None:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Database reachable.")
    except Exception as exc:
        raise RuntimeError(f"Database health check failed: {exc}") from exc


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up — checking external dependencies...")
    try:
        _check_database()
        check_minio()
    except RuntimeError as exc:
        logger.critical("Startup check failed: %s", exc)
        sys.exit(1)
    logger.info("All dependency checks passed.")
    yield


app = FastAPI(
    title="Recipe Organizer API",
    version="0.1.0",
    description="Capture and organize recipes from web pages, photos, and scans.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(recipes.router)
app.include_router(tags.router)
app.include_router(capture.router)
app.include_router(search.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
