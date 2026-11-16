# =============================================================================
# Copyright (c) 2026 ZombieTech LLC. All rights reserved.
#
# SPDX-License-Identifier: PolyForm-Strict-1.0.0
# See LICENSE in the project root for the full terms.
#
# Licensing inquiries: license@zombietech.biz
# =============================================================================
# ai: claude-opus-5-5 | 2026-11-16
"""
Serve stored recipe images through the API, never straight from MinIO.

The bucket stays private. An image is served only when one of the requesting
household's recipes references its key; the household filter on the session
makes that lookup household-scoped, so another household's key is a 404,
indistinguishable from a key that doesn't exist.
"""
import logging

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.services import storage as storage_svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/images", tags=["images"])

# Keys are random (uuid), so content under a key never changes: let the browser
# keep it. "private" keeps shared caches from storing one household's images.
_CACHE_CONTROL = "private, max-age=604800, immutable"


@router.get(
    "/{key:path}",
    response_class=Response,
    responses={200: {"content": {"image/*": {}}}, 404: {"description": "No such image for this household"}},
)
def get_image(key: str, db: Session = Depends(get_db)) -> Response:
    # A plain ORM select on Recipe, so the household filter applies to it.
    owner_id = db.scalar(
        select(models.Recipe.id)
        .where(or_(models.Recipe.image_key == key, models.Recipe.thumbnail_key == key))
        .limit(1)
    )
    if owner_id is None:
        raise HTTPException(status_code=404, detail="Image not found")
    try:
        content, content_type = storage_svc.get_image(key)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
            raise HTTPException(status_code=404, detail="Image not found")
        logger.warning("[images] MinIO error for %s: %s", key, exc)
        raise HTTPException(status_code=502, detail="Image storage error")
    except BotoCoreError as exc:
        logger.warning("[images] MinIO unreachable for %s: %s", key, exc)
        raise HTTPException(status_code=502, detail="Image storage error")
    return Response(content=content, media_type=content_type, headers={"Cache-Control": _CACHE_CONTROL})
