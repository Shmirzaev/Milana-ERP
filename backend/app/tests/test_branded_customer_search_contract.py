"""Public customer-search response and literal-search contract."""
from uuid import uuid4

from app.schemas import Customer
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
