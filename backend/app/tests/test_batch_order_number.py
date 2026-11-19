"""New Nastil references follow the displayed business order, never its PK."""
import pytest

from app.db.session import SessionLocal
from app.models.production_service import create_production_batches
from app.schemas import Model, ProductionBatch, ProductionOrder, SalesOrder
from app.tests.test_passport_cutting_submission import passport_cutting  # noqa: F401


@pytest.mark.parametrize(("production_no", "sales_no", "prefix"), [
    ("PO-0887", None, "0887"),
    ("PO-0999", "SO-0421", "0421"),
    ("USL-0027", None, "0027"),
    ("PO-10001", None, "10001"),
])
def test_initial_batches_follow_public_order_and_retry_preserves_identity(production_no, sales_no, prefix):
    with SessionLocal() as db:
        sales = SalesOrder(order_no=sales_no) if sales_no else None
        if sales:
            db.add(sales)
            db.flush()
        order = ProductionOrder(production_no=production_no, model_id=db.query(Model.id).first()[0],
                                production_type="client_order" if sales else "branded_stock",
                                sales_order_id=sales.id if sales else None, planned_quantity=12)
        db.add(order)
        db.flush()
        assert order.id != int(prefix), "Fixture must distinguish business number from database ID"
        batches = create_production_batches(db, order.id, [{"planned_quantity": 5}, {"planned_quantity": 7}])
        assert [row.batch_no for row in batches] == [f"{prefix}-01", f"{prefix}-02"]
        original = [(row.id, row.batch_no) for row in batches]
        retry = create_production_batches(db, order.id, [{"planned_quantity": 12}])
        assert [(row.id, row.batch_no) for row in retry] == original
        assert db.query(ProductionBatch).filter_by(production_order_id=order.id).count() == 2


def test_later_manual_nastil_follows_order_without_renaming_existing(client, auth_headers, passport_cutting):
    _, order, work, payload = passport_cutting
    with SessionLocal() as db:
        db.get(ProductionOrder, order["id"]).production_no = "PO-0887"
        original = db.get(ProductionBatch, payload["production_batch_id"])
        original.batch_no = "HISTORICAL-IMMUTABLE-01"
        original_id = original.id
        db.commit()
    response = client.post(f"/api/work-orders/{work['id']}/extra-batch", headers=auth_headers,
                           json={"planned_quantity": 4})
    assert response.status_code == 200, response.text
    assert response.json()["batch_no"] == "0887-02"
    with SessionLocal() as db:
        assert db.get(ProductionBatch, original_id).batch_no == "HISTORICAL-IMMUTABLE-01"


def test_later_passport_nastil_follows_public_order(client, auth_headers, passport_cutting):
    _, order, _, payload = passport_cutting
    with SessionLocal() as db:
        db.get(ProductionOrder, order["id"]).production_no = "PO-0887"
        first = db.get(ProductionBatch, payload["production_batch_id"])
        original = (first.id, first.batch_no)
        db.commit()
    response = client.post("/api/cutting-passports", headers=auth_headers, json={
        "production_order_id": order["id"], "date": "2026-11-13T00:00:00Z", "pieces": 4,
    })
    assert response.status_code == 201, response.text
    with SessionLocal() as db:
        assert db.get(ProductionBatch, response.json()["production_batch_id"]).batch_no == "0887-02"
        assert db.get(ProductionBatch, original[0]).batch_no == original[1]


@pytest.mark.parametrize("reference", ["0027-01", "BATCH:0027-01"])
def test_unscoped_duplicate_batch_scan_refuses_instead_of_opening_another_order(client, auth_headers, reference):
    from app.api.routes.traceability import _find_production_batch

    with SessionLocal() as db:
        model_id = db.query(Model.id).first()[0]
        orders = [ProductionOrder(production_no=number, model_id=model_id, production_type="branded_stock")
                  for number in ("PO-0027", "USL-0027")]
        db.add_all(orders)
        db.flush()
        batches = [create_production_batches(db, order.id, [{"planned_quantity": 3}])[0] for order in orders]
        assert [row.batch_no for row in batches] == ["0027-01", "0027-01"]
        ids = [row.id for row in batches]
        db.commit()
        # Existing printed ID-based QR codes retain precise resolution.
        for batch_id in ids:
            assert _find_production_batch(db, f"BATCH_ID:{batch_id}").id == batch_id
    response = client.get(f"/api/traceability/production-batch/{reference}", headers=auth_headers)
    assert response.status_code == 409, response.text
    assert "multiple orders" in response.json()["detail"]
