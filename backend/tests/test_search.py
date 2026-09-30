def test_search_empty_query(client, make_recipe):
    make_recipe(title="Recipe A")
    make_recipe(title="Recipe B")

    response = client.get("/search?q=")
    payload = response.json()

    assert response.status_code == 200
    assert payload["total"] == 2
    assert len(payload["results"]) == 2


def test_search_by_title_ilike(client, make_recipe):
    make_recipe(title="Spicy Thai Noodles")

    response = client.get("/search?q=thai")
    payload = response.json()

    assert response.status_code == 200
    assert payload["total"] == 1
    assert len(payload["results"]) == 1
    assert payload["results"][0]["title"] == "Spicy Thai Noodles"


def test_search_no_match(client, make_recipe):
    make_recipe(title="Chocolate Cake")

    response = client.get("/search?q=pizza")
    payload = response.json()

    assert response.status_code == 200
    assert payload["total"] == 0
    assert payload["results"] == []


def test_search_tag_filter_single(client, make_recipe, make_tag):
    italian = make_tag(name="Italian", slug="italian")
    tagged = make_recipe(title="Tagged", tags=[italian])
    make_recipe(title="Untagged")

    response = client.get("/search?tags=italian")
    payload = response.json()

    assert response.status_code == 200
    assert payload["total"] == 1
    assert len(payload["results"]) == 1
    assert payload["results"][0]["id"] == tagged.id


def test_search_tag_filter_and_logic(client, make_recipe, make_tag):
    italian = make_tag(name="Italian", slug="italian")
    vegetarian = make_tag(name="Vegetarian", slug="vegetarian")

    recipe_a = make_recipe(title="A", tags=[italian, vegetarian])
    make_recipe(title="B", tags=[italian])
    make_recipe(title="C", tags=[vegetarian])

    response = client.get("/search?tags=italian,vegetarian")
    payload = response.json()

    assert response.status_code == 200
    assert payload["total"] == 1
    assert len(payload["results"]) == 1
    assert payload["results"][0]["id"] == recipe_a.id


def test_search_tag_unknown_slug_ignored(client, make_recipe):
    make_recipe(title="Recipe 1")
    make_recipe(title="Recipe 2")

    response = client.get("/search?tags=nonexistent")
    payload = response.json()

    assert response.status_code == 200
    assert payload["total"] == 2
    assert len(payload["results"]) == 2


def test_search_pagination(client, make_recipe):
    for i in range(5):
        make_recipe(title=f"Soup Recipe {i}")

    page_1 = client.get("/search?q=soup&page=1&page_size=2")
    page_3 = client.get("/search?q=soup&page=3&page_size=2")

    payload_1 = page_1.json()
    payload_3 = page_3.json()

    assert page_1.status_code == 200
    assert payload_1["total"] == 5
    assert len(payload_1["results"]) == 2

    assert page_3.status_code == 200
    assert payload_3["total"] == 5
    assert len(payload_3["results"]) == 1


def test_search_combined_text_and_tag(client, make_recipe, make_tag):
    asian = make_tag(name="Asian", slug="asian")
    tagged = make_recipe(title="Ramen", tags=[asian])
    make_recipe(title="Ramen")

    response = client.get("/search?q=ramen&tags=asian")
    payload = response.json()

    assert response.status_code == 200
    assert payload["total"] == 1
    assert len(payload["results"]) == 1
    assert payload["results"][0]["id"] == tagged.id
