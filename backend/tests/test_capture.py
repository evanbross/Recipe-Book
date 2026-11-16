from unittest.mock import patch

import httpx
import pytest
from sqlalchemy.exc import SQLAlchemyError

from app import models
from app.schemas import CaptureResult
from app.services.claude_client import ClaudeRefusalError


@pytest.fixture()
def capture_result():
    return CaptureResult(
        title="Mocked Recipe",
        description="A test recipe",
        ingredients="1 cup flour\n2 eggs",
        instructions="Mix and bake.",
        servings="4",
        prep_time="10 minutes",
        cook_time="30 minutes",
    )


# ── URL capture ───────────────────────────────────────────────────────────────

def test_capture_url_success(client, capture_result):
    with (
        patch("app.services.recipe_capture.scraper_svc.fetch_page",
              return_value=("some page text", None, "https://example.com/recipe", None)),
        patch("app.services.recipe_capture.vision_svc.extract_from_text", return_value=capture_result),
    ):
        response = client.post("/capture/url", json={"url": "https://example.com/recipe"})

    payload = response.json()
    assert response.status_code == 200
    assert payload["title"] == "Mocked Recipe"
    assert payload["source_type"] == "web"
    assert payload["source_url"] == "https://example.com/recipe"


def test_capture_url_scraper_failure(client):
    with patch("app.services.recipe_capture.scraper_svc.fetch_page",
               side_effect=httpx.ConnectTimeout("timeout")):
        response = client.post("/capture/url", json={"url": "https://example.com/recipe"})

    assert response.status_code == 422
    assert "Failed to fetch URL" in response.json()["detail"]


# ai: claude-opus-5-5 | 2026-11-15
def test_capture_url_blocked_site_reports_status_and_alternatives(client):
    request = httpx.Request("GET", "https://example.com/recipe")
    refused = httpx.HTTPStatusError("403", request=request, response=httpx.Response(403, request=request))
    with patch("app.services.recipe_capture.scraper_svc.fetch_page", side_effect=refused):
        response = client.post("/capture/url", json={"url": "https://example.com/recipe"})

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "HTTP 403" in detail
    assert "example.com blocks automated downloads" in detail  # ai: claude-opus-5-5 | 2026-11-16
    assert "browser extension" in detail
    assert "screenshot" in detail


# ai: claude-opus-5-5 | 2026-11-16
@pytest.mark.parametrize(("status", "expected"), [
    (404, "page doesn't exist (HTTP 404)"),
    (500, "returned an error (HTTP 500)"),
])
def test_capture_url_non_blocking_http_errors_do_not_suggest_extension(client, status, expected):
    request = httpx.Request("GET", "https://www.example.com/recipe")
    failed = httpx.HTTPStatusError(str(status), request=request, response=httpx.Response(status, request=request))
    with patch("app.services.recipe_capture.scraper_svc.fetch_page", side_effect=failed):
        response = client.post("/capture/url", json={"url": "https://www.example.com/recipe"})

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert expected in detail
    assert "example.com" in detail and "www." not in detail
    assert "extension" not in detail


@pytest.mark.parametrize("error", [ValueError("unparseable reply"), ClaudeRefusalError("declined")])
def test_capture_url_vision_failure(client, error):
    with (
        patch("app.services.recipe_capture.scraper_svc.fetch_page", return_value=("text", None, "https://example.com/recipe", None)),
        patch("app.services.recipe_capture.vision_svc.extract_from_text", side_effect=error),
    ):
        response = client.post("/capture/url", json={"url": "https://example.com/recipe"})

    assert response.status_code == 422
    assert "Claude extraction failed" in response.json()["detail"]


def test_capture_url_with_tags(client, make_tag, capture_result):
    tag = make_tag(name="Asian", slug="asian")

    with (
        patch("app.services.recipe_capture.scraper_svc.fetch_page",
              return_value=("some page text", None, "https://example.com/recipe", None)),
        patch("app.services.recipe_capture.vision_svc.extract_from_text", return_value=capture_result),
    ):
        response = client.post(
            "/capture/url",
            json={"url": "https://example.com/recipe", "tag_ids": [tag.id]},
        )

    # ai: claude-opus-5-5 | 2026-11-11
    # capture_from_url also attaches an auto-derived source tag (example.com →
    # "Example", under the Source category) alongside the caller's tag_ids.
    payload = response.json()
    assert response.status_code == 200
    tags_by_id = {t["id"]: t for t in payload["tags"]}
    assert len(tags_by_id) == 2
    assert tag.id in tags_by_id
    source_tags = [t for t in payload["tags"] if t["id"] != tag.id]
    assert source_tags[0]["name"] == "Example"


# ── URL capture — OG image stored in MinIO ────────────────────────────────────

def test_capture_url_og_image_stored_in_minio(client, capture_result):
    """OG image is downloaded and stored; recipe gets MinIO keys, not external URL."""
    uploaded = {"image_key": "tenants/1/originals/abc.jpg", "thumbnail_key": "tenants/1/thumbnails/abc.jpg"}
    with (
        patch("app.services.recipe_capture.scraper_svc.fetch_page",
              return_value=("page text", "https://example.com/image.jpg", "https://example.com/recipe", None)),
        patch("app.services.recipe_capture.vision_svc.extract_from_text", return_value=capture_result),
        patch("app.services.recipe_capture.scraper_svc.fetch_page_image",
              return_value=(b"\xff\xd8\xff\xe0", "image/jpeg")),
        patch("app.services.recipe_capture.storage_svc.upload_image", return_value=uploaded),
        patch("app.services.recipe_capture.storage_svc.tag_objects_with_recipe_id"),
    ):
        response = client.post("/capture/url", json={"url": "https://example.com/recipe"})

    assert response.status_code == 200
    payload = response.json()
    # ai: claude-opus-5-5 | 2026-11-16 -- stored images are served through the API, never MinIO
    assert payload["image_url"] == "/api/images/tenants/1/originals/abc.jpg"
    assert payload["thumbnail_url"] == "/api/images/tenants/1/thumbnails/abc.jpg"
    assert "image_key" not in payload


def test_capture_url_og_image_download_fails_uses_external_url(client, capture_result):
    """If OG image download fails, recipe falls back to external URL."""
    with (
        patch("app.services.recipe_capture.scraper_svc.fetch_page",
              return_value=("page text", "https://example.com/image.jpg", "https://example.com/recipe", None)),
        patch("app.services.recipe_capture.vision_svc.extract_from_text", return_value=capture_result),
        patch("app.services.recipe_capture.scraper_svc.fetch_page_image",
              side_effect=httpx.RequestError("timeout")),
    ):
        response = client.post("/capture/url", json={"url": "https://example.com/recipe"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["image_url"] == "https://example.com/image.jpg"
    assert payload["thumbnail_url"] is None


def test_capture_url_og_image_unsupported_type_falls_back(client, capture_result):
    """Unsupported OG image content-type skips MinIO; recipe gets external URL."""
    with (
        patch("app.services.recipe_capture.scraper_svc.fetch_page",
              return_value=("page text", "https://example.com/image.svg", "https://example.com/recipe", None)),
        patch("app.services.recipe_capture.vision_svc.extract_from_text", return_value=capture_result),
        patch("app.services.recipe_capture.scraper_svc.fetch_page_image",
              return_value=(b"<svg/>", "image/svg+xml")),
    ):
        response = client.post("/capture/url", json={"url": "https://example.com/recipe"})

    assert response.status_code == 200
    assert response.json()["image_url"] == "https://example.com/image.svg"
    assert response.json()["thumbnail_url"] is None


# ai: claude-opus-5-5 | 2026-11-15
# ── HTML capture (page HTML supplied by the user's browser) ──────────────────

_JSONLD_PAGE = """<html><head>
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "Recipe", "name": "Browser Soup",
 "recipeIngredient": ["1 onion", "2 cups stock"],
 "recipeInstructions": [{"@type": "HowToStep", "text": "Simmer."}]}
</script></head><body><h1>Browser Soup</h1></body></html>"""


def test_capture_html_uses_supplied_html_without_fetching_the_page(client):
    # Real parse + JSON-LD extraction + Source tag + DB write; only the page fetch
    # is booby-trapped, to prove the server never requests the page itself.
    with patch("app.services.recipe_capture.scraper_svc.fetch_page") as fetch:
        response = client.post("/capture/html", json={
            "url": "https://www.example.com/soup", "html": _JSONLD_PAGE,
        })

    assert response.status_code == 200, response.text
    fetch.assert_not_called()
    payload = response.json()
    assert payload["title"] == "Browser Soup"
    assert payload["ingredients"] == "1 onion\n2 cups stock"
    assert payload["source_url"] == "https://www.example.com/soup"
    assert [t["name"] for t in payload["tags"]] == ["Example"]


@pytest.mark.parametrize("body", [
    {"url": "javascript:alert(1)", "html": "<p>x</p>"},
    {"url": "https://example.com/r", "html": ""},
])
def test_capture_html_rejects_invalid_payloads(client, body):
    assert client.post("/capture/html", json=body).status_code == 422


def test_capture_save_failure_discards_the_uploaded_image(client, capture_result):
    stored = {"image_key": "originals/x.jpg", "image_url": "u", "thumbnail_key": "thumbnails/x.jpg", "thumbnail_url": "t"}
    with (
        patch("app.services.recipe_capture.scraper_svc.fetch_page",
              return_value=("text", "https://example.com/i.jpg", "https://example.com/r", None)),
        patch("app.services.recipe_capture.vision_svc.extract_from_text", return_value=capture_result),
        patch("app.services.recipe_capture.scraper_svc.fetch_page_image", return_value=(b"img", "image/jpeg")),
        patch("app.services.recipe_capture.storage_svc.upload_image", return_value=stored),
        patch("app.services.recipe_capture.sources_svc.get_or_create_source_tag",
              side_effect=SQLAlchemyError("db down")),
        patch("app.services.recipe_capture.storage_svc.delete_image") as delete,
    ):
        response = client.post("/capture/url", json={"url": "https://example.com/r"})

    assert response.status_code == 500
    delete.assert_called_once_with("originals/x.jpg", "thumbnails/x.jpg")


# ── Image capture — existing tests ────────────────────────────────────────────

def test_capture_image_success(client, capture_result):
    uploaded = {"image_key": "tenants/1/originals/test.jpg", "thumbnail_key": "tenants/1/thumbnails/test.jpg"}

    with (
        patch("app.routes.capture.vision_svc.extract_from_image_bytes",
              return_value=capture_result),
        patch("app.routes.capture.storage_svc.upload_image", return_value=uploaded),
        patch("app.routes.capture.storage_svc.tag_objects_with_recipe_id"),
    ):
        response = client.post(
            "/capture/image",
            files={"file": ("test.jpg", b"\xff\xd8\xff\xe0", "image/jpeg")},
        )

    payload = response.json()
    assert response.status_code == 200
    assert payload["source_type"] == "image"
    assert payload["image_url"] == "/api/images/tenants/1/originals/test.jpg"


def test_capture_image_unsupported_media_type(client):
    response = client.post(
        "/capture/image",
        files={"file": ("test.pdf", b"%PDF-1.5", "application/pdf")},
    )

    assert response.status_code == 415
    assert "Unsupported media type" in response.json()["detail"]


def test_capture_image_vision_failure(client):
    with patch(
        "app.routes.capture.vision_svc.extract_from_image_bytes",
        side_effect=Exception("vision error"),
    ):
        response = client.post(
            "/capture/image",
            files={"file": ("test.jpg", b"\xff\xd8\xff\xe0", "image/jpeg")},
        )

    assert response.status_code == 422
    assert "Claude extraction failed" in response.json()["detail"]


def test_capture_image_storage_failure(client, capture_result):
    with (
        patch("app.routes.capture.vision_svc.extract_from_image_bytes",
              return_value=capture_result),
        patch("app.routes.capture.storage_svc.upload_image",
              side_effect=Exception("MinIO error")),
    ):
        response = client.post(
            "/capture/image",
            files={"file": ("test.jpg", b"\xff\xd8\xff\xe0", "image/jpeg")},
        )

    assert response.status_code == 500
    assert "Storage upload failed" in response.json()["detail"]


# ── Image capture — metadata and tagging ─────────────────────────────────────

def test_capture_image_upload_called_with_metadata(client, capture_result):
    """upload_image receives the expected metadata keys."""
    uploaded = {
        "image_key": "originals/test.jpg",
        "image_url": "http://minio/originals/test.jpg",
        "thumbnail_key": "thumbnails/test.jpg",
        "thumbnail_url": "http://minio/thumbnails/test.jpg",
    }
    with (
        patch("app.routes.capture.vision_svc.extract_from_image_bytes",
              return_value=capture_result),
        patch("app.routes.capture.storage_svc.upload_image",
              return_value=uploaded) as mock_upload,
        patch("app.routes.capture.storage_svc.tag_objects_with_recipe_id"),
    ):
        client.post(
            "/capture/image",
            files={"file": ("test.jpg", b"\xff\xd8\xff\xe0", "image/jpeg")},
        )

    meta = mock_upload.call_args.kwargs["metadata"]
    assert meta["source-type"] == "image"
    assert meta["recipe-title"] == "Mocked Recipe"
    assert meta["app-name"] == "recipe-app"
    assert "captured-at" in meta


def test_capture_image_recipe_id_tagged_after_commit(client, capture_result):
    """tag_objects_with_recipe_id is called with the committed recipe's DB ID."""
    uploaded = {
        "image_key": "originals/xyz.jpg",
        "image_url": "http://minio/originals/xyz.jpg",
        "thumbnail_key": "thumbnails/xyz.jpg",
        "thumbnail_url": "http://minio/thumbnails/xyz.jpg",
    }
    with (
        patch("app.routes.capture.vision_svc.extract_from_image_bytes",
              return_value=capture_result),
        patch("app.routes.capture.storage_svc.upload_image", return_value=uploaded),
        patch("app.routes.capture.storage_svc.tag_objects_with_recipe_id") as mock_tag,
    ):
        response = client.post(
            "/capture/image",
            files={"file": ("test.jpg", b"\xff\xd8\xff\xe0", "image/jpeg")},
        )

    recipe_id = response.json()["id"]
    assert recipe_id > 0
    mock_tag.assert_called_once_with("originals/xyz.jpg", "thumbnails/xyz.jpg", recipe_id)
