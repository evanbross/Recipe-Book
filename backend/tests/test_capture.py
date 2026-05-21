from unittest.mock import patch

import httpx
import pytest
from app.schemas import CaptureResult


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


# ── URL capture — existing tests (fetch_page_text → fetch_page) ───────────────

def test_capture_url_success(client, capture_result):
    with (
        patch("app.routes.capture.scraper_svc.fetch_page",
              return_value=("some page text", None, "https://example.com/recipe", None)),
        patch("app.routes.capture.vision_svc.extract_from_text", return_value=capture_result),
    ):
        response = client.post("/capture/url", json={"url": "https://example.com/recipe"})

    payload = response.json()
    assert response.status_code == 200
    assert payload["title"] == "Mocked Recipe"
    assert payload["source_type"] == "web"
    assert payload["source_url"] == "https://example.com/recipe"


def test_capture_url_scraper_failure(client):
    with patch("app.routes.capture.scraper_svc.fetch_page",
               side_effect=Exception("timeout")):
        response = client.post("/capture/url", json={"url": "https://example.com/recipe"})

    assert response.status_code == 422
    assert "Failed to fetch URL" in response.json()["detail"]


def test_capture_url_vision_failure(client):
    with (
        patch("app.routes.capture.scraper_svc.fetch_page", return_value=("text", None, "https://example.com/recipe", None)),
        patch("app.routes.capture.vision_svc.extract_from_text",
              side_effect=Exception("Claude error")),
    ):
        response = client.post("/capture/url", json={"url": "https://example.com/recipe"})

    assert response.status_code == 422
    assert "Claude extraction failed" in response.json()["detail"]


def test_capture_url_with_tags(client, make_tag, capture_result):
    tag = make_tag(name="Asian", slug="asian")

    with (
        patch("app.routes.capture.scraper_svc.fetch_page",
              return_value=("some page text", None, "https://example.com/recipe", None)),
        patch("app.routes.capture.vision_svc.extract_from_text", return_value=capture_result),
    ):
        response = client.post(
            "/capture/url",
            json={"url": "https://example.com/recipe", "tag_ids": [tag.id]},
        )

    payload = response.json()
    assert response.status_code == 200
    assert len(payload["tags"]) == 1
    assert payload["tags"][0]["id"] == tag.id


# ── URL capture — OG image stored in MinIO ────────────────────────────────────

def test_capture_url_og_image_stored_in_minio(client, capture_result):
    """OG image is downloaded and stored; recipe gets MinIO keys, not external URL."""
    uploaded = {
        "image_key": "originals/abc.jpg",
        "image_url": "http://minio/recipe-images/originals/abc.jpg",
        "thumbnail_key": "thumbnails/abc.jpg",
        "thumbnail_url": "http://minio/recipe-images/thumbnails/abc.jpg",
    }
    with (
        patch("app.routes.capture.scraper_svc.fetch_page",
              return_value=("page text", "https://example.com/image.jpg", "https://example.com/recipe", None)),
        patch("app.routes.capture.vision_svc.extract_from_text", return_value=capture_result),
        patch("app.routes.capture.scraper_svc.fetch_page_image",
              return_value=(b"\xff\xd8\xff\xe0", "image/jpeg")),
        patch("app.routes.capture.storage_svc.upload_image", return_value=uploaded),
        patch("app.routes.capture.storage_svc.tag_objects_with_recipe_id"),
    ):
        response = client.post("/capture/url", json={"url": "https://example.com/recipe"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["image_url"] == "http://minio/recipe-images/originals/abc.jpg"
    assert payload["thumbnail_url"] == "http://minio/recipe-images/thumbnails/abc.jpg"


def test_capture_url_og_image_download_fails_uses_external_url(client, capture_result):
    """If OG image download fails, recipe falls back to external URL."""
    with (
        patch("app.routes.capture.scraper_svc.fetch_page",
              return_value=("page text", "https://example.com/image.jpg", "https://example.com/recipe", None)),
        patch("app.routes.capture.vision_svc.extract_from_text", return_value=capture_result),
        patch("app.routes.capture.scraper_svc.fetch_page_image",
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
        patch("app.routes.capture.scraper_svc.fetch_page",
              return_value=("page text", "https://example.com/image.svg", "https://example.com/recipe", None)),
        patch("app.routes.capture.vision_svc.extract_from_text", return_value=capture_result),
        patch("app.routes.capture.scraper_svc.fetch_page_image",
              return_value=(b"<svg/>", "image/svg+xml")),
    ):
        response = client.post("/capture/url", json={"url": "https://example.com/recipe"})

    assert response.status_code == 200
    assert response.json()["image_url"] == "https://example.com/image.svg"
    assert response.json()["thumbnail_url"] is None


# ── Image capture — existing tests ────────────────────────────────────────────

def test_capture_image_success(client, capture_result):
    uploaded = {
        "image_key": "originals/test.jpg",
        "image_url": "https://cdn.example.com/originals/test.jpg",
        "thumbnail_key": "thumbnails/test.jpg",
        "thumbnail_url": "https://cdn.example.com/thumbnails/test.jpg",
    }

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
    assert payload["image_url"] == "https://cdn.example.com/originals/test.jpg"


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
