from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app import models, schemas

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
    from app.services import storage as storage_svc
    recipe = _get_or_404(db, recipe_id)
    if recipe.image_key:
        storage_svc.delete_image(recipe.image_key, recipe.thumbnail_key)
    db.delete(recipe)
    db.commit()
