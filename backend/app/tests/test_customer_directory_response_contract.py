from uuid import uuid4


def test_customer_directory_list_page_and_clamps(client, auth_headers):
    marker = f"Directory-{uuid4().hex[:10]}"
    created = []
    for suffix in ("one", "two"):
        response = client.post("/api/customers", headers=auth_headers, json={"name": f"{marker}-{suffix}"})
        assert response.status_code == 201
        created.append(response.json())

    response = client.get("/api/customers", headers=auth_headers, params={"q": marker})
    assert response.status_code == 200
    assert response.json() == list(reversed(created))
    page = client.get(
        "/api/customers", headers=auth_headers,
        params={"q": marker, "include_total": "true", "page": 0, "page_size": 0},
    )
    assert page.status_code == 200
    assert page.json() == {"rows": [created[-1]], "total": 2, "page": 1, "page_size": 1}
    empty = client.get(
        "/api/customers", headers=auth_headers,
        params={"q": f"{marker}-missing", "include_total": "true", "page_size": 501},
    )
    assert empty.status_code == 200
    assert empty.json() == {"rows": [], "total": 0, "page": 1, "page_size": 500}


def test_customer_directory_requires_auth_and_exposes_both_shapes(client):
    assert client.get("/api/customers").status_code == 401
    schema = client.get("/openapi.json").json()
    response = schema["paths"]["/api/customers"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert len(response["anyOf"]) == 2
    assert schema["components"]["schemas"]["PartyPageOut"]["required"] == ["rows", "total", "page", "page_size"]
