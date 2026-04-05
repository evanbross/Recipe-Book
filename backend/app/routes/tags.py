from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app import models, schemas

router = APIRouter(prefix="/tags", tags=["tags"])


@router.get("/categories", response_model=list[schemas.TagCategoryOut])
def list_categories(db: Session = Depends(get_db)) -> list[schemas.TagCategoryOut]:
    return db.query(models.TagCategory).order_by(models.TagCategory.name).all()


@router.post("/categories", response_model=schemas.TagCategoryOut, status_code=status.HTTP_201_CREATED)
def create_category(payload: schemas.TagCategoryCreate, db: Session = Depends(get_db)) -> schemas.TagCategoryOut:
    cat = models.TagCategory(**payload.model_dump())
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


@router.get("", response_model=list[schemas.TagOut])
def list_tags(category_id: Optional[int] = None, db: Session = Depends(get_db)) -> list[schemas.TagOut]:
    q = db.query(models.Tag)
    if category_id:
        q = q.filter(models.Tag.category_id == category_id)
    return q.order_by(models.Tag.name).all()


@router.post("", response_model=schemas.TagOut, status_code=status.HTTP_201_CREATED)
def create_tag(payload: schemas.TagCreate, db: Session = Depends(get_db)) -> schemas.TagOut:
    tag = models.Tag(**payload.model_dump())
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag


@router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tag(tag_id: int, db: Session = Depends(get_db)) -> None:
    tag = db.get(models.Tag, tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    db.delete(tag)
    db.commit()
