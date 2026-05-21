from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, computed_field


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
    image_pending: bool = False
    tags: list[TagOut] = []
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}

class RecipeListOut(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    thumbnail_url: Optional[str] = None
    image_url: Optional[str] = None
    image_pending: bool = False
    source_url: Optional[str] = None
    source_type: str
    tags: list[TagOut] = []
    created_at: datetime
    model_config = {"from_attributes": True}


# ── Capture ───────────────────────────────────────────────────────────────────

class CaptureUrlRequest(BaseModel):
    url: str
    tag_ids: list[int] = []

class ScanRequest(BaseModel):
    url: Optional[str] = None
    html: Optional[str] = None
    base_url: Optional[str] = None  # required when html is supplied

class ScannedLink(BaseModel):
    url: str
    title: Optional[str] = None
    same_origin: bool = False

class ScanResponse(BaseModel):
    links: list[ScannedLink]
    total: int
    source_url: Optional[str] = None

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


# ── Tag Suggestion ────────────────────────────────────────────────────────────

class TagSuggestRequest(BaseModel):
    title: str
    description: Optional[str] = None
    ingredients: Optional[str] = None

class SuggestedNewTag(BaseModel):
    name: str
    category_name: Optional[str] = None

class TagSuggestResponse(BaseModel):
    existing_tag_ids: list[int]
    new_tags: list[SuggestedNewTag]


# ── Email Scan ────────────────────────────────────────────────────────────────

class EmailAuthStatus(BaseModel):
    authenticated: bool

class EmailConnectResponse(BaseModel):
    auth_url: str

class ScanLogEntry(BaseModel):
    sender: str
    subject: str
    folder: str = ""         # Gmail label or "Inbox" (or "Label + Inbox" if in both)
    result: str              # imported | candidate | no_recipe | error
    title: Optional[str] = None   # recipe title when result is imported/candidate
    reason: Optional[str] = None  # human-readable detail for no_recipe or error


class EmailScanStatus(BaseModel):
    running: bool
    processed: int = 0
    total: int = 0
    imported: int = 0
    already_scanned: int = 0
    no_recipe: int = 0
    errors: list[str] = []
    current_folder: Optional[str] = None
    started_at: Optional[str] = None
    last_completed: Optional[str] = None


class ScanReport(BaseModel):
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    total_processed: int = 0
    already_scanned: int = 0
    imported: int = 0
    no_recipe: int = 0
    error_count: int = 0
    entries: list[ScanLogEntry] = []

class EmailSettings(BaseModel):
    auto_import: bool = True
    labels: list[str] = ["Cooking"]
    scan_inbox: bool = False
    inbox_lookback_days: int = 30
    max_per_folder: int = 50

class EmailSettingsUpdate(BaseModel):
    auto_import: Optional[bool] = None
    labels: Optional[list[str]] = None
    scan_inbox: Optional[bool] = None
    inbox_lookback_days: Optional[int] = None
    max_per_folder: Optional[int] = None

class EmailCandidateOut(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    ingredients: Optional[str] = None
    instructions: Optional[str] = None
    servings: Optional[str] = None
    prep_time: Optional[str] = None
    cook_time: Optional[str] = None
    source_sender: Optional[str] = None
    source_subject: Optional[str] = None
    created_at: datetime
    model_config = {"from_attributes": True}


# ── Image Candidates ──────────────────────────────────────────────────────────

class ImageCandidateOut(BaseModel):
    id: int
    image_url: str
    score: int           # 0-100 confidence
    rank: int
    sender_domain: Optional[str] = None
    model_config = {"from_attributes": True}


class SelectImageRequest(BaseModel):
    image_url: str


# ── Watch List ────────────────────────────────────────────────────────────────

class WatchedSiteCreate(BaseModel):
    name: str
    url: str
    check_every_days: int = 7

class WatchedSiteUpdate(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    check_every_days: Optional[int] = None

class WatchedSiteOut(BaseModel):
    id: int
    name: str
    url: str
    check_every_days: int
    last_visited_at: Optional[datetime] = None
    created_at: datetime

    @computed_field
    @property
    def due(self) -> bool:
        if self.last_visited_at is None:
            return True
        lv = self.last_visited_at
        if lv.tzinfo is None:
            lv = lv.replace(tzinfo=timezone.utc)
        elapsed = (datetime.now(timezone.utc) - lv).total_seconds()
        return elapsed >= self.check_every_days * 86400

    model_config = {"from_attributes": True}
