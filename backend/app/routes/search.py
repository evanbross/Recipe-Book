"""
Search routes: full-text and tag-based recipe search.
"""
from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, or_
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/search", tags=["search"])


def _parse_tsquery(raw: str) -> str:
    """
    Convert a natural-language boolean query to a PostgreSQL tsquery string.

    User syntax  →  tsquery
      AND / and  →  &  (also implicit between adjacent words)
      OR  / or   →  |
      NOT / not  →  !
      -word      →  !word
      word*      →  word:*  (prefix wildcard)
      ( )        →  ( )     (passed through)
    """
    q = re.sub(r'\bAND\b', '&', raw,  flags=re.IGNORECASE)
    q = re.sub(r'\bOR\b',  '|', q,    flags=re.IGNORECASE)
    q = re.sub(r'\bNOT\b', '!', q,    flags=re.IGNORECASE)
    q = re.sub(r'(?<!\w)-(\w)', r'!\1', q)   # -word → !word

    tokens = re.findall(r'[()&|!]|[\w]+\*?', q)
    parts: list[str] = []
    need_op = False   # True when the previous token was a term or ')'

    for tok in tokens:
        if tok in ('&', '|'):
            parts.append(tok)
            need_op = False
        elif tok == '!':
            if need_op:
                parts.append('&')
            parts.append('!')
            need_op = False
        elif tok == '(':
            if need_op:
                parts.append('&')
            parts.append('(')
            need_op = False
        elif tok == ')':
            parts.append(')')
            need_op = True
        else:
            if need_op:
                parts.append('&')
            if tok.endswith('*'):
                word = tok[:-1]
                if word:
                    parts.append(f"{word.lower()}:*")
                    need_op = True
            elif tok:
                parts.append(tok.lower())
                need_op = True

    return ' '.join(parts)


@router.get("", response_model=schemas.SearchResult)
def search_recipes(
    q: str = Query(default=""),
    tag_ids: str = Query(default="", description="Comma-separated tag IDs"),
    tag_mode: str = Query(default="and", pattern="^(and|or)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=100),
    db: Session = Depends(get_db),
) -> schemas.SearchResult:
    """
    Search recipes by text and/or tags.

    Text query supports: AND, OR, NOT, parentheses, * wildcards.
    Tag mode: 'and' = must have ALL tags,  'or' = must have ANY tag.
    """
    query = db.query(models.Recipe)

    # ── Text filter ───────────────────────────────────────────────────────────
    if q.strip():
        text_q = q.strip()
        parsed_ts = _parse_tsquery(text_q)

        # Content words for ILIKE fallback (skip boolean keywords)
        content_words = [
            w for w in re.findall(r'\b\w{2,}\b', text_q, re.IGNORECASE)
            if w.lower() not in ('and', 'or', 'not')
        ][:8]

        conditions = []

        if parsed_ts:
            conditions.append(
                models.Recipe.search_vector.op("@@")(func.to_tsquery("english", parsed_ts))
            )

        # ILIKE fallback: each content word must appear in at least one column.
        # This catches recipes whose search_vector hasn't been populated yet.
        if content_words:
            per_word = [
                or_(
                    models.Recipe.title.ilike(f"%{w}%"),
                    models.Recipe.ingredients.ilike(f"%{w}%"),
                    models.Recipe.instructions.ilike(f"%{w}%"),
                )
                for w in content_words
            ]
            conditions.append(and_(*per_word))

        if conditions:
            query = query.filter(or_(*conditions))

    # ── Tag filter ────────────────────────────────────────────────────────────
    ids = [int(i) for i in tag_ids.split(",") if i.strip().isdigit()]
    if ids:
        if tag_mode == "or":
            # Any one of the tags must be present
            query = query.filter(models.Recipe.tags.any(models.Tag.id.in_(ids)))
        else:
            # All tags must be present (AND)
            for tid in ids:
                query = query.filter(models.Recipe.tags.any(models.Tag.id == tid))

    # ── Execute ───────────────────────────────────────────────────────────────
    try:
        total = query.count()
        results = (
            query.order_by(models.Recipe.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
    except DBAPIError as exc:
        logger.warning("Search query failed (malformed tsquery?): %s", exc)
        db.rollback()
        fallback = db.query(models.Recipe).filter(
            models.Recipe.title.ilike(f"%{q.strip()}%")
        )
        total = fallback.count()
        results = (
            fallback.order_by(models.Recipe.created_at.desc())
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
