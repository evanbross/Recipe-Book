from datetime import datetime, timezone
from sqlalchemy import (
    Boolean, Column, Integer, String, Text, DateTime, ForeignKey, Table, Index
)
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import TSVECTOR
from app.database import Base

# Many-to-many join table: recipes <-> tags
recipe_tags = Table(
    "recipe_tags",
    Base.metadata,
    Column("recipe_id", Integer, ForeignKey("recipes.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class TagCategory(Base):
    """
    High-level grouping for tags, e.g. Cuisine, Course, Diet, Ingredient.
    Allows browsing tags by category independently.
    """
    __tablename__ = "tag_categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)   # e.g. "Cuisine"
    slug = Column(String(100), unique=True, nullable=False)   # e.g. "cuisine"

    tags = relationship("Tag", back_populates="category", cascade="all, delete-orphan")


class Tag(Base):
    """
    A tag such as 'Asian', 'Italian', 'Soup', 'Bread', 'Gluten-Free'.
    Belongs to exactly one TagCategory.
    """
    __tablename__ = "tags"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)                # e.g. "Asian"
    slug = Column(String(100), nullable=False)                # e.g. "asian"
    category_id = Column(Integer, ForeignKey("tag_categories.id", ondelete="SET NULL"), nullable=True)

    category = relationship("TagCategory", back_populates="tags")
    recipes = relationship("Recipe", secondary=recipe_tags, back_populates="tags")


class Recipe(Base):
    """
    Core recipe entity. Stores structured content extracted from web pages,
    images, or manual entry. Source image/page stored in Cloudflare R2.
    """
    __tablename__ = "recipes"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    ingredients = Column(Text, nullable=True)       # stored as plain text or JSON string
    instructions = Column(Text, nullable=True)
    servings = Column(String(50), nullable=True)
    prep_time = Column(String(50), nullable=True)
    cook_time = Column(String(50), nullable=True)
    source_url = Column(String(2048), nullable=True)    # original web URL if captured from web
    source_type = Column(String(50), nullable=False, default="manual")  # web | image | manual

    # MinIO references
    image_key = Column(String(512), nullable=True)
    image_url = Column(String(2048), nullable=True)
    thumbnail_key = Column(String(512), nullable=True)
    thumbnail_url = Column(String(2048), nullable=True)

    # True while an email-sourced recipe is waiting for the user to pick an image
    image_pending = Column(Boolean, nullable=False, default=False)

    # Full-text search vector (populated by DB trigger or application)
    search_vector = Column(TSVECTOR, nullable=True)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    tags = relationship("Tag", secondary=recipe_tags, back_populates="recipes")
    image_candidates = relationship(
        "RecipeImageCandidate", back_populates="recipe", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_recipes_search_vector", "search_vector", postgresql_using="gin"),
    )


class ScannedEmail(Base):
    """Tracks Gmail messages that have been processed to prevent re-scanning."""
    __tablename__ = "scanned_emails"

    id = Column(Integer, primary_key=True, index=True)
    gmail_message_id = Column(String(100), unique=True, nullable=False, index=True)
    subject = Column(String(500), nullable=True)
    sender = Column(String(255), nullable=True)
    email_date = Column(String(100), nullable=True)
    scanned_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    # "imported" | "candidate" | "discarded" | "no_recipe"
    disposition = Column(String(50), nullable=False)

    candidate = relationship("EmailRecipeCandidate", back_populates="scanned_email", uselist=False)


class EmailRecipeCandidate(Base):
    """Extracted recipe from email, queued for user review before importing."""
    __tablename__ = "email_recipe_candidates"

    id = Column(Integer, primary_key=True, index=True)
    scanned_email_id = Column(Integer, ForeignKey("scanned_emails.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    ingredients = Column(Text, nullable=True)
    instructions = Column(Text, nullable=True)
    servings = Column(String(50), nullable=True)
    prep_time = Column(String(50), nullable=True)
    cook_time = Column(String(50), nullable=True)
    source_sender = Column(String(255), nullable=True)
    source_subject = Column(String(500), nullable=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id", ondelete="SET NULL"), nullable=True)
    # "pending" | "imported" | "discarded"
    status = Column(String(50), nullable=False, default="pending")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    scanned_email = relationship("ScannedEmail", back_populates="candidate")
    recipe = relationship("Recipe")


class AppSetting(Base):
    """Key-value store for user-configurable app settings persisted in the DB."""
    __tablename__ = "app_settings"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=False)


class RecipeImageCandidate(Base):
    """Up to 3 candidate images for an email-sourced recipe, pending user selection."""
    __tablename__ = "recipe_image_candidates"

    id = Column(Integer, primary_key=True, index=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False)
    image_url = Column(String(2048), nullable=False)
    score = Column(Integer, nullable=False)        # 0-100 confidence
    rank = Column(Integer, nullable=False)         # display order (0 = highest confidence)
    selected = Column(Boolean, nullable=False, default=False)
    sender_domain = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    recipe = relationship("Recipe", back_populates="image_candidates")


class WatchedSite(Base):
    """A website the user wants to revisit manually on a recurring schedule."""
    __tablename__ = "watched_sites"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    url = Column(String(2048), nullable=False)
    check_every_days = Column(Integer, nullable=False, default=7)
    last_visited_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


class EmailImagePreference(Base):
    """Per-sender-domain record of which image the user tends to pick."""
    __tablename__ = "email_image_preferences"

    id = Column(Integer, primary_key=True, index=True)
    sender_domain = Column(String(255), unique=True, nullable=False, index=True)
    url_domain = Column(String(255), nullable=True)   # image host the user tends to pick
    preferred_rank = Column(Integer, nullable=True)   # rank (0-indexed) user tends to pick
    selection_count = Column(Integer, nullable=False, default=0)
    last_used_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
