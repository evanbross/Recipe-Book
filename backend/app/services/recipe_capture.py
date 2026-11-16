# =============================================================================
# Copyright (c) 2026 ZombieTech LLC. All rights reserved.
#
# SPDX-License-Identifier: PolyForm-Strict-1.0.0
# See LICENSE in the project root for the full terms.
#
# Licensing inquiries: license@zombietech.biz
# =============================================================================
# ai: claude-opus-5-5 | 2026-11-15
"""
Recipe capture from a web page: the one implementation behind every entry point.

Two ways in, one pipeline:
  - capture_url():  the server fetches the page itself.
  - capture_html(): the caller supplies HTML its own browser already loaded
    (the browser extension), for sites that refuse server-side fetches.

Both parse the page, extract the recipe (JSON-LD first, Claude for the gaps),
resolve the Source tag, store the page image, and save the recipe.

All slow external work (page fetch, Claude, image download/upload) runs before
the first DB query, so no pooled connection is held across it. Errors are raised
as the domain exceptions below; the HTTP routes decide
the status code.
"""
import logging
from dataclasses import dataclass
from datetime import datetime, UTC
from urllib.parse import urljoin

import anthropic
import httpx
from botocore.exceptions import BotoCoreError, ClientError
from PIL import Image
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import models
from app.database import current_tenant_id  # ai: claude-opus-5-5 | 2026-11-16
from app.schemas import CaptureResult
from app.services import scraper as scraper_svc
from app.services import sources as sources_svc
from app.services import storage as storage_svc
from app.services import vision as vision_svc
from app.services.claude_client import ClaudeRefusalError
from app.services.media_types import SUPPORTED_IMAGE_MEDIA_TYPES

logger = logging.getLogger(__name__)


class PageFetchError(Exception):
    """The page could not be fetched. status_code is set when the site answered with an HTTP error."""

    def __init__(self, url: str, status_code: int | None) -> None:
        self.url = url
        self.status_code = status_code
        super().__init__(f"Fetch failed for {url} (HTTP {status_code})" if status_code else f"Fetch failed for {url}")


class RecipeExtractionError(Exception):
    """Neither JSON-LD nor Claude produced a recipe from the page."""


class RecipeSaveError(Exception):
    """The extracted recipe could not be written to the database."""


@dataclass(frozen=True)
class _ParsedPage:
    text: str
    og_image_url: str | None
    final_url: str
    jsonld_recipe: dict | None


def _trunc(value: str | None, max_len: int) -> str:
    return value[:max_len] if value else ""


class RecipeCaptureService:
    """Captures a recipe from a web page into the given session's database."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def capture_url(self, url: str, tag_ids: list[int]) -> models.Recipe:
        """Fetch the page server-side, then capture it.

        Raises UnsafeURLError (private/local destination), PageFetchError,
        RecipeExtractionError or RecipeSaveError.
        """
        logger.info("[capture] Starting URL capture for %s", url)
        try:
            page = _ParsedPage(*scraper_svc.fetch_page(url))
        except httpx.HTTPStatusError as exc:
            raise PageFetchError(url, exc.response.status_code) from exc
        except httpx.HTTPError as exc:
            raise PageFetchError(url, None) from exc
        return self._capture(url, page, tag_ids)

    def capture_html(self, url: str, html: str, tag_ids: list[int]) -> models.Recipe:
        """Capture from HTML the caller already loaded; the page itself is never fetched.

        Raises RecipeExtractionError or RecipeSaveError.
        """
        logger.info("[capture] Starting HTML capture for %s (%d chars)", url, len(html))
        return self._capture(url, _ParsedPage(*scraper_svc.parse_page_html(html, url)), tag_ids)

    # ── pipeline ──────────────────────────────────────────────────────────────

    def _capture(self, source_url: str, page: _ParsedPage, tag_ids: list[int]) -> models.Recipe:
        extracted = self._extract(source_url, page)
        source_name = sources_svc.resolve_source_name(page.final_url, page.jsonld_recipe)
        image_url = self._best_image_url(page)
        stored = self._store_image(image_url, extracted, source_url) if image_url else None

        # Slow work is done; from here on it's DB only.
        try:
            recipe = self._save(source_url, extracted, source_name, tag_ids, stored, image_url)
        except RecipeSaveError:
            if stored:
                self._discard_image(stored)
            raise

        if stored:
            try:
                storage_svc.tag_objects_with_recipe_id(stored["image_key"], stored.get("thumbnail_key"), recipe.id)
            except (BotoCoreError, ClientError) as exc:
                logger.warning("[capture] Failed to tag MinIO objects for recipe %d: %s", recipe.id, exc)

        logger.info("[capture] Saved recipe %d from %s", recipe.id, source_url)
        return recipe

    @staticmethod
    def _extract(source_url: str, page: _ParsedPage) -> CaptureResult:
        try:
            if page.jsonld_recipe:
                extracted = vision_svc.extract_from_jsonld(page.jsonld_recipe)
                if extracted.ingredients and extracted.instructions:
                    return extracted
                # JSON-LD was present but incomplete; fall back to Claude for the gaps.
            return vision_svc.extract_from_text(page.text)
        # Claude API failure / refusal / unparseable or schema-invalid reply (ValueError
        # covers json.JSONDecodeError and pydantic.ValidationError).
        except (anthropic.APIError, ClaudeRefusalError, ValueError) as exc:
            logger.warning("[capture] Extraction failed for %s: %s", source_url, exc)
            raise RecipeExtractionError(str(exc)) from exc

    @staticmethod
    def _best_image_url(page: _ParsedPage) -> str | None:
        """OG image first, then the JSON-LD image."""
        if page.og_image_url:
            return page.og_image_url
        if page.jsonld_recipe:
            jsonld_image = scraper_svc.extract_jsonld_image_url(page.jsonld_recipe)
            if jsonld_image:
                return urljoin(page.final_url, jsonld_image)
        return None

    def _store_image(self, image_url: str, extracted: CaptureResult, source_url: str) -> dict[str, str] | None:
        """Download the page image into MinIO. Non-fatal: None means "link the external URL instead"."""
        try:
            img_bytes, content_type = scraper_svc.fetch_page_image(image_url)
            if content_type not in SUPPORTED_IMAGE_MEDIA_TYPES:
                logger.warning("[capture] Image at %s has unsupported type '%s'; linking it instead", image_url, content_type)
                return None
            return storage_svc.upload_image(
                img_bytes,
                content_type,
                tenant_id=current_tenant_id(self._db),  # ai: claude-opus-5-5 | 2026-11-16
                metadata={
                    "recipe-title": _trunc(extracted.title, 512),
                    "source-type": "web",
                    "source-url": _trunc(source_url, 1024),
                    "source-image-url": _trunc(image_url, 1024),
                    "captured-at": datetime.now(UTC).isoformat(),
                    "app-name": "recipe-app",
                },
            )
        # Network / URL-guard (ValueError) / image decode (OSError, decompression bomb) / MinIO.
        except (httpx.HTTPError, ValueError, OSError, Image.DecompressionBombError,
                BotoCoreError, ClientError) as exc:
            logger.warning("[capture] Image download/store failed for %s (%s: %s); linking it instead",
                           image_url, type(exc).__name__, exc)
            return None

    @staticmethod
    def _discard_image(stored: dict[str, str]) -> None:
        """Remove an uploaded image whose recipe was never saved, so it isn't orphaned in MinIO."""
        try:
            storage_svc.delete_image(stored["image_key"], stored.get("thumbnail_key"))
        except (BotoCoreError, ClientError) as exc:
            logger.warning("[capture] Could not remove orphaned image %s: %s", stored["image_key"], exc)

    def _save(
        self,
        source_url: str,
        extracted: CaptureResult,
        source_name: str | None,
        tag_ids: list[int],
        stored: dict[str, str] | None,
        image_url: str | None,
    ) -> models.Recipe:
        try:
            tags = self._db.query(models.Tag).filter(models.Tag.id.in_(tag_ids)).all()
            source_tag = sources_svc.get_or_create_source_tag(self._db, source_name) if source_name else None
            if source_tag and source_tag not in tags:
                tags.append(source_tag)

            image_fields = stored if stored else {"image_url": image_url}
            recipe = models.Recipe(**extracted.model_dump(), source_url=source_url, source_type="web", **image_fields)
            recipe.tags = tags
            self._db.add(recipe)
            self._db.commit()
            self._db.refresh(recipe)
            return recipe
        except SQLAlchemyError as exc:
            self._db.rollback()
            logger.error("[capture] Database save failed for %s: %s", source_url, exc)
            raise RecipeSaveError(str(exc)) from exc
