"""
Capture routes: ingest recipes from web URLs or uploaded images/scans.
All paths run through Claude vision extraction and store results in PostgreSQL + MinIO.
"""
import logging
from datetime import datetime, UTC
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

from app.database import current_tenant_id, default_tenant_session, get_db  # ai: claude-opus-5-5 | 2026-11-16
from app import models, schemas
from app.services import vision as vision_svc
from app.services import storage as storage_svc
from app.services import scraper as scraper_svc
from app.services.recipe_capture import (  # ai: claude-opus-5-5 | 2026-11-15
    PageFetchError, RecipeCaptureService, RecipeExtractionError, RecipeSaveError,
)
from app.services.media_types import SUPPORTED_IMAGE_MEDIA_TYPES  # ai: claude-opus-5-5 | 2026-11-15
from app.services.url_guard import UnsafeURLError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/capture", tags=["capture"])


def _trunc(value: str | None, max_len: int) -> str:
    return value[:max_len] if value else ""


# ai: claude-opus-5-5 | 2026-11-15
_BLOCKED_HINT = (
    "Some sites block automated access; capture it from your browser with the "
    "userscript, or upload a screenshot instead."
)


def capture_error_response(exc: Exception) -> tuple[int, str]:
    """Map a capture-service error to (HTTP status, user-facing message).

    Shared by the HTTP routes and the userscript listener so both report the
    same thing. Messages stay generic: details go to the server log only.
    """
    if isinstance(exc, UnsafeURLError):
        return 400, "URL not allowed: it points to a private or local address."
    if isinstance(exc, PageFetchError):
        if exc.status_code is not None:
            return 422, f"Failed to fetch URL: the site refused the request (HTTP {exc.status_code}). {_BLOCKED_HINT}"
        return 422, "Failed to fetch URL: could not reach the site."
    if isinstance(exc, RecipeExtractionError):
        return 422, "Claude extraction failed."
    if isinstance(exc, RecipeSaveError):
        return 500, "Database error saving recipe"
    raise exc


_CAPTURE_ERRORS = (UnsafeURLError, PageFetchError, RecipeExtractionError, RecipeSaveError)


# ai: claude-opus-5-5 | 2026-11-15
@router.post("/url", response_model=schemas.RecipeOut)
def capture_from_url(payload: schemas.CaptureUrlRequest, db: Session = Depends(get_db)) -> schemas.RecipeOut:
    """Fetch a web page server-side, extract the recipe, store its image and save it."""
    try:
        return RecipeCaptureService(db).capture_url(payload.url, payload.tag_ids)
    except _CAPTURE_ERRORS as exc:
        status_code, detail = capture_error_response(exc)
        raise HTTPException(status_code=status_code, detail=detail)


# ai: claude-opus-5-5 | 2026-11-15
@router.post("/html", response_model=schemas.RecipeOut)
def capture_from_html(payload: schemas.CaptureHtmlRequest, db: Session = Depends(get_db)) -> schemas.RecipeOut:
    """Capture from page HTML the caller's browser already loaded.

    For sites that refuse server-side fetches: the page itself is never fetched,
    only its image (through the same SSRF-guarded client as every other fetch).
    """
    try:
        return RecipeCaptureService(db).capture_html(payload.url, payload.html, payload.tag_ids)
    except _CAPTURE_ERRORS as exc:
        status_code, detail = capture_error_response(exc)
        raise HTTPException(status_code=status_code, detail=detail)


# ai: claude-opus-5-5 | 2026-11-16
def submit_listener_capture(body: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Capture callback for the userscript listener (its own thread, so its own session).

    The listener only accepts localhost connections and has no login, so captures
    land in the default household. Uses the page HTML when the userscript sent it,
    otherwise fetches the URL.
    """
    with default_tenant_session() as db:
        service = RecipeCaptureService(db)
        try:
            html = body.get("html")
            if html:
                recipe = service.capture_html(body["url"], html, body["tag_ids"])
            else:
                recipe = service.capture_url(body["url"], body["tag_ids"])
        except _CAPTURE_ERRORS as exc:
            status_code, detail = capture_error_response(exc)
            return {"detail": detail}, status_code
        return schemas.RecipeOut.model_validate(recipe).model_dump(mode="json"), 200


@router.post("/scan", response_model=schemas.ScanResponse)
def scan_for_links(payload: schemas.ScanRequest) -> schemas.ScanResponse:
    """
    Scan a URL or raw HTML for links and return them for bulk capture review.
    Supply either `url` (backend fetches the page) or `html` + `base_url` (use provided markup).
    """
    if not payload.url and not payload.html:
        raise HTTPException(status_code=422, detail="Provide either 'url' or 'html'.")
    if payload.html and not payload.base_url:
        raise HTTPException(status_code=422, detail="'base_url' is required when providing 'html'.")

    source_url: str
    if payload.url and not payload.html:
        try:
            html, source_url = scraper_svc.fetch_page_html(payload.url)
        # ai: claude-opus-5-5 | 2026-11-13
        except UnsafeURLError as e:
            logger.warning("[scan] Blocked fetch of %s: %s", payload.url, e)
            raise HTTPException(status_code=400, detail="URL not allowed: it points to a private or local address.")
        except httpx.HTTPError as e:
            logger.warning("[scan] Failed to fetch %s: %s", payload.url, e)
            raise HTTPException(status_code=422, detail="Failed to fetch URL.")
    else:
        html = payload.html
        source_url = payload.base_url

    try:
        raw_links = scraper_svc.extract_links(html, source_url)
    except Exception as e:
        logger.exception("[scan] Link extraction failed for %s: %s", source_url, e)
        raise HTTPException(
            status_code=500,
            detail="Failed to extract links from the page.",  # ai: claude-opus-5-5 | 2026-11-13
        )

    links = [
        schemas.ScannedLink(url=l["url"], title=l["title"], same_origin=l["same_origin"])
        for l in raw_links
    ]
    return schemas.ScanResponse(links=links, total=len(links), source_url=source_url)


@router.post("/image", response_model=schemas.RecipeOut)
async def capture_from_image(
    file: UploadFile = File(...),
    tag_ids: str = Form(default=""),   # comma-separated tag IDs from multipart form
    db: Session = Depends(get_db),
) -> schemas.RecipeOut:
    """
    Accept an uploaded image or scan, send to Claude vision, store in MinIO, save recipe.
    """
    media_type = file.content_type or "image/jpeg"
    if media_type not in SUPPORTED_IMAGE_MEDIA_TYPES:
        raise HTTPException(status_code=415, detail=f"Unsupported media type: {media_type}")

    image_bytes = await file.read()

    # Extract recipe via Claude vision
    try:
        extracted = vision_svc.extract_from_image_bytes(image_bytes, media_type)
    except Exception as e:
        logger.warning("[capture:image] Claude extraction failed: %s", e)
        raise HTTPException(status_code=422, detail="Claude extraction failed.")  # ai: claude-opus-5-5 | 2026-11-13

    # Upload original + thumbnail to MinIO with identifying metadata
    img_metadata = {
        "recipe-title": _trunc(extracted.title, 512),
        "source-type": "image",
        "captured-at": datetime.now(UTC).isoformat(),
        "app-name": "recipe-app",
    }
    try:
        stored = storage_svc.upload_image(
            image_bytes, media_type, tenant_id=current_tenant_id(db), metadata=img_metadata,
        )  # ai: claude-opus-5-5 | 2026-11-16
    except Exception as e:
        logger.error("[capture:image] Storage upload failed: %s", e)
        raise HTTPException(status_code=500, detail="Storage upload failed.")  # ai: claude-opus-5-5 | 2026-11-13

    # Parse tag_ids from comma-separated form field
    parsed_tag_ids = [int(t) for t in tag_ids.split(",") if t.strip().isdigit()]
    tags = db.query(models.Tag).filter(models.Tag.id.in_(parsed_tag_ids)).all()

    recipe = models.Recipe(
        **extracted.model_dump(),
        source_type="image",
        **stored,
    )
    recipe.tags = tags

    try:
        db.add(recipe)
        db.commit()
        db.refresh(recipe)
    except Exception as e:
        db.rollback()
        logger.error("[capture:image] Database save failed: %s", e)
        raise HTTPException(status_code=500, detail="Database error saving recipe")

    try:
        storage_svc.tag_objects_with_recipe_id(
            stored["image_key"], stored.get("thumbnail_key"), recipe.id
        )
    except Exception as exc:
        logger.warning("[capture:image] Failed to tag MinIO objects for recipe %d: %s", recipe.id, exc)

    return recipe
