from unittest.mock import patch

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


def test_capture_url_success(client, capture_result):
    with patch("app.routes.capture.scraper_svc.fetch_page_text", return_value="some page text"), patch(
        "app.routes.capture.vision_svc.extract_from_text", return_value=capture_result
    ):
        response = client.post("/capture/url", json={"url": "https://example.com/recipe"})

    payload = response.json()
    assert response.status_code == 200
    assert payload["title"] == "Mocked Recipe"
    assert payload["source_type"] == "web"
    assert payload["source_url"] == "https://example.com/recipe"


def test_capture_url_scraper_failure(client):
    with patch("app.routes.capture.scraper_svc.fetch_page_text", side_effect=Exception("timeout")):
        response = client.post("/capture/url", json={"url": "https://example.com/recipe"})

    assert response.status_code == 422
    assert "Failed to fetch URL" in response.json()["detail"]


def test_capture_url_vision_failure(client):
    with patch("app.routes.capture.scraper_svc.fetch_page_text", return_value="text"), patch(
        "app.routes.capture.vision_svc.extract_from_text", side_effect=Exception("Claude error")
    ):
        response = client.post("/capture/url", json={"url": "https://example.com/recipe"})

    assert response.status_code == 422
    assert "Claude extraction failed" in response.json()["detail"]


def test_capture_url_with_tags(client, make_tag, capture_result):
    tag = make_tag(name="Asian", slug="asian")

    with patch("app.routes.capture.scraper_svc.fetch_page_text", return_value="some page text"), patch(
        "app.routes.capture.vision_svc.extract_from_text", return_value=capture_result
    ):
        response = client.post(
            "/capture/url",
            json={"url": "https://example.com/recipe", "tag_ids": [tag.id]},
        )

    payload = response.json()
    assert response.status_code == 200
    assert len(payload["tags"]) == 1
    assert payload["tags"][0]["id"] == tag.id


def test_capture_image_success(client, capture_result):
    uploaded = {
        "image_key": "originals/test.jpg",
        "image_url": "https://cdn.example.com/originals/test.jpg",
        "thumbnail_key": "thumbnails/test.jpg",
        "thumbnail_url": "https://cdn.example.com/thumbnails/test.jpg",
    }

    with patch(
        "app.routes.capture.vision_svc.extract_from_image_bytes", return_value=capture_result
    ), patch("app.routes.capture.storage_svc.upload_image", return_value=uploaded):
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
    with patch(
        "app.routes.capture.vision_svc.extract_from_image_bytes", return_value=capture_result
    ), patch("app.routes.capture.storage_svc.upload_image", side_effect=Exception("R2 error")):
        response = client.post(
            "/capture/image",
            files={"file": ("test.jpg", b"\xff\xd8\xff\xe0", "image/jpeg")},
        )

    assert response.status_code == 500
    assert "Storage upload failed" in response.json()["detail"]
