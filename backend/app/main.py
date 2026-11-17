import logging
import sys
from contextlib import asynccontextmanager
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from app.config import settings
from app.database import NotSignedInError, engine, get_current_auth, get_db  # ai: claude-opus-5-5 | 2026-11-17
from app import models
from app.routes import auth, capture, email_scan, households, images, recipes, search, tags, watchlist  # ai: claude-opus-5-5 | 2026-11-17
from app.routes.households import require_owner
from app.services import storage as storage_svc
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

# ai: claude-opus-5-5 | 2026-11-17
# Every data route needs a signed-in session. Routes that must stay public live
# on routers included without it: /health, the sign-in flow, and the two OAuth
# callbacks Google sends to http://localhost:<port>, where there is no cookie.
# tests/test_auth.py fails if any other route is reachable without signing in.
_signed_in = [Depends(get_current_auth)]
for _router in (
    recipes.router, tags.router, capture.router, search.router, email_scan.router,
    watchlist.router, images.router, households.router,
):
    app.include_router(_router, dependencies=_signed_in)
app.include_router(auth.router)
app.include_router(email_scan.callback_router)


@app.exception_handler(NotSignedInError)
async def _not_signed_in(_request: Request, _exc: NotSignedInError) -> JSONResponse:
    return JSONResponse(status_code=401, content={"detail": "Not signed in."})


# ai: claude-opus-5-5 | 2026-11-17
# The session cookie is SameSite=Lax, but every *.localhost dev app counts as the
# same site as recipe-app.localhost, so Lax alone would let another local app post
# with this one's cookie. Writes must come from the app itself or an extension
# (the capture extension posts from chrome-extension://<id>).
_TRUSTED_ORIGINS = frozenset({settings.public_url, *(o.strip().rstrip("/") for o in settings.cors_origins.split(","))})
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


@app.middleware("http")
async def _refuse_foreign_writes(request: Request, call_next) -> Response:
    origin = request.headers.get("origin")
    if (
        request.method in _UNSAFE_METHODS
        and origin is not None
        and origin not in _TRUSTED_ORIGINS
        and not origin.startswith("chrome-extension://")
    ):
        logger.warning("Refused %s %s from origin %s.", request.method, request.url.path, origin)
        return JSONResponse(status_code=403, content={"detail": "Request from an untrusted origin."})
    return await call_next(request)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# ai: claude-opus-5-5 | 2026-11-16
@app.delete("/admin/purge-recipes", tags=["admin"], dependencies=[Depends(require_owner)])  # ai: claude-opus-5-5 | 2026-11-17
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
