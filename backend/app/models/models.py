from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, ForeignKey, Table, Index
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

    # Cloudflare R2 references
    image_key = Column(String(512), nullable=True)      # R2 object key for original image/scan
    image_url = Column(String(2048), nullable=True)     # Public R2 URL for display
    thumbnail_key = Column(String(512), nullable=True)
    thumbnail_url = Column(String(2048), nullable=True)

    # Full-text search vector (populated by DB trigger or application)
    search_vector = Column(TSVECTOR, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    tags = relationship("Tag", secondary=recipe_tags, back_populates="recipes")

    __table_args__ = (
        Index("ix_recipes_search_vector", "search_vector", postgresql_using="gin"),
    )
