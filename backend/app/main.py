import logging
import sys
from contextlib import asynccontextmanager
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from app.config import settings
from app.database import engine, get_db
from app import models
from app.routes import recipes, tags, capture, search, email_scan, watchlist, images
from app.services import storage as storage_svc
from app.services.capture_listener import start_capture_listener
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
    start_capture_listener(capture.submit_listener_capture)  # ai: claude-opus-5-5 | 2026-11-15
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
app.include_router(email_scan.router)
app.include_router(watchlist.router)
app.include_router(images.router)  # ai: claude-opus-5-5 | 2026-11-16


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# ai: claude-opus-5-5 | 2026-11-16
@app.delete("/admin/purge-recipes", tags=["admin"])
def purge_all_recipes(db: Session = Depends(get_db)) -> dict[str, int]:
    """
    Delete every recipe of the requesting household, and its stored images. Tags
    are preserved. Intended for development resets; use with care.
    """
    recipes_with_images = db.query(models.Recipe).filter(models.Recipe.image_key.isnot(None)).all()
    deleted_images = 0
    for recipe in recipes_with_images:
        try:
            storage_svc.delete_image(recipe.image_key, recipe.thumbnail_key)
            deleted_images += 1
        except (BotoCoreError, ClientError) as exc:
            logger.warning("purge: could not delete images for recipe %d: %s", recipe.id, exc)

    try:
        deleted = db.query(models.Recipe).delete()
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Admin purge failed")
        raise
    logger.info("Admin purge: deleted %d recipes, cleaned %d image sets.", deleted, deleted_images)
    return {"deleted_recipes": deleted, "deleted_image_sets": deleted_images}
