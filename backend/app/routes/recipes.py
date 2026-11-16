from datetime import datetime, UTC

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import current_tenant_id, get_db  # ai: claude-opus-5-5 | 2026-11-16
from app import models, schemas
from app.services import image_candidates as img_cand_svc
from app.services.media_types import SUPPORTED_IMAGE_MEDIA_TYPES  # ai: claude-opus-5-5 | 2026-11-15
from app.services import scraper as scraper_svc
from app.services import storage as storage_svc

router = APIRouter(prefix="/recipes", tags=["recipes"])


def _get_or_404(db: Session, recipe_id: int) -> models.Recipe:
    recipe = db.get(models.Recipe, recipe_id)
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")
    return recipe


@router.get("", response_model=list[schemas.RecipeListOut])
def list_recipes(skip: int = 0, limit: int = 24, db: Session = Depends(get_db)) -> list[schemas.RecipeListOut]:
    return db.query(models.Recipe).order_by(models.Recipe.created_at.desc()).offset(skip).limit(limit).all()


@router.get("/{recipe_id}", response_model=schemas.RecipeOut)
def get_recipe(recipe_id: int, db: Session = Depends(get_db)) -> schemas.RecipeOut:
    return _get_or_404(db, recipe_id)


@router.post("", response_model=schemas.RecipeOut, status_code=status.HTTP_201_CREATED)
def create_recipe(payload: schemas.RecipeCreate, db: Session = Depends(get_db)) -> schemas.RecipeOut:
    tags = db.query(models.Tag).filter(models.Tag.id.in_(payload.tag_ids)).all()
    recipe = models.Recipe(**payload.model_dump(exclude={"tag_ids"}))
    recipe.tags = tags
    db.add(recipe)
    db.commit()
    db.refresh(recipe)
    return recipe


@router.patch("/{recipe_id}", response_model=schemas.RecipeOut)
def update_recipe(recipe_id: int, payload: schemas.RecipeUpdate, db: Session = Depends(get_db)) -> schemas.RecipeOut:
    recipe = _get_or_404(db, recipe_id)
    data = payload.model_dump(exclude_unset=True)

    if "tag_ids" in data:
        recipe.tags = db.query(models.Tag).filter(models.Tag.id.in_(data.pop("tag_ids"))).all()

    for field, value in data.items():
        setattr(recipe, field, value)

    db.commit()
    db.refresh(recipe)
    return recipe


@router.delete("/{recipe_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_recipe(recipe_id: int, db: Session = Depends(get_db)) -> None:
    recipe = _get_or_404(db, recipe_id)
    if recipe.image_key:
        storage_svc.delete_image(recipe.image_key, recipe.thumbnail_key)
    db.delete(recipe)
    db.commit()


# ── Image candidate endpoints ─────────────────────────────────────────────────

@router.get("/{recipe_id}/image-candidates", response_model=list[schemas.ImageCandidateOut])
def get_image_candidates(recipe_id: int, db: Session = Depends(get_db)) -> list[schemas.ImageCandidateOut]:
    _get_or_404(db, recipe_id)
    return (
        db.query(models.RecipeImageCandidate)
        .filter(models.RecipeImageCandidate.recipe_id == recipe_id)
        .order_by(models.RecipeImageCandidate.rank)
        .all()
    )


@router.post("/{recipe_id}/select-image", response_model=schemas.RecipeOut)
def select_recipe_image(
    recipe_id: int,
    payload: schemas.SelectImageRequest,
    db: Session = Depends(get_db),
) -> schemas.RecipeOut:
    recipe = _get_or_404(db, recipe_id)

    try:
        img_bytes, content_type = scraper_svc.fetch_page_image(payload.image_url)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Failed to fetch image: {exc}")

    if content_type not in SUPPORTED_IMAGE_MEDIA_TYPES:
        raise HTTPException(status_code=415, detail=f"Unsupported image type: {content_type}")

    try:
        stored = storage_svc.upload_image(
            img_bytes,
            content_type,
            tenant_id=current_tenant_id(db),  # ai: claude-opus-5-5 | 2026-11-16
            metadata={
                "source-type": "email",
                "recipe-title": recipe.title[:512],
                "captured-at": datetime.now(UTC).isoformat(),
                "app-name": "recipe-app",
            },
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Storage upload failed: {exc}")

    # Determine which candidate was selected (for preference learning)
    candidates = (
        db.query(models.RecipeImageCandidate)
        .filter(models.RecipeImageCandidate.recipe_id == recipe_id)
        .order_by(models.RecipeImageCandidate.rank)
        .all()
    )
    selected_rank = 0
    sender_domain = ""
    for c in candidates:
        c.selected = c.image_url == payload.image_url
        if c.selected:
            selected_rank = c.rank
            sender_domain = c.sender_domain or ""

    recipe.image_key = stored["image_key"]
    recipe.image_url = None  # ai: claude-opus-5-5 | 2026-11-16 (stored image: URL derived from the key)
    recipe.thumbnail_key = stored["thumbnail_key"]
    recipe.thumbnail_url = None
    recipe.image_pending = False

    db.commit()
    db.refresh(recipe)

    storage_svc.tag_objects_with_recipe_id(
        stored["image_key"], stored.get("thumbnail_key"), recipe_id
    )

    if sender_domain:
        img_cand_svc.update_preference(db, sender_domain, payload.image_url, selected_rank)

    return recipe


@router.delete("/{recipe_id}/image-pending", status_code=status.HTTP_204_NO_CONTENT)
def skip_image_selection(recipe_id: int, db: Session = Depends(get_db)) -> None:
    """Dismiss the image picker without selecting — clears the image_pending flag."""
    recipe = _get_or_404(db, recipe_id)
    recipe.image_pending = False
    db.commit()
