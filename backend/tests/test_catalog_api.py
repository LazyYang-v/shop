def test_catalog_lists_products_from_database(client):
    response = client.get("/api/products", params={"category": "女装", "q": "春日轻盈针织开衫"})

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "id": "00000000-0000-0000-0000-000000000001",
                "name": "春日轻盈针织开衫",
                "category": "女装",
                "description": "柔软亲肤的日常针织开衫，适合春秋叠穿。",
                "image_url": "/images/cardigan.svg",
                "price": "129.00",
                "stock": 24,
            }
        ],
        "total": 1,
        "page": 1,
        "page_size": 20,
    }


def test_catalog_searches_filters_sorts_and_paginates_from_server(client):
    response = client.get("/api/products", params={"q": "针织", "category": "女装", "sort": "price_desc", "page": 1, "page_size": 10})
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["id"] == "00000000-0000-0000-0000-000000000001"


def test_catalog_rejects_unknown_sort_order(client):
    assert client.get("/api/products", params={"sort": "random"}).status_code == 422
