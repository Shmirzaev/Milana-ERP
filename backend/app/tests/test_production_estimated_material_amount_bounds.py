from app.db.session import SessionLocal
from uuid import uuid4

from app.models import AuditLog, Item, ProductionOrder, StockBatch, Warehouse


MAX_ESTIMATED_MATERIAL_AMOUNT = 9_999_999_999.9999


def _write_counts() -> tuple[int, int]:
    with SessionLocal() as db:
        return (
            db.query(ProductionOrder).count(),
            db.query(AuditLog).count(),
        )


def _payload(model_id: int, amount: object) -> dict:
    return {
        "production_type": "branded_stock",
        "model_id": model_id,
        "estimated_material_amount": amount,
    }


def test_estimated_material_amount_rejects_non_finite_and_numeric_overflow(
    client,
    auth_headers,
):
    before = _write_counts()

    for amount in ("NaN", "Infinity", 10_000_000_000):
        response = client.post(
            "/api/production-orders",
            headers=auth_headers,
            json=_payload(1, amount),
        )

        assert response.status_code == 422, response.text
        assert _write_counts() == before


def test_estimated_material_amount_accepts_storage_maximum(client, auth_headers):
    response = client.post(
        "/api/production-orders",
        headers=auth_headers,
        json=_payload(1, MAX_ESTIMATED_MATERIAL_AMOUNT),
    )

    assert response.status_code == 201, response.text
    assert response.json()["estimated_material_amount"] == MAX_ESTIMATED_MATERIAL_AMOUNT


def test_estimated_material_amount_rejects_extra_fractional_places_without_writes(client, auth_headers):
    before = _write_counts()
    response = client.post(
        "/api/production-orders", headers=auth_headers,
        json=_payload(1, "1.00001"),
    )

    assert response.status_code == 422, response.text
    assert _write_counts() == before

    accepted = client.post(
        "/api/production-orders", headers=auth_headers,
        json=_payload(1, "1.0001"),
    )
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["estimated_material_amount"] == 1.0001


def test_material_line_estimate_cannot_silently_round_production_amount(client, auth_headers):
    marker = uuid4().hex[:8]
    with SessionLocal() as db:
        warehouse = Warehouse(name=f"FN07 fabric {marker}", type="fabric_storage")
        item = Item(sku=f"FN07-FABRIC-{marker}", name="Precision fabric", category="fabric", unit="kg")
        db.add_all([warehouse, item])
        db.flush()
        batch = StockBatch(
            item_id=item.id, batch_no=f"FN07-BATCH-{marker}", quantity=10,
            unit="kg", warehouse_id=warehouse.id, qc_status="passed",
        )
        db.add(batch)
        db.commit()
        batch_id = batch.id

    before = _write_counts()
    response = client.post(
        "/api/production-orders", headers=auth_headers,
        json={
            "production_type": "branded_stock", "model_id": 1,
            "materials": [{"stock_batch_id": batch_id, "estimated_quantity": 1.00001, "unit": "kg"}],
        },
    )
    assert response.status_code == 422, response.text
    assert _write_counts() == before


def test_estimated_material_amount_keeps_auth_and_model_error_precedence(client, auth_headers):
    unauthenticated = client.post(
        "/api/production-orders",
        json=_payload(1, "Infinity"),
    )
    assert unauthenticated.status_code == 401

    missing_model = client.post(
        "/api/production-orders",
        headers=auth_headers,
        json=_payload(2_147_483_647, "Infinity"),
    )
    assert missing_model.status_code == 404

    missing_model_extra_places = client.post(
        "/api/production-orders",
        headers=auth_headers,
        json=_payload(2_147_483_647, "1.00001"),
    )
    assert missing_model_extra_places.status_code == 404
