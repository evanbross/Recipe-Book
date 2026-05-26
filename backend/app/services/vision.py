"""
Vision service: uses Claude API to extract structured recipe data
from images (photos, scans) or raw web page text.
"""
import base64
import json
import logging
import re
from typing import Optional
import anthropic
from app.config import settings
from app.schemas import CaptureResult

logger = logging.getLogger(__name__)
client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

EXTRACTION_PROMPT = """
You are a recipe extraction assistant. Extract the recipe from the provided content and return
a JSON object with exactly these fields (use null for any field you cannot find):

{
  "title": "Recipe name",
  "description": "Brief description or notes",
  "ingredients": "Full ingredients list, one per line",
  "instructions": "Step-by-step instructions, one step per line",
  "servings": "e.g. 4 servings",
  "prep_time": "e.g. 15 minutes",
  "cook_time": "e.g. 30 minutes"
}

Return ONLY the JSON object. No markdown, no explanation, no extra text.
""".strip()


def _parse_iso_duration(value: object) -> str | None:
    """Convert an ISO 8601 duration string like 'PT1H30M' to '1 hour 30 minutes'."""
    if not value:
        return None
    s = str(value).strip()
    match = re.fullmatch(r"P(?:(\d+)D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s)
    if not match:
        return s  # already plain text (e.g. "30 minutes")
    days, hours, minutes, seconds = match.groups()
    parts: list[str] = []
    if days:
        parts.append(f"{days} day{'s' if int(days) != 1 else ''}")
    if hours:
        parts.append(f"{hours} hour{'s' if int(hours) != 1 else ''}")
    if minutes:
        parts.append(f"{minutes} minute{'s' if int(minutes) != 1 else ''}")
    if seconds:
        parts.append(f"{seconds} second{'s' if int(seconds) != 1 else ''}")
    return " ".join(parts) or None


def _jsonld_ingredients(value: object) -> str | None:
    if not value:
        return None
    if isinstance(value, str):
        return value.strip() or None
    return "\n".join(str(i) for i in value) or None


def _jsonld_instructions(value: object) -> str | None:
    if not value:
        return None
    if isinstance(value, str):
        return value.strip() or None
    steps: list[str] = []
    for i, step in enumerate(value, 1):
        if isinstance(step, str):
            steps.append(f"{i}. {step}")
        elif isinstance(step, dict):
            text = step.get("text") or step.get("name") or ""
            steps.append(f"{i}. {text}")
    return "\n".join(steps) or None


def _jsonld_servings(value: object) -> str | None:
    if not value:
        return None
    if isinstance(value, list):
        return str(value[0]) if value else None
    return str(value).strip() or None


def extract_from_jsonld(recipe_data: dict) -> CaptureResult:
    """
    Build a CaptureResult directly from a JSON-LD Recipe dict.
    No Claude API call — the structured data is already authoritative.
    """
    logger.info("[vision] Extracting from JSON-LD: %s", recipe_data.get("name", "unknown"))
    return CaptureResult(
        title=recipe_data.get("name") or "Untitled Recipe",
        description=recipe_data.get("description"),
        ingredients=_jsonld_ingredients(recipe_data.get("recipeIngredient")),
        instructions=_jsonld_instructions(recipe_data.get("recipeInstructions")),
        servings=_jsonld_servings(recipe_data.get("recipeYield")),
        prep_time=_parse_iso_duration(recipe_data.get("prepTime")),
        cook_time=_parse_iso_duration(recipe_data.get("cookTime")),
    )


def _parse_claude_response(text: str) -> CaptureResult:
    """Parse Claude's JSON response into a CaptureResult."""
    clean = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    data = json.loads(clean)
    data["title"] = data.get("title") or "Untitled Recipe"
    return CaptureResult(**data)


def extract_from_image_bytes(image_bytes: bytes, media_type: str = "image/jpeg") -> CaptureResult:
    """
    Extract recipe from an uploaded image (photo or scan).
    Sends the image directly to Claude vision.
    """
    logger.info("[vision] Calling Claude vision for image (%s, %d bytes)", media_type, len(image_bytes))
    b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    try:
        response = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=2048,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": EXTRACTION_PROMPT,
                        },
                    ],
                }
            ],
        )
    except Exception as exc:
        logger.error("[vision] Claude vision API failed: %s", exc)
        raise

    try:
        result = _parse_claude_response(response.content[0].text)
    except Exception as exc:
        logger.error("[vision] Failed to parse Claude response: %s", exc)
        raise

    logger.info("[vision] Claude vision extraction successful: %s", result.title)
    return result


def extract_from_text(page_text: str) -> CaptureResult:
    """
    Extract recipe from raw text (scraped web page content).
    """
    logger.info("[vision] Calling Claude text extraction (%d chars)", len(page_text))
    try:
        response = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=2048,
            messages=[
                {
                    "role": "user",
                    "content": f"{EXTRACTION_PROMPT}\n\nContent to extract from:\n\n{page_text[:8000]}",
                }
            ],
        )
    except Exception as exc:
        logger.error("[vision] Claude text extraction API failed: %s", exc)
        raise

    try:
        result = _parse_claude_response(response.content[0].text)
    except Exception as exc:
        logger.error("[vision] Failed to parse Claude response: %s", exc)
        raise

    logger.info("[vision] Claude text extraction successful: %s", result.title)
    return result
