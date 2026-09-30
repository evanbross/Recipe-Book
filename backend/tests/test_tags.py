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
