import pytest

from app.models import AuditLog, BrandedPlanningOrder
from app.tests.conftest import TestSessionLocal


@pytest.mark.parametrize("ordered_for_type", ["", "unknown", "milana-like", " unknown "])
def test_unsupported_branded_order_type_keeps_400_and_writes_nothing(
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

    assert response.status_code == 400
    assert "Choose Milana" in response.json()["detail"]
    with TestSessionLocal() as db:
        assert db.query(BrandedPlanningOrder.id).count() == order_count_before
        assert db.query(AuditLog.id).count() == audit_count_before


def test_branded_order_type_guard_preserves_authentication_precedence(client):
    response = client.post(
        "/api/planning/branded-orders",
        json={"ordered_for_type": "unknown"},
    )

    assert response.status_code == 401


def test_branded_order_type_guard_keeps_normalized_stable_code(client, auth_headers):
    response = client.post(
        "/api/planning/branded-orders",
        headers=auth_headers,
        json={"ordered_for_type": "  BESTTEX  "},
    )

    assert response.status_code == 201, response.text
    assert response.json()["ordered_for_type"] == "besttex"
    assert response.json()["ordered_for_name"] == "Besttex"
