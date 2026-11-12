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


# ai: claude-opus-5-5 | 2026-11-11
# The route filters on `tag_ids` (comma-separated integer IDs) — not slugs.
# An unrecognised query param is silently ignored by FastAPI, so the old
# `?tags=<slug>` tests never applied any filter at all.
def test_search_tag_filter_single(client, make_recipe, make_tag):
    italian = make_tag(name="Italian", slug="italian")
    tagged = make_recipe(title="Tagged", tags=[italian])
    make_recipe(title="Untagged")

    response = client.get(f"/search?tag_ids={italian.id}")
    payload = response.json()

    assert response.status_code == 200
    assert payload["total"] == 1
    assert len(payload["results"]) == 1
    assert payload["results"][0]["id"] == tagged.id


# ai: claude-opus-5-5 | 2026-11-11
def test_search_tag_filter_and_logic(client, make_recipe, make_tag):
    italian = make_tag(name="Italian", slug="italian")
    vegetarian = make_tag(name="Vegetarian", slug="vegetarian")

    recipe_a = make_recipe(title="A", tags=[italian, vegetarian])
    make_recipe(title="B", tags=[italian])
    make_recipe(title="C", tags=[vegetarian])

    response = client.get(f"/search?tag_ids={italian.id},{vegetarian.id}")
    payload = response.json()

    assert response.status_code == 200
    assert payload["total"] == 1
    assert len(payload["results"]) == 1
    assert payload["results"][0]["id"] == recipe_a.id


# ai: claude-opus-5-5 | 2026-11-11
def test_search_tag_filter_or_logic(client, make_recipe, make_tag):
    italian = make_tag(name="Italian", slug="italian")
    vegetarian = make_tag(name="Vegetarian", slug="vegetarian")
    mexican = make_tag(name="Mexican", slug="mexican")

    recipe_a = make_recipe(title="A", tags=[italian, vegetarian])
    recipe_b = make_recipe(title="B", tags=[italian])
    recipe_c = make_recipe(title="C", tags=[vegetarian])
    make_recipe(title="D", tags=[mexican])

    response = client.get(f"/search?tag_ids={italian.id},{vegetarian.id}&tag_mode=or")
    payload = response.json()

    assert response.status_code == 200
    assert payload["total"] == 3
    assert {r["id"] for r in payload["results"]} == {recipe_a.id, recipe_b.id, recipe_c.id}


# ai: claude-opus-5-5 | 2026-11-11
def test_search_tag_unknown_id_matches_nothing(client, make_recipe):
    """An unknown tag ID is still applied as a filter, so nothing can match it."""
    make_recipe(title="Recipe 1")
    make_recipe(title="Recipe 2")

    response = client.get("/search?tag_ids=99999")
    payload = response.json()

    assert response.status_code == 200
    assert payload["total"] == 0
    assert payload["results"] == []


# ai: claude-opus-5-5 | 2026-11-11
def test_search_tag_ids_non_numeric_ignored(client, make_recipe):
    """Non-numeric entries in tag_ids are dropped; with none left, no tag filter applies."""
    make_recipe(title="Recipe 1")
    make_recipe(title="Recipe 2")

    response = client.get("/search?tag_ids=italian,abc")
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

    response = client.get(f"/search?q=ramen&tag_ids={asian.id}")  # ai: claude-opus-5-5 | 2026-11-11
    payload = response.json()

    assert response.status_code == 200
    assert payload["total"] == 1
    assert len(payload["results"]) == 1
    assert payload["results"][0]["id"] == tagged.id
