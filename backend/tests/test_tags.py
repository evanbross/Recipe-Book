from unittest.mock import patch

import pytest


def test_list_categories_empty(client):
    response = client.get("/tags/categories")

    assert response.status_code == 200
    assert response.json() == []


def test_create_category(client):
    response = client.post("/tags/categories", json={"name": "Cuisine", "slug": "cuisine"})
    payload = response.json()

    assert response.status_code == 201
    assert payload["id"] > 0
    assert payload["name"] == "Cuisine"
    assert payload["slug"] == "cuisine"


def test_list_categories(client, make_category):
    make_category(name="Diet", slug="diet")
    make_category(name="Cuisine", slug="cuisine")

    response = client.get("/tags/categories")
    payload = response.json()

    assert response.status_code == 200
    assert len(payload) == 2
    assert [item["name"] for item in payload] == ["Cuisine", "Diet"]


def test_create_tag_no_category(client):
    response = client.post("/tags", json={"name": "Vegan", "slug": "vegan"})
    payload = response.json()

    assert response.status_code == 201
    assert payload["name"] == "Vegan"
    assert payload["slug"] == "vegan"
    assert payload["category"] is None


def test_create_tag_with_category(client, make_category):
    category = make_category(name="Cuisine", slug="cuisine")

    response = client.post(
        "/tags",
        json={"name": "Italian", "slug": "italian", "category_id": category.id},
    )
    payload = response.json()

    assert response.status_code == 201
    assert payload["category"]["id"] == category.id


def test_list_tags(client, make_category, make_tag):
    cat_a = make_category(name="Cuisine", slug="cuisine")
    cat_b = make_category(name="Diet", slug="diet")
    make_tag(name="Italian", slug="italian", category_id=cat_a.id)
    make_tag(name="French", slug="french", category_id=cat_a.id)
    make_tag(name="Vegan", slug="vegan", category_id=cat_b.id)

    response = client.get("/tags")

    assert response.status_code == 200
    assert len(response.json()) == 3


def test_list_tags_filtered_by_category(client, make_category, make_tag):
    cat_a = make_category(name="Cuisine", slug="cuisine")
    cat_b = make_category(name="Diet", slug="diet")
    make_tag(name="Italian", slug="italian", category_id=cat_a.id)
    make_tag(name="French", slug="french", category_id=cat_a.id)
    make_tag(name="Vegan", slug="vegan", category_id=cat_b.id)

    response = client.get(f"/tags?category_id={cat_a.id}")

    assert response.status_code == 200
    assert len(response.json()) == 2


def test_delete_tag(client, make_tag):
    tag = make_tag(name="Delete Me", slug="delete-me")

    delete_response = client.delete(f"/tags/{tag.id}")
    list_response = client.get("/tags")
    slugs = [item["slug"] for item in list_response.json()]

    assert delete_response.status_code == 204
    assert "delete-me" not in slugs


def test_delete_tag_not_found(client):
    response = client.delete("/tags/99999")

    assert response.status_code == 404


# ai: claude-opus-5-5 | 2026-11-14
# ── Duplicate slugs (uq_tags_category_id_slug) ───────────────────────────────

def test_create_tag_duplicate_slug_in_category_conflicts(client, make_category, make_tag):
    category = make_category(name="Cuisine", slug="cuisine")
    make_tag(name="Italian", slug="italian", category_id=category.id)

    response = client.post(
        "/tags", json={"name": "Italian", "slug": "italian", "category_id": category.id},
    )

    assert response.status_code == 409


def test_create_tag_duplicate_uncategorized_slug_conflicts(client, make_tag):
    make_tag(name="Vegan", slug="vegan")

    response = client.post("/tags", json={"name": "Vegan", "slug": "vegan"})

    assert response.status_code == 409


def test_create_tag_same_slug_in_other_category_is_allowed(client, make_category, make_tag):
    cuisine = make_category(name="Cuisine", slug="cuisine")
    diet = make_category(name="Diet", slug="diet")
    make_tag(name="Keto", slug="keto", category_id=cuisine.id)

    response = client.post("/tags", json={"name": "Keto", "slug": "keto", "category_id": diet.id})

    assert response.status_code == 201


def test_create_tag_unknown_category_not_found(client):
    response = client.post("/tags", json={"name": "X", "slug": "x", "category_id": 99999})

    assert response.status_code == 404


# ai: claude-opus-5-5 | 2026-11-14
# ── /tags/suggest (real tagger, Claude call patched) ─────────────────────────

def test_suggest_tags_returns_parsed_reply_and_lists_existing_tags(client, make_category, make_tag):
    cuisine = make_category(name="Cuisine", slug="cuisine")
    italian = make_tag(name="Italian", slug="italian", category_id=cuisine.id)
    quick = make_tag(name="Quick", slug="quick")
    reply = (
        '```json\n{"existing_tag_ids": [%d], '
        '"new_tags": [{"name": "Pasta", "category_name": "Course"}]}\n```' % italian.id
    )

    with patch("app.services.tagger.request_text", return_value=reply) as request_text:
        response = client.post(
            "/tags/suggest",
            json={"title": "Cacio e Pepe", "description": "Roman classic", "ingredients": "pecorino"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "existing_tag_ids": [italian.id],
        "new_tags": [{"name": "Pasta", "category_name": "Course"}],
    }
    prompt = request_text.call_args.args[0]
    assert f"Cuisine: Italian (id:{italian.id})" in prompt
    assert f"Uncategorized: Quick (id:{quick.id})" in prompt
    assert "Title: Cacio e Pepe" in prompt
    assert "Ingredients:\npecorino" in prompt


def test_suggest_tags_with_no_tags_says_none_yet(client):
    reply = '{"existing_tag_ids": [], "new_tags": []}'

    with patch("app.services.tagger.request_text", return_value=reply) as request_text:
        response = client.post("/tags/suggest", json={"title": "Toast"})

    assert response.status_code == 200
    assert "(none yet)" in request_text.call_args.args[0]


@pytest.mark.parametrize("failure", [
    {"return_value": "not json at all"},
    {"return_value": '{"existing_tag_ids": ["abc"], "new_tags": []}'},
    {"side_effect": ValueError("boom")},
])
def test_suggest_tags_failure_returns_empty_result(client, failure):
    with patch("app.services.tagger.request_text", **failure):
        response = client.post("/tags/suggest", json={"title": "Toast"})

    assert response.status_code == 200
    assert response.json() == {"existing_tag_ids": [], "new_tags": []}
