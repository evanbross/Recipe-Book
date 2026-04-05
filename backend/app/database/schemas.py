from datetime import datetime
from typing import Optional
from pydantic import BaseModel


# ── Tag Category ──────────────────────────────────────────────────────────────

class TagCategoryBase(BaseModel):
    name: str
    slug: str

class TagCategoryCreate(TagCategoryBase):
    pass

class TagCategoryOut(TagCategoryBase):
    id: int
    model_config = {"from_attributes": True}


# ── Tag ───────────────────────────────────────────────────────────────────────

class TagBase(BaseModel):
    name: str
    slug: str
    category_id: Optional[int] = None

class TagCreate(TagBase):
    pass

class TagOut(TagBase):
    id: int
    category: Optional[TagCategoryOut] = None
    model_config = {"from_attributes": True}


# ── Recipe ────────────────────────────────────────────────────────────────────

class RecipeBase(BaseModel):
    title: str
    description: Optional[str] = None
    ingredients: Optional[str] = None
    instructions: Optional[str] = None
    servings: Optional[str] = None
    prep_time: Optional[str] = None
    cook_time: Optional[str] = None
    source_url: Optional[str] = None
    source_type: str = "manual"

class RecipeCreate(RecipeBase):
    tag_ids: list[int] = []

class RecipeUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    ingredients: Optional[str] = None
    instructions: Optional[str] = None
    servings: Optional[str] = None
    prep_time: Optional[str] = None
    cook_time: Optional[str] = None
    tag_ids: Optional[list[int]] = None

class RecipeOut(RecipeBase):
    id: int
    image_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    tags: list[TagOut] = []
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}

class RecipeListOut(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    thumbnail_url: Optional[str] = None
    source_type: str
    tags: list[TagOut] = []
    created_at: datetime
    model_config = {"from_attributes": True}


# ── Capture ───────────────────────────────────────────────────────────────────

class CaptureUrlRequest(BaseModel):
    url: str
    tag_ids: list[int] = []

class CaptureResult(BaseModel):
    """Structured recipe data extracted by Claude vision."""
    title: str
    description: Optional[str] = None
    ingredients: Optional[str] = None
    instructions: Optional[str] = None
    servings: Optional[str] = None
    prep_time: Optional[str] = None
    cook_time: Optional[str] = None


# ── Search ────────────────────────────────────────────────────────────────────

class SearchResult(BaseModel):
    total: int
    page: int
    page_size: int
    results: list[RecipeListOut]
