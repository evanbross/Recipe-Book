from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, func
from sqlalchemy.orm import Session
from app.database import get_db
from app import models, schemas

router = APIRouter(prefix="/search", tags=["search"])


@router.get("", response_model=schemas.SearchResult)
def search_recipes(
    q: str = Query(default="", description="Full-text search query"),
    tags: str = Query(default="", description="Comma-separated tag slugs, e.g. 'asian,soup'"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=100),
    db: Session = Depends(get_db),
) -> schemas.SearchResult:
    """
    Search recipes by text and/or tag slugs.
    Tag filtering is AND-based: results must match ALL specified tags.
    Text search uses PostgreSQL full-text search on title + ingredients + instructions.
    """
    query = db.query(models.Recipe)

    # Full-text filter
    if q.strip():
        ts_query = func.plainto_tsquery("english", q)
        query = query.filter(
            or_(
                models.Recipe.search_vector.op("@@")(ts_query),
                models.Recipe.title.ilike(f"%{q}%"),
            )
        )

    # Tag slug filter (AND logic — must match all requested tags)
    tag_slugs = [s.strip() for s in tags.split(",") if s.strip()]
    for slug in tag_slugs:
        tag = db.query(models.Tag).filter(models.Tag.slug == slug).first()
        if tag:
            query = query.filter(models.Recipe.tags.contains(tag))

    total = query.count()
    results = (
        query.order_by(models.Recipe.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return schemas.SearchResult(
        total=total,
        page=page,
        page_size=page_size,
        results=results,
    )
