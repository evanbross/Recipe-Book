"""
Capture routes: ingest recipes from web URLs or uploaded images/scans.
All paths run through Claude vision extraction and store results in PostgreSQL + R2.
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from app.database import get_db
from app import models, schemas
from app.services import vision as vision_svc
from app.services import storage as storage_svc
from app.services import scraper as scraper_svc

router = APIRouter(prefix="/capture", tags=["capture"])

ALLOWED_MEDIA_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


@router.post("/url", response_model=schemas.RecipeOut)
def capture_from_url(payload: schemas.CaptureUrlRequest, db: Session = Depends(get_db)) -> schemas.RecipeOut:
    """
    Fetch a web page, extract its text, send to Claude, save resulting recipe.
    """
    try:
        page_text = scraper_svc.fetch_page_text(payload.url)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Failed to fetch URL: {e}")

    try:
        extracted = vision_svc.extract_from_text(page_text)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Claude extraction failed: {e}")

    tags = db.query(models.Tag).filter(models.Tag.id.in_(payload.tag_ids)).all()

    recipe = models.Recipe(
        **extracted.model_dump(),
        source_url=payload.url,
        source_type="web",
    )
    recipe.tags = tags
    db.add(recipe)
    db.commit()
    db.refresh(recipe)
    return recipe


@router.post("/image", response_model=schemas.RecipeOut)
async def capture_from_image(
    file: UploadFile = File(...),
    tag_ids: str = Form(default=""),   # comma-separated tag IDs from multipart form
    db: Session = Depends(get_db),
) -> schemas.RecipeOut:
    """
    Accept an uploaded image or scan, send to Claude vision, store in R2, save recipe.
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

    # Upload original + thumbnail to R2
    try:
        stored = storage_svc.upload_image(image_bytes, media_type)
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
    return recipe
