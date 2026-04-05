"""
Vision service: uses Claude API to extract structured recipe data
from images (photos, scans) or raw web page text.
"""
import base64
import json
from typing import Optional
import anthropic
from app.config import settings
from app.schemas import CaptureResult

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


def _parse_claude_response(text: str) -> CaptureResult:
    """Parse Claude's JSON response into a CaptureResult."""
    clean = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    data = json.loads(clean)
    return CaptureResult(**data)


def extract_from_image_bytes(image_bytes: bytes, media_type: str = "image/jpeg") -> CaptureResult:
    """
    Extract recipe from an uploaded image (photo or scan).
    Sends the image directly to Claude vision.
    """
    b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

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

    return _parse_claude_response(response.content[0].text)


def extract_from_text(page_text: str) -> CaptureResult:
    """
    Extract recipe from raw text (scraped web page content).
    """
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

    return _parse_claude_response(response.content[0].text)
