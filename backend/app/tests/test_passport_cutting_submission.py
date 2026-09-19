from uuid import uuid4
import pytest
from app.db.session import SessionLocal
from app.models import Bundle, CuttingRecord, StockBatch, WorkOrder
from app.tests.test_material_reservations import _warehouse, _fabric_item, _receive_batch, _cutting_work_order


@pytest.fixture
def passport_cutting(client, auth_headers):
    warehouse = _warehouse(client, auth_headers, "fabric_storage")
    item = _fabric_item(client, auth_headers)
    batches = [_receive_batch(client, auth_headers, item_id=item["id"], warehouse_id=warehouse["id"], quantity=100, unit="kg") for _ in range(2)]
    response = client.post("/api/planning/create-branded-production", headers=auth_headers, json={
        "production_type": "branded_stock", "model_id": 1, "planned_quantity": 10,
        "materials": [{"stock_batch_id": row["id"], "estimated_quantity": 10, "unit": "kg"} for row in batches],
        "items": [{"model_id": 1, "color": "white", "size": "46", "planned_quantity": 10, "printing_required": False}],
    })
    assert response.status_code == 201, response.text
    order = response.json()
    work = _cutting_work_order(client, auth_headers, order["id"])
    passport = client.post("/api/cutting-passports", headers=auth_headers, json={
        "passport_no": "SAVED-" + uuid4().hex[:8], "date": "2026-09-19T00:00:00Z", "production_order_id": order["id"],
        "materials": [{"stock_batch_id": row["id"], "layer_weight_kg": 2, "total_layers": 3, "scrap_kg": 0.5,
                       "pieces": 10, "rolls_count": 1, "operator_name_manual": "Saved operator"} for row in batches],
    })
    assert passport.status_code == 201, passport.text
    payload = {"work_order_id": work["id"], "cutting_passport_id": passport.json()["id"], "use_passport_materials": True,
               "input_quantity": 999, "materials": [], "cut_pieces": 10, "passed_pieces": 10,
               "bundles": [{"color": "white", "size": "46", "quantity": 10, "count": 1, "next": "sewing", "sewing_factory": "milana"}]}
    return batches, order, work, payload


def test_saved_passport_consumes_exact_stock_once_and_keeps_bundle_handoff(client, auth_headers, passport_cutting):
    batches, order, work, payload = passport_cutting
    result = client.post("/api/cutting/records", headers=auth_headers, json=payload)
    assert result.status_code == 201, result.text
    assert [row["quantity"] for row in result.json()["materials"]] == [6.5, 6.5]
    with SessionLocal() as db:
        assert [float(db.get(StockBatch, row["id"]).quantity) for row in batches] == [93.5, 93.5]
        assert db.query(Bundle).filter_by(production_order_id=order["id"]).one().quantity == 10
        assert db.get(WorkOrder, work["id"]).passed_qty == 10
    again = client.post("/api/cutting/records", headers=auth_headers, json=payload)
    assert again.status_code in {400, 409}, again.text
    with SessionLocal() as db:
        assert db.query(CuttingRecord).filter_by(work_order_id=work["id"]).count() == 1
        assert [float(db.get(StockBatch, row["id"]).quantity) for row in batches] == [93.5, 93.5]


def test_missing_passport_does_not_consume_or_create_bundles(client, auth_headers, passport_cutting):
    batches, order, work, payload = passport_cutting
    payload["cutting_passport_id"] = None
    response = client.post("/api/cutting/records", headers=auth_headers, json=payload)
    assert response.status_code == 400, response.text
    with SessionLocal() as db:
        assert db.query(Bundle).filter_by(production_order_id=order["id"]).count() == 0
        assert [float(db.get(StockBatch, row["id"]).quantity) for row in batches] == [100, 100]


def test_awaiting_packaging_has_business_identity(client, auth_headers, passport_cutting):
    _, order, _, _ = passport_cutting
    with SessionLocal() as db:
        sew = db.query(WorkOrder).filter_by(production_order_id=order["id"], operation="sewing").one()
        sew.passed_qty = 7
        db.commit()
    result = client.get("/api/inbox?dept=PKG", headers=auth_headers)
    assert result.status_code == 200, result.text
    row = next(row for row in result.json()["awaiting_packaging"] if row["production_order_id"] == order["id"])
    assert row["order_no"] and row["production_no"]
    assert row["model_no"] and "variant_no" in row and "model_image_url" in row and "material_image_url" in row
    assert row["ready_qty"] == 7
