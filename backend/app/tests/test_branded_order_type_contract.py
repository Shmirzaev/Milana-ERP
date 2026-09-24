import pytest

from app.models import AuditLog, BrandedPlanningOrder
from app.tests.conftest import TestSessionLocal


@pytest.mark.parametrize("ordered_for_type", ["", "unknown", "milana-like", " unknown ", 7])
def test_unsupported_branded_order_type_returns_422_and_writes_nothing(
    client,
    auth_headers,
    ordered_for_type,
):
    with TestSessionLocal() as db:
        order_count_before = db.query(BrandedPlanningOrder.id).count()
        audit_count_before = db.query(AuditLog.id).count()

    response = client.post(
        "/api/planning/branded-orders",
        headers=auth_headers,
        json={"ordered_for_type": ordered_for_type},
    )

    assert response.status_code == 422
    assert any(error["loc"][-1] == "ordered_for_type" for error in response.json()["detail"])
    with TestSessionLocal() as db:
        assert db.query(BrandedPlanningOrder.id).count() == order_count_before
        assert db.query(AuditLog.id).count() == audit_count_before


def test_branded_order_type_guard_preserves_authentication_precedence(client):
    response = client.post(
        "/api/planning/branded-orders",
        json={"ordered_for_type": "unknown"},
    )

    assert response.status_code == 401


@pytest.mark.parametrize(
    ("submitted_type", "normalized_type", "ordered_for_name"),
    [("  BESTTEX  ", "besttex", "Besttex"), ("Eco_Cotton", "eco_cotton", "Eco Cotton")],
)
def test_branded_order_type_guard_keeps_normalized_stable_code(
    client,
    auth_headers,
    submitted_type,
    normalized_type,
    ordered_for_name,
):
    response = client.post(
        "/api/planning/branded-orders",
        headers=auth_headers,
        json={"ordered_for_type": submitted_type},
    )

    assert response.status_code == 201, response.text
    assert response.json()["ordered_for_type"] == normalized_type
    assert response.json()["ordered_for_name"] == ordered_for_name


def test_customer_order_type_is_validated_before_customer_reference_lookup(client, auth_headers):
    with TestSessionLocal() as db:
        order_count_before = db.query(BrandedPlanningOrder.id).count()
        audit_count_before = db.query(AuditLog.id).count()

    response = client.post(
        "/api/planning/branded-orders",
        headers=auth_headers,
        json={"ordered_for_type": " CUSTOMER "},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Customer not found"
    with TestSessionLocal() as db:
        assert db.query(BrandedPlanningOrder.id).count() == order_count_before
        assert db.query(AuditLog.id).count() == audit_count_before


def test_branded_order_type_openapi_advertises_stable_codes(client):
    schema = client.get("/openapi.json").json()
    property_schema = schema["components"]["schemas"]["BrandedPlanningOrderIn"]["properties"]["ordered_for_type"]

    assert property_schema["enum"] == ["milana", "eco_cotton", "besttex", "customer"]
