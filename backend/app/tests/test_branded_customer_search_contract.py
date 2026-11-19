"""Public customer-search response and literal-search contract."""
from uuid import uuid4

from app.core.security import create_access_token
from app.schemas import Customer, Role, User
from app.tests.conftest import TestSessionLocal


def test_customer_search_preserves_literal_wildcards_and_wire(client, auth_headers):
    marker = uuid4().hex[:10]
    with TestSessionLocal() as db:
        rows = [Customer(name=f"{marker} 100% A"), Customer(name=f"{marker} 100X A"),
                Customer(name=f"{marker} under_score"), Customer(name=f"{marker} underXscore")]
        db.add_all(rows)
        db.commit()
        ids = [row.id for row in rows]
    route = "/api/planning/branded-order-customers"
    percent = client.get(route, headers=auth_headers, params={"q": f" {marker} 100% "})
    assert percent.status_code == 200
    assert percent.json() == [{"id": ids[0], "name": f"{marker} 100% A"}]
    underscore = client.get(route, headers=auth_headers, params={"q": f"{marker} under_score"})
    assert underscore.status_code == 200
    assert underscore.json() == [{"id": ids[2], "name": f"{marker} under_score"}]
    assert client.get(route, headers=auth_headers, params={"q": marker + "-missing"}).json() == []


def test_customer_search_openapi_and_access(client):
    path = "/api/planning/branded-order-customers"
    assert client.get(path).status_code in (401, 403)
    schema = client.get("/openapi.json").json()["paths"][path]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema["type"] == "array"
    assert schema["items"]["$ref"] == "#/components/schemas/BrandedOrderCustomerOut"


def test_customer_search_real_permission_and_backslash_literal(client):
    marker = uuid4().hex[:10]
    with TestSessionLocal() as db:
        allowed_role = Role(name=f"planning-search-{marker}", permissions=["planning.production"])
        denied_role = Role(name=f"no-planning-search-{marker}", permissions=[])
        db.add_all([allowed_role, denied_role])
        db.flush()
        allowed = User(name="Search allowed", email=f"allowed-{marker}@example.invalid",
                       password_hash="unused", role_id=allowed_role.id, factory_code="MIL", is_active=True)
        denied = User(name="Search denied", email=f"denied-{marker}@example.invalid",
                      password_hash="unused", role_id=denied_role.id, factory_code="MIL", is_active=True)
        rows = [Customer(name=f"{marker} fabric\\roll"), Customer(name=f"{marker} fabricXroll")]
        db.add_all([allowed, denied, *rows])
        db.commit()
        allowed_id, denied_id, matching_id = allowed.id, denied.id, rows[0].id
    path = "/api/planning/branded-order-customers"
    denied_headers = {"Authorization": f"Bearer {create_access_token(denied_id)}"}
    allowed_headers = {"Authorization": f"Bearer {create_access_token(allowed_id)}"}
    assert client.get(path, headers=denied_headers, params={"q": marker}).status_code == 403
    response = client.get(path, headers=allowed_headers, params={"q": f" {marker} fabric\\roll "})
    assert response.status_code == 200
    assert response.json() == [{"id": matching_id, "name": f"{marker} fabric\\roll"}]


def test_customer_search_limit_and_id_tiebreak_for_equal_names(client, auth_headers):
    marker = uuid4().hex[:10]
    name = f"{marker} same-name"
    with TestSessionLocal() as db:
        rows = [Customer(name=name) for _ in range(51)]
        db.add_all(rows)
        db.commit()
        ids = sorted(row.id for row in rows)
    response = client.get("/api/planning/branded-order-customers", headers=auth_headers,
                          params={"q": marker})
    assert response.status_code == 200
    assert response.json() == [{"id": customer_id, "name": name} for customer_id in ids[:50]]
