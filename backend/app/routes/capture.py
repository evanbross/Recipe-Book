"""
Capture routes: ingest recipes from web URLs or uploaded images/scans.
All paths run through Claude vision extraction and store results in PostgreSQL + MinIO.
"""
import logging
from datetime import datetime, UTC
from urllib.parse import urljoin

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas
from app.services import vision as vision_svc
from app.services import storage as storage_svc
from app.services import scraper as scraper_svc
from app.services import sources as sources_svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/capture", tags=["capture"])

ALLOWED_MEDIA_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}

def _trunc(value: str | None, max_len: int) -> str:
    return value[:max_len] if value else ""


@router.post("/url", response_model=schemas.RecipeOut)
def capture_from_url(payload: schemas.CaptureUrlRequest, db: Session = Depends(get_db)) -> schemas.RecipeOut:
    """
    Fetch a web page, extract its text, send to Claude, save resulting recipe.
    The OG image is downloaded and stored in MinIO when available; falls back to
    the external URL if the download or upload fails.
    """
    logger.info("[capture] Starting URL capture for %s", payload.url)

    try:
        # Phase 1 — fetch page
        try:
            page_text, og_image_url, final_url, jsonld_recipe = scraper_svc.fetch_page(payload.url)
        except Exception as e:
            logger.warning("[capture] Fetch failed for %s: %s", payload.url, e)
            raise HTTPException(status_code=422, detail=f"Failed to fetch URL: {e}")

        # Phase 2 — extract recipe
        try:
            if jsonld_recipe:
                extracted = vision_svc.extract_from_jsonld(jsonld_recipe)
                if not extracted.ingredients or not extracted.instructions:
                    # JSON-LD was present but incomplete; fall back to Claude for the gaps.
                    extracted = vision_svc.extract_from_text(page_text)
            else:
                extracted = vision_svc.extract_from_text(page_text)
        except Exception as e:
            logger.warning("[capture] Extraction failed for %s: %s", payload.url, e)
            raise HTTPException(status_code=422, detail=f"Claude extraction failed: {e}")

        # Resolve source tag from URL / JSON-LD
        source_name = sources_svc.resolve_source_name(final_url, jsonld_recipe)
        source_tag = sources_svc.get_or_create_source_tag(db, source_name) if source_name else None

        tags = db.query(models.Tag).filter(models.Tag.id.in_(payload.tag_ids)).all()
        if source_tag:
            tags.append(source_tag)

        # Determine best available image URL: OG image first, then JSON-LD image.
        image_url = og_image_url
        if not image_url and jsonld_recipe:
            jsonld_image = scraper_svc.extract_jsonld_image_url(jsonld_recipe)
            if jsonld_image:
                image_url = urljoin(final_url, jsonld_image)

        # Phase 3 — download / store image (non-fatal)
        minio_stored: dict[str, str] | None = None
        if image_url:
            try:
                img_bytes, content_type = scraper_svc.fetch_page_image(image_url)
                if content_type not in ALLOWED_MEDIA_TYPES:
                    logger.warning(
                        "[capture] Image at %s has unsupported type '%s' — skipping MinIO upload",
                        image_url, content_type,
                    )
                else:
                    web_metadata = {
                        "recipe-title": _trunc(extracted.title, 512),
                        "source-type": "web",
                        "source-url": _trunc(payload.url, 1024),
                        "source-image-url": _trunc(image_url, 1024),
                        "captured-at": datetime.now(UTC).isoformat(),
                        "app-name": "recipe-app",
                    }
                    minio_stored = storage_svc.upload_image(
                        img_bytes, content_type, metadata=web_metadata
                    )
            except Exception as exc:
                logger.warning(
                    "[capture] Image download/store failed for %s (%s: %s) — falling back to external URL",
                    image_url, type(exc).__name__, exc,
                )

        # Phase 4 — build model (truncate fields to avoid DB errors)
        if minio_stored:
            recipe = models.Recipe(
                **extracted.model_dump(),
                source_url=payload.url,
                source_type="web",
                **minio_stored,
            )
        else:
            recipe = models.Recipe(
                **extracted.model_dump(),
                source_url=payload.url,
                source_type="web",
                image_url=image_url,
            )

        recipe.tags = tags

        # Phase 5 — save to DB
        try:
            db.add(recipe)
            db.commit()
            db.refresh(recipe)
        except Exception as exc:
            db.rollback()
            logger.error("[capture] Database save failed for %s: %s", payload.url, exc)
            raise HTTPException(status_code=500, detail="Database error saving recipe")

        # Phase 6 — tag MinIO objects (non-fatal)
        if minio_stored:
            try:
                storage_svc.tag_objects_with_recipe_id(
                    minio_stored["image_key"], minio_stored.get("thumbnail_key"), recipe.id
                )
            except Exception as exc:
                logger.warning(
                    "[capture] Failed to tag MinIO objects for recipe %d: %s",
                    recipe.id, exc,
                )

        logger.info("[capture] Successfully saved recipe %d from %s", recipe.id, payload.url)
        return recipe

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[capture] Unexpected error for %s: %s", payload.url, exc)
        raise HTTPException(status_code=500, detail="Unexpected server error")


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
        except Exception as e:
            logger.warning("[scan] Failed to fetch %s: %s", payload.url, e)
            raise HTTPException(status_code=422, detail=f"Failed to fetch URL: {e}")
    else:
        html = payload.html
        source_url = payload.base_url

    try:
        raw_links = scraper_svc.extract_links(html, source_url)
    except Exception as e:
        logger.exception("[scan] Link extraction failed for %s: %s", source_url, e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to extract links from {source_url}: {type(e).__name__}: {e}",
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
    if media_type not in ALLOWED_MEDIA_TYPES:
        raise HTTPException(status_code=415, detail=f"Unsupported media type: {media_type}")

    image_bytes = await file.read()

    # Extract recipe via Claude vision
    try:
        extracted = vision_svc.extract_from_image_bytes(image_bytes, media_type)
    except Exception as e:
        logger.warning("[capture:image] Claude extraction failed: %s", e)
        raise HTTPException(status_code=422, detail=f"Claude extraction failed: {e}")

    # Upload original + thumbnail to MinIO with identifying metadata
    img_metadata = {
        "recipe-title": _trunc(extracted.title, 512),
        "source-type": "image",
        "captured-at": datetime.now(UTC).isoformat(),
        "app-name": "recipe-app",
    }
    try:
        stored = storage_svc.upload_image(image_bytes, media_type, metadata=img_metadata)
    except Exception as e:
        logger.error("[capture:image] Storage upload failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Storage upload failed: {e}")

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
