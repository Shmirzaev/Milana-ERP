def test_models_list(client, auth_headers):
    r = client.get("/api/models", headers=auth_headers)
    assert r.status_code == 200
    items = r.json()
    assert any(m["code"] == "T-SHIRT-001" for m in items)


def test_create_model_and_approve(client, auth_headers):
    r = client.post("/api/models", json={
        "code": "HOODIE-001", "name": "Pullover Hoodie", "category": "hoodie", "status": "draft",
    }, headers=auth_headers)
    assert r.status_code == 201, r.text
    mid = r.json()["id"]
    r2 = client.post(f"/api/models/{mid}/approve", headers=auth_headers)
    assert r2.status_code == 200
    assert r2.json()["status"] == "approved"


def test_brands_collections(client, auth_headers):
    r = client.get("/api/brands", headers=auth_headers)
    assert r.status_code == 200
    assert len(r.json()) >= 1
    r2 = client.get("/api/collections", headers=auth_headers)
    assert r2.status_code == 200
