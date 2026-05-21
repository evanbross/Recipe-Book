import logging
import sys
from contextlib import asynccontextmanager
from typing import Any
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from app.config import settings
from app.database import Base, engine, SessionLocal
from app import models, schemas
from app.routes import recipes, tags, capture, search, email_scan, watchlist
from app.services import scraper as scraper_svc, vision as vision_svc
from app.services import storage as storage_svc
from app.services.capture_listener import start_capture_listener
from app.services.storage import check_connectivity as check_minio

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d): %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def _listener_submit_capture(body: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Callback wired into the capture listener; mirrors the /capture/url route logic."""
    url = str(body["url"])
    tag_ids: list[int] = list(body.get("tag_ids") or [])

    try:
        page_text = scraper_svc.fetch_page_text(url)
    except Exception as exc:
        logger.warning("Capture listener: failed to fetch %s: %s", url, exc)
        return {"detail": f"Failed to fetch URL: {exc}"}, 422

    try:
        extracted = vision_svc.extract_from_text(page_text)
    except Exception as exc:
        logger.warning("Capture listener: Claude extraction failed: %s", exc)
        return {"detail": f"Claude extraction failed: {exc}"}, 422

    db = SessionLocal()
    try:
        matched_tags = db.query(models.Tag).filter(models.Tag.id.in_(tag_ids)).all()
        recipe = models.Recipe(
            **extracted.model_dump(),
            source_url=url,
            source_type="web",
        )
        recipe.tags = matched_tags
        db.add(recipe)
        db.commit()
        db.refresh(recipe)
        return schemas.RecipeOut.model_validate(recipe).model_dump(mode="json"), 200
    except Exception as exc:
        db.rollback()
        logger.error("Capture listener: database error: %s", exc)
        return {"detail": "Database error"}, 500
    finally:
        db.close()


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
    start_capture_listener(_listener_submit_capture)
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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.delete("/admin/purge-recipes", tags=["admin"])
def purge_all_recipes() -> dict[str, int]:
    """
    Delete every recipe and its stored images. Tags are preserved.
    Intended for development resets — use with care.
    """
    db = SessionLocal()
    try:
        recipes_with_images = (
            db.query(models.Recipe)
            .filter(models.Recipe.image_key.isnot(None))
            .all()
        )
        deleted_images = 0
        for recipe in recipes_with_images:
            try:
                storage_svc.delete_image(recipe.image_key, recipe.thumbnail_key)
                deleted_images += 1
            except Exception as exc:
                logger.warning("purge: could not delete images for recipe %d: %s", recipe.id, exc)

        deleted = db.query(models.Recipe).delete()
        db.commit()
        logger.info("Admin purge: deleted %d recipes, cleaned %d image sets.", deleted, deleted_images)
        return {"deleted_recipes": deleted, "deleted_image_sets": deleted_images}
    except Exception as exc:
        db.rollback()
        logger.error("Admin purge failed: %s", exc)
        raise
    finally:
        db.close()
