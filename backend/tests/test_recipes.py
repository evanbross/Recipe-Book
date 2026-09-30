from unittest.mock import patch


def test_list_recipes_empty(client):
    response = client.get("/recipes")

    assert response.status_code == 200
    assert response.json() == []


def test_list_recipes_returns_items(client, make_recipe):
    make_recipe(title="Recipe 1")
    make_recipe(title="Recipe 2")
    make_recipe(title="Recipe 3")

    response = client.get("/recipes")
    payload = response.json()

    assert response.status_code == 200
    assert len(payload) == 3
    for item in payload:
        assert "id" in item
        assert "title" in item
        assert "source_type" in item
        assert "tags" in item
        assert "created_at" in item
        assert "ingredients" not in item
        assert "instructions" not in item


def test_list_recipes_pagination(client, make_recipe):
    for i in range(5):
        make_recipe(title=f"Recipe {i}")

    response = client.get("/recipes?skip=2&limit=2")

    assert response.status_code == 200
    assert len(response.json()) == 2


def test_get_recipe_success(client, make_recipe):
    recipe = make_recipe(
        title="Full Recipe",
        ingredients="1 cup flour",
        instructions="Mix and bake",
    )

    response = client.get(f"/recipes/{recipe.id}")
    payload = response.json()

    assert response.status_code == 200
    assert payload["id"] == recipe.id
    assert payload["title"] == "Full Recipe"
    assert payload["ingredients"] == "1 cup flour"
    assert payload["instructions"] == "Mix and bake"


def test_get_recipe_not_found(client):
    response = client.get("/recipes/99999")

    assert response.status_code == 404


def test_create_recipe_minimal(client):
    response = client.post("/recipes", json={"title": "My Recipe", "source_type": "manual"})
    payload = response.json()

    assert response.status_code == 201
    assert payload["id"] > 0
    assert payload["title"] == "My Recipe"
    assert payload["tags"] == []


def test_create_recipe_with_tags(client, make_tag):
    tag = make_tag(name="Italian", slug="italian")

    response = client.post(
        "/recipes",
        json={"title": "Tagged Recipe", "source_type": "manual", "tag_ids": [tag.id]},
    )
    payload = response.json()

    assert response.status_code == 201
    assert len(payload["tags"]) == 1
    assert payload["tags"][0]["id"] == tag.id
    assert payload["tags"][0]["slug"] == "italian"


def test_update_recipe_fields(client, make_recipe):
    recipe = make_recipe(title="Original")

    response = client.patch(f"/recipes/{recipe.id}", json={"title": "Updated"})

    assert response.status_code == 200
    assert response.json()["title"] == "Updated"


def test_update_recipe_swap_tags(client, make_recipe, make_tag):
    tag_a = make_tag(name="Italian", slug="italian")
    tag_b = make_tag(name="Vegetarian", slug="vegetarian")
    recipe = make_recipe(title="Swap Tags", tags=[tag_a])

    response = client.patch(f"/recipes/{recipe.id}", json={"tag_ids": [tag_b.id]})
    payload = response.json()

    assert response.status_code == 200
    assert len(payload["tags"]) == 1
    assert payload["tags"][0]["id"] == tag_b.id


def test_update_recipe_not_found(client):
    response = client.patch("/recipes/99999", json={"title": "x"})

    assert response.status_code == 404


def test_delete_recipe_no_image(client, make_recipe):
    recipe = make_recipe()

    delete_response = client.delete(f"/recipes/{recipe.id}")
    get_response = client.get(f"/recipes/{recipe.id}")

    assert delete_response.status_code == 204
    assert get_response.status_code == 404


def test_delete_recipe_with_image(client, make_recipe):
    recipe = make_recipe(image_key="originals/abc.jpg", thumbnail_key="thumbnails/abc.jpg")

    with patch("app.services.storage.delete_image") as mock_delete_image:
        response = client.delete(f"/recipes/{recipe.id}")

    assert response.status_code == 204
    mock_delete_image.assert_called_once_with("originals/abc.jpg", "thumbnails/abc.jpg")


def test_delete_recipe_not_found(client):
    response = client.delete("/recipes/99999")

    assert response.status_code == 404
