from uuid import uuid4

from app.db.session import SessionLocal
from app.models import AuditLog, Model, PriceCalculationRequest, User


def test_price_request_list_survives_malformed_legacy_accessory_price_without_rewrite(
    client, auth_headers,
):
    code = f"PC-LEGACY-{uuid4().hex[:12]}"
    original = [
        {"name": name, "price": price}
        for name, price in (
            ("Button", "not-a-price"), ("Zip", "NaN"),
            ("Label", "Infinity"), ("Thread", "1e10000"),
        )
    ]
    with SessionLocal() as db:
        model = Model(code=code, name="Legacy accessory price")
        db.add(model)
        db.flush()
        creator_id = db.query(User.id).order_by(User.id).first()[0]
        request = PriceCalculationRequest(
            model_id=model.id, created_by_id=creator_id, accessories_json=original,
        )
        db.add(request)
        db.commit()
        request_id = request.id
        before_audits = db.query(AuditLog).count()

    response = client.get("/api/price-calculation/requests", headers=auth_headers)
    assert response.status_code == 200, response.text
    row = next(row for row in response.json() if row["id"] == request_id)
    assert row["accessories"] == [{"name": item["name"], "price": None} for item in original]
    assert row["accessories_status"] == "in_progress"
    assert row["overall_status"] == "in_progress"
    assert row["cost_price"] is None
    with SessionLocal() as db:
        assert db.get(PriceCalculationRequest, request_id).accessories_json == original
        assert db.query(AuditLog).count() == before_audits

        # Historical JSON could also have the wrong root shape.
        db.get(PriceCalculationRequest, request_id).accessories_json = 7
        db.commit()

    malformed_root = client.get("/api/price-calculation/requests", headers=auth_headers)
    assert malformed_root.status_code == 200, malformed_root.text
    row = next(row for row in malformed_root.json() if row["id"] == request_id)
    assert row["accessories"] == []
    assert row["accessories_status"] == "new"
    with SessionLocal() as db:
        assert db.get(PriceCalculationRequest, request_id).accessories_json == 7
        assert db.query(AuditLog).count() == before_audits
