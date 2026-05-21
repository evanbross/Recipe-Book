"""
Capture routes: ingest recipes from web URLs or uploaded images/scans.
All paths run through Claude vision extraction and store results in PostgreSQL + MinIO.
"""
import logging
from datetime import datetime, UTC

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas
from app.services import vision as vision_svc
from app.services import storage as storage_svc
from app.services import scraper as scraper_svc

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
    try:
        page_text, og_image_url, _, jsonld_recipe = scraper_svc.fetch_page(payload.url)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Failed to fetch URL: {e}")

    try:
        if jsonld_recipe:
            extracted = vision_svc.extract_from_jsonld(jsonld_recipe)
            if not extracted.ingredients or not extracted.instructions:
                # JSON-LD was present but incomplete; fall back to Claude for the gaps.
                extracted = vision_svc.extract_from_text(page_text)
        else:
            extracted = vision_svc.extract_from_text(page_text)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Claude extraction failed: {e}")

    tags = db.query(models.Tag).filter(models.Tag.id.in_(payload.tag_ids)).all()

    # Attempt to download the OG image and store it in MinIO.
    # Any failure here is non-fatal; the recipe is saved with the external URL as fallback.
    minio_stored: dict[str, str] | None = None
    if og_image_url:
        try:
            img_bytes, content_type = scraper_svc.fetch_page_image(og_image_url)
            if content_type not in ALLOWED_MEDIA_TYPES:
                logger.warning(
                    "OG image at %s has unsupported type '%s' — skipping MinIO upload",
                    og_image_url, content_type,
                )
            else:
                web_metadata = {
                    "recipe-title": _trunc(extracted.title, 512),
                    "source-type": "web",
                    "source-url": _trunc(og_image_url, 1024),
                    "captured-at": datetime.now(UTC).isoformat(),
                    "app-name": "recipe-app",
                }
                minio_stored = storage_svc.upload_image(
                    img_bytes, content_type, metadata=web_metadata
                )
        except Exception as exc:
            logger.warning(
                "OG image download/store failed for %s (%s: %s) — falling back to external URL",
                og_image_url, type(exc).__name__, exc,
            )

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
            image_url=og_image_url,
        )

    recipe.tags = tags
    db.add(recipe)
    db.commit()
    db.refresh(recipe)

    if minio_stored:
        storage_svc.tag_objects_with_recipe_id(
            minio_stored["image_key"], minio_stored.get("thumbnail_key"), recipe.id
        )

    return recipe


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

    if payload.url and not payload.html:
        try:
            html, source_url = scraper_svc.fetch_page_html(payload.url)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Failed to fetch URL: {e}")
    else:
        html = payload.html
        source_url = payload.base_url

    raw_links = scraper_svc.extract_links(html, source_url)
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
    db.add(recipe)
    db.commit()
    db.refresh(recipe)

    storage_svc.tag_objects_with_recipe_id(
        stored["image_key"], stored.get("thumbnail_key"), recipe.id
    )

    return recipe
