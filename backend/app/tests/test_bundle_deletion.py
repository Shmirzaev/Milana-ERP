from uuid import uuid4


PASSWORD = "CuttingDelete!2026"


def _role_id(client, headers, name: str) -> int:
    response = client.get("/api/roles", headers=headers)
    assert response.status_code == 200, response.text
    return int(next(row["id"] for row in response.json() if row["name"] == name))


def _department_id(client, headers, code: str) -> int:
    response = client.get("/api/departments", headers=headers)
    assert response.status_code == 200, response.text
    return int(next(row["id"] for row in response.json() if row["code"] == code))


def _create_cutting_user(client, admin_headers, suffix: str) -> tuple[int, dict[str, str]]:
    email = f"cutting.bundle.delete.{suffix}.{uuid4().hex[:8]}@example.com"
    response = client.post(
        "/api/users",
        json={
            "name": f"Cutting {suffix}",
            "email": email,
            "password": PASSWORD,
            "role_id": _role_id(client, admin_headers, "Cutting"),
            "department_id": _department_id(client, admin_headers, "CUT"),
            "is_active": True,
        },
        headers=admin_headers,
    )
    assert response.status_code == 201, response.text
    user_id = int(response.json()["id"])
    login = client.post("/api/auth/token", data={"username": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return user_id, {"Authorization": f"Bearer {login.json()['access_token']}"}


def _production_order(client, headers) -> int:
    response = client.post(
        "/api/planning/create-branded-production",
        json={
            "production_type": "branded_stock",
            "model_id": 1,
            "planned_quantity": 20,
            "items": [{"model_id": 1, "color": "white", "size": "M", "planned_quantity": 20}],
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def _bundle(client, headers, production_order_id: int) -> dict:
    response = client.post(
        "/api/bundles",
        json={
            "production_order_id": production_order_id,
            "model_id": 1,
            "color": "white",
            "size": "M",
            "quantity": 20,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_cutting_user_can_delete_only_own_unprocessed_bundle(client, auth_headers):
    owner_id, owner_headers = _create_cutting_user(client, auth_headers, "Owner")
    _, other_headers = _create_cutting_user(client, auth_headers, "Other")
    production_order_id = _production_order(client, auth_headers)

    bundle = _bundle(client, owner_headers, production_order_id)
    assert int(bundle["created_by"]) == owner_id

    blocked = client.delete(f"/api/bundles/{bundle['id']}", headers=other_headers)
    assert blocked.status_code == 403, blocked.text

    deleted = client.delete(f"/api/bundles/{bundle['id']}", headers=owner_headers)
    assert deleted.status_code == 204, deleted.text
    missing = client.get(f"/api/bundles/{bundle['id']}", headers=auth_headers)
    assert missing.status_code == 404, missing.text


def test_cutting_user_cannot_delete_bundle_after_it_moves_stage(client, auth_headers):
    _, owner_headers = _create_cutting_user(client, auth_headers, "Processed")
    production_order_id = _production_order(client, auth_headers)
    bundle = _bundle(client, owner_headers, production_order_id)

    moved = client.post(f"/api/bundles/{bundle['id']}/send-sewing", headers=owner_headers)
    assert moved.status_code == 200, moved.text
    blocked = client.delete(f"/api/bundles/{bundle['id']}", headers=owner_headers)
    assert blocked.status_code == 409, blocked.text
