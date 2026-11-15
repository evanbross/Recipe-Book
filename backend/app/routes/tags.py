import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas
from app.services import tagger as tagger_svc
from app.services.slugs import slugify

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tags", tags=["tags"])


@router.get("/categories", response_model=list[schemas.TagCategoryOut])
def list_categories(db: Session = Depends(get_db)) -> list[schemas.TagCategoryOut]:
    return db.query(models.TagCategory).order_by(models.TagCategory.name).all()


# ai: claude-opus-5-5 | 2026-11-14
def _slug_for(name: str) -> str:
    """Derive the slug server-side; clients never send one."""
    slug = slugify(name)
    if not slug:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Name must contain at least one letter or digit (A-Z, 0-9)",
        )
    return slug


# ai: claude-opus-5-5 | 2026-11-14
@router.post(
    "/categories", response_model=schemas.TagCategoryOut, status_code=status.HTTP_201_CREATED,
    responses={409: {"description": "A category with this name or slug already exists"}},
)
def create_category(payload: schemas.TagCategoryCreate, db: Session = Depends(get_db)) -> schemas.TagCategoryOut:
    cat = models.TagCategory(name=payload.name, slug=_slug_for(payload.name))
    db.add(cat)
    try:
        db.commit()
    except IntegrityError:
        # tag_categories has unique name and unique slug, and no foreign keys.
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="A category with this name already exists",
        )
    db.refresh(cat)
    return cat


@router.get("", response_model=list[schemas.TagOut])
def list_tags(category_id: Optional[int] = None, db: Session = Depends(get_db)) -> list[schemas.TagOut]:
    q = db.query(models.Tag)
    if category_id:
        q = q.filter(models.Tag.category_id == category_id)
    return q.order_by(models.Tag.name).all()


# ai: claude-opus-5-5 | 2026-11-14
@router.post(
    "", response_model=schemas.TagOut, status_code=status.HTTP_201_CREATED,
    responses={
        404: {"description": "category_id does not exist"},
        409: {"description": "A tag with this slug already exists in the category"},
    },
)
def create_tag(payload: schemas.TagCreate, db: Session = Depends(get_db)) -> schemas.TagOut:
    if payload.category_id is not None and db.get(models.TagCategory, payload.category_id) is None:
        raise HTTPException(status_code=404, detail="Category not found")
    tag = models.Tag(name=payload.name, slug=_slug_for(payload.name), category_id=payload.category_id)
    db.add(tag)
    try:
        db.commit()
    except IntegrityError:
        # The category was checked above, so this is uq_tags_category_id_slug.
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A tag with this name already exists in that category",
        )
    db.refresh(tag)
    return tag


@router.post("/suggest", response_model=schemas.TagSuggestResponse)
def suggest_tags(
    payload: schemas.TagSuggestRequest,
    db: Session = Depends(get_db),
) -> schemas.TagSuggestResponse:
    existing_tags = db.query(models.Tag).all()
    categories = db.query(models.TagCategory).all()
    try:
        return tagger_svc.suggest_tags(
            payload.title,
            payload.description,
            payload.ingredients,
            existing_tags,
            categories,
        )
    except Exception as exc:
        logger.warning("Tag suggestion failed, returning empty result: %s", exc)
        return schemas.TagSuggestResponse(existing_tag_ids=[], new_tags=[])


@router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tag(tag_id: int, db: Session = Depends(get_db)) -> None:
    tag = db.get(models.Tag, tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    db.delete(tag)
    db.commit()
