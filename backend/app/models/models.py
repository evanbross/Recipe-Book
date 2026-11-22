# ai: claude-opus-5-5 | 2026-11-14
# Converted from legacy Column() to SQLAlchemy 2.x Mapped/mapped_column. Column
# types are spelled out wherever the Python-type default would differ from the
# migrated schema (Text vs VARCHAR, naive DateTime), so autogenerate stays clean.
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Table, Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, TenantScoped


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# Many-to-many join table: recipes <-> tags. A Core Table, so it keeps Column().
recipe_tags = Table(
    "recipe_tags",
    Base.metadata,
    Column("recipe_id", Integer, ForeignKey("recipes.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class TagCategory(TenantScoped, Base):
    """
    High-level grouping for tags, e.g. Cuisine, Course, Diet, Ingredient.
    Allows browsing tags by category independently.
    """
    __tablename__ = "tag_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))   # e.g. "Cuisine"
    slug: Mapped[str] = mapped_column(String(100))   # e.g. "cuisine"

    tags: Mapped[list["Tag"]] = relationship(back_populates="category", cascade="all, delete-orphan")

    # ai: claude-opus-5-5 | 2026-11-16
    # Names and slugs are unique per household, not globally.
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_tag_categories_tenant_id_name"),
        UniqueConstraint("tenant_id", "slug", name="uq_tag_categories_tenant_id_slug"),
    )


class Tag(TenantScoped, Base):
    """
    A tag such as 'Asian', 'Italian', 'Soup', 'Bread', 'Gluten-Free'.
    Belongs to at most one TagCategory; slugs are unique within a category per household.
    """
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))                # e.g. "Asian"
    slug: Mapped[str] = mapped_column(String(100))                # e.g. "asian"
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("tag_categories.id", ondelete="SET NULL")
    )

    category: Mapped["TagCategory | None"] = relationship(back_populates="tags")
    recipes: Mapped[list["Recipe"]] = relationship(secondary=recipe_tags, back_populates="tags")

    __table_args__ = (
        # NULLS NOT DISTINCT: uncategorized tags share one slug namespace too.
        # ai: claude-opus-5-5 | 2026-11-16
        UniqueConstraint(
            "tenant_id", "category_id", "slug", name="uq_tags_tenant_id_category_id_slug",
            postgresql_nulls_not_distinct=True,
        ),
    )


class Recipe(TenantScoped, Base):
    """
    Core recipe entity. Stores structured content extracted from web pages,
    images, email, or manual entry. Images are stored in MinIO.
    """
    __tablename__ = "recipes"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    ingredients: Mapped[str | None] = mapped_column(Text)   # plain text or JSON string
    instructions: Mapped[str | None] = mapped_column(Text)
    servings: Mapped[str | None] = mapped_column(Text)
    prep_time: Mapped[str | None] = mapped_column(Text)
    cook_time: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)    # original web URL if captured from web
    source_type: Mapped[str] = mapped_column(Text, default="manual")  # web | image | manual | email

    # MinIO references
    image_key: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(Text)
    thumbnail_key: Mapped[str | None] = mapped_column(Text)
    thumbnail_url: Mapped[str | None] = mapped_column(Text)

    # True while an email-sourced recipe is waiting for the user to pick an image
    image_pending: Mapped[bool] = mapped_column(Boolean, default=False)

    # Full-text search vector (populated by DB trigger or application)
    search_vector: Mapped[str | None] = mapped_column(TSVECTOR)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    tags: Mapped[list["Tag"]] = relationship(secondary=recipe_tags, back_populates="recipes")
    image_candidates: Mapped[list["RecipeImageCandidate"]] = relationship(
        back_populates="recipe", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_recipes_search_vector", "search_vector", postgresql_using="gin"),
        Index("ix_recipes_tenant_id", "tenant_id"),  # ai: claude-opus-5-5 | 2026-11-16
    )


class ScannedEmail(TenantScoped, Base):
    """Tracks Gmail messages that have been processed to prevent re-scanning."""
    __tablename__ = "scanned_emails"

    id: Mapped[int] = mapped_column(primary_key=True)
    gmail_message_id: Mapped[str] = mapped_column(String(100))
    subject: Mapped[str | None] = mapped_column(String(500))
    sender: Mapped[str | None] = mapped_column(String(255))
    email_date: Mapped[str | None] = mapped_column(String(100))
    scanned_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    # "imported" | "candidate" | "discarded" | "no_recipe"
    disposition: Mapped[str] = mapped_column(String(50))

    candidate: Mapped["EmailRecipeCandidate | None"] = relationship(back_populates="scanned_email")

    __table_args__ = (
        # ai: claude-opus-5-5 | 2026-11-16
        UniqueConstraint("tenant_id", "gmail_message_id", name="uq_scanned_emails_tenant_id_gmail_message_id"),
    )


class EmailRecipeCandidate(TenantScoped, Base):
    """Extracted recipe from email, queued for user review before importing."""
    __tablename__ = "email_recipe_candidates"

    id: Mapped[int] = mapped_column(primary_key=True)
    scanned_email_id: Mapped[int] = mapped_column(ForeignKey("scanned_emails.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    ingredients: Mapped[str | None] = mapped_column(Text)
    instructions: Mapped[str | None] = mapped_column(Text)
    servings: Mapped[str | None] = mapped_column(Text)
    prep_time: Mapped[str | None] = mapped_column(Text)
    cook_time: Mapped[str | None] = mapped_column(Text)
    source_sender: Mapped[str | None] = mapped_column(String(255))
    source_subject: Mapped[str | None] = mapped_column(String(500))
    recipe_id: Mapped[int | None] = mapped_column(ForeignKey("recipes.id", ondelete="SET NULL"))
    # "pending" | "imported" | "discarded"
    status: Mapped[str] = mapped_column(String(50), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    scanned_email: Mapped["ScannedEmail"] = relationship(back_populates="candidate")
    recipe: Mapped["Recipe | None"] = relationship()

    __table_args__ = (Index("ix_email_recipe_candidates_tenant_id", "tenant_id"),)  # ai: claude-opus-5-5 | 2026-11-16


class AppSetting(TenantScoped, Base):
    """Per-household key-value store for user-configurable app settings."""
    __tablename__ = "app_settings"

    # ai: claude-opus-5-5 | 2026-11-16
    # Primary key is (tenant_id, key): each household has its own settings.
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class SystemSetting(Base):
    """Server-wide settings. Secrets inside values are application-encrypted."""
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class RecipeImageCandidate(TenantScoped, Base):
    """Up to 3 candidate images for an email-sourced recipe, pending user selection."""
    __tablename__ = "recipe_image_candidates"

    id: Mapped[int] = mapped_column(primary_key=True)
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipes.id", ondelete="CASCADE"), index=True)
    image_url: Mapped[str] = mapped_column(String(2048))
    score: Mapped[int] = mapped_column(Integer)        # 0-100 confidence
    rank: Mapped[int] = mapped_column(Integer)         # display order (0 = highest confidence)
    selected: Mapped[bool] = mapped_column(Boolean, default=False)
    sender_domain: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    recipe: Mapped["Recipe"] = relationship(back_populates="image_candidates")

    __table_args__ = (Index("ix_recipe_image_candidates_tenant_id", "tenant_id"),)  # ai: claude-opus-5-5 | 2026-11-16


class WatchedSite(TenantScoped, Base):
    """A website the user wants to revisit manually on a recurring schedule."""
    __tablename__ = "watched_sites"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    url: Mapped[str] = mapped_column(String(2048))
    check_every_days: Mapped[int] = mapped_column(Integer, default=7)
    last_visited_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    __table_args__ = (Index("ix_watched_sites_tenant_id", "tenant_id"),)  # ai: claude-opus-5-5 | 2026-11-16


class EmailImagePreference(TenantScoped, Base):
    """Per-sender-domain record of which image the user tends to pick."""
    __tablename__ = "email_image_preferences"

    id: Mapped[int] = mapped_column(primary_key=True)
    sender_domain: Mapped[str] = mapped_column(String(255))
    url_domain: Mapped[str | None] = mapped_column(String(255))   # image host the user tends to pick
    preferred_rank: Mapped[int | None] = mapped_column(Integer)   # rank (0-indexed) user tends to pick
    selection_count: Mapped[int] = mapped_column(Integer, default=0)
    last_used_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    __table_args__ = (
        # ai: claude-opus-5-5 | 2026-11-16
        UniqueConstraint("tenant_id", "sender_domain", name="uq_email_image_preferences_tenant_id_sender_domain"),
    )
