from uuid import uuid4

from app.db.session import SessionLocal
from app.models import AuditLog, Model, PriceCalculationRequest


def test_accessory_completion_rejects_unrepresentable_derived_cost_before_writes(client, auth_headers):
    with SessionLocal() as db:
        model_id = int(db.query(Model.id).filter(Model.catalog_scope == "standard").order_by(Model.id).scalar())
    created = client.post(
        "/api/price-calculation/requests", headers=auth_headers, json={"model_id": model_id},
    )
    assert created.status_code == 201, created.text
    request_id = int(created.json()["id"])

    cutting = client.patch(
        f"/api/price-calculation/requests/{request_id}/cutting",
        headers=auth_headers,
        json={
            "kroy_no": f"DERIVED-{uuid4().hex[:8]}",
            "fabric_width_m": "9999999999.9999",
            "lay_length_m": 2,
            "size_count": 1,
            "gramage": 1,
            "binding_kg_per_piece": 0,
        },
    )
    assert cutting.status_code == 200, cutting.text
    purchasing = client.patch(
        f"/api/price-calculation/requests/{request_id}/purchasing",
        headers=auth_headers,
        json={"fabric_price": 2, "sewing_cost": 1},
    )
    assert purchasing.status_code == 200, purchasing.text
    with SessionLocal() as db:
        before_audits = db.query(AuditLog).count()

    rejected = client.patch(
        f"/api/price-calculation/requests/{request_id}/accessories",
        headers=auth_headers,
        json={"accessories": [{"name": "Button", "price": 1}]},
    )
    assert rejected.status_code == 422, rejected.text
    with SessionLocal() as db:
        request = db.get(PriceCalculationRequest, request_id)
        assert request.accessories_json == []
        assert db.query(AuditLog).count() == before_audits
        # Imported or older rows may already contain this combination.
        request.accessories_json = [{"name": "Button", "price": 1}]
        db.commit()

    listed = client.get("/api/price-calculation/requests", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    row = next(row for row in listed.json() if row["id"] == request_id)
    assert row["cost_price"] is None
    assert row["difference"] is None
