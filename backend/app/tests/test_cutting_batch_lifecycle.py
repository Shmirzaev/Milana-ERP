import pytest

from app.db.session import SessionLocal
from app.models import (
    Bundle, CuttingRecord, MaterialReservation, ProductionBatch, SewingRecord,
    StockBatch, StockMovement, WorkOrder,
)
from app.tests.test_passport_cutting_submission import passport_cutting  # noqa: F401


def _cut(client, headers, payload):
    response = client.post("/api/cutting/records", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_delete_reverses_exact_materials_and_reservations_and_keeps_sibling(client, auth_headers, passport_cutting):
    stocks, order, work, payload = passport_cutting
    rid = _cut(client, auth_headers, payload)
    with SessionLocal() as db:
        sibling = ProductionBatch(production_order_id=order["id"], batch_no="KEEP-02",
                                  batch_index=2, planned_quantity=5, name="Keep")
        db.add(sibling)
        db.commit()
        sibling_id = sibling.id
    url = f"/api/work-orders/{work['id']}/batches/{payload['production_batch_id']}"
    response = client.delete(url, headers=auth_headers)
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        assert db.get(ProductionBatch, payload["production_batch_id"]) is None
        assert db.get(ProductionBatch, sibling_id).name == "Keep"
        assert db.get(CuttingRecord, rid) is None
        assert not db.query(Bundle).filter_by(production_batch_id=payload["production_batch_id"]).count()
        assert [float(db.get(StockBatch, row["id"]).quantity) for row in stocks] == [100, 100]
        assert all(float(row.consumed_quantity) == 0 for row in db.query(MaterialReservation).filter_by(production_order_id=order["id"]))
        assert db.query(StockMovement).filter_by(reference_type="CuttingRecord", reference_id=rid).count() == 2
        assert db.query(StockMovement).filter_by(reference_type="CuttingBatchDeletion").count() == 2
        assert db.get(WorkOrder, work["id"]).passed_qty == 0
    assert client.delete(url, headers=auth_headers).status_code == 404
    with SessionLocal() as db:
        assert [float(db.get(StockBatch, row["id"]).quantity) for row in stocks] == [100, 100]


@pytest.mark.parametrize("legacy", [False, True])
def test_sewing_output_freezes_all_batch_edits_and_delete(client, auth_headers, passport_cutting, legacy):
    stocks, order, work, payload = passport_cutting
    rid = _cut(client, auth_headers, payload)
    with SessionLocal() as db:
        sewing = db.query(WorkOrder).filter_by(production_order_id=order["id"], operation="sewing").one()
        db.add(SewingRecord(work_order_id=sewing.id, production_batch_id=None if legacy else payload["production_batch_id"],
                           input_qty=1, sewn_qty=1, passed_qty=1))
        db.commit()
        bundle = db.query(Bundle).filter_by(production_batch_id=payload["production_batch_id"]).one()
        bundle_id = bundle.id
    url = f"/api/work-orders/{work['id']}/batches/{payload['production_batch_id']}"
    for method, path, body in [
        ("delete", url, None),
        ("patch", url, {"name": "Changed"}),
        ("patch", f"/api/cutting/records/{rid}", {"notes": "Changed"}),
        ("patch", f"/api/cutting/records/{rid}/bundle-quantities", {"bundles": [{"id": bundle_id, "quantity": 11}]}),
    ]:
        response = client.request(method, path, headers=auth_headers, json=body)
        assert response.status_code == 409, response.text
        assert "Sewing output" in response.text
    rows = client.get(f"/api/work-orders/{work['id']}/cutting-batch-progress", headers=auth_headers).json()["items"]
    target = next(row for row in rows if row["id"] == payload["production_batch_id"])
    assert not target["editable"] and not target["name_editable"] and not target["deletable"]
    with SessionLocal() as db:
        assert [float(db.get(StockBatch, row["id"]).quantity) for row in stocks] == [93.5, 93.5]
        assert db.get(CuttingRecord, rid) is not None


def test_delete_rejects_unproven_stock_movement_atomically(client, auth_headers, passport_cutting):
    stocks, order, work, payload = passport_cutting
    rid = _cut(client, auth_headers, payload)
    with SessionLocal() as db:
        movement = db.query(StockMovement).filter_by(reference_type="CuttingRecord", reference_id=rid).first()
        movement.quantity += 1
        db.commit()
    response = client.delete(f"/api/work-orders/{work['id']}/batches/{payload['production_batch_id']}", headers=auth_headers)
    assert response.status_code == 409, response.text
    with SessionLocal() as db:
        assert db.get(CuttingRecord, rid)
        assert [float(db.get(StockBatch, row["id"]).quantity) for row in stocks] == [93.5, 93.5]
        assert not db.query(StockMovement).filter_by(reference_type="CuttingBatchDeletion").count()


def test_delete_rejects_wrong_work_order_and_anonymous(client, auth_headers, passport_cutting):
    _, order, work, payload = passport_cutting
    with SessionLocal() as db:
        sewing = db.query(WorkOrder).filter_by(production_order_id=order["id"], operation="sewing").one()
        sewing_id = sewing.id
    assert client.delete(f"/api/work-orders/{work['id']}/batches/{payload['production_batch_id']}").status_code == 401
    assert client.delete(f"/api/work-orders/{sewing_id}/batches/{payload['production_batch_id']}", headers=auth_headers).status_code == 404


def test_real_sewing_handoff_freezes_cutting(client, auth_headers, passport_cutting):
    _, order, work, payload = passport_cutting
    # This fixture's planned fabrics are explicit; no accessory BOM is required.
    from app.models import ModelBOM
    with SessionLocal() as db:
        db.query(ModelBOM).filter_by(model_id=order["model_id"]).delete()
        db.commit()
    _cut(client, auth_headers, payload)
    with SessionLocal() as db:
        bundle_id = db.query(Bundle).filter_by(production_batch_id=payload["production_batch_id"]).one().id
        sewing_id = db.query(WorkOrder).filter_by(production_order_id=order["id"], operation="sewing").one().id
    received = client.post(f"/api/bundles/{bundle_id}/receive-sewing", headers=auth_headers)
    assert received.status_code == 200, received.text
    sewn = client.post("/api/sewing/records", headers=auth_headers, json={
        "work_order_id": sewing_id, "production_batch_id": payload["production_batch_id"],
        "input_qty": 10, "sewn_qty": 10, "passed_qty": 10,
    })
    assert sewn.status_code == 201, sewn.text
    assert client.delete(f"/api/work-orders/{work['id']}/batches/{payload['production_batch_id']}", headers=auth_headers).status_code == 409
    assert client.patch(f"/api/work-orders/{work['id']}/batches/{payload['production_batch_id']}",
                        headers=auth_headers, json={"name": "Changed"}).status_code == 409
    packaging = client.get(f"/api/work-orders?production_order_id={order['id']}", headers=auth_headers).json()
    assert next(row for row in packaging if row["operation"] == "packaging")["planned_output_qty"] >= 10


def test_delete_before_sewing_output_reverses_receipt(client, auth_headers, passport_cutting):
    from app.models import ModelBOM
    stocks, order, work, payload = passport_cutting
    with SessionLocal() as db:
        db.query(ModelBOM).filter_by(model_id=order["model_id"]).delete()
        db.commit()
    _cut(client, auth_headers, payload)
    with SessionLocal() as db:
        bundle_id = db.query(Bundle).filter_by(production_batch_id=payload["production_batch_id"]).one().id
        sewing_id = db.query(WorkOrder).filter_by(production_order_id=order["id"], operation="sewing").one().id
    assert client.post(f"/api/bundles/{bundle_id}/receive-sewing", headers=auth_headers).status_code == 200
    with SessionLocal() as db:
        assert db.get(WorkOrder, sewing_id).actual_input_qty == 10
    response = client.delete(f"/api/work-orders/{work['id']}/batches/{payload['production_batch_id']}", headers=auth_headers)
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        assert db.get(WorkOrder, sewing_id).actual_input_qty == 0
        assert [float(db.get(StockBatch, row["id"]).quantity) for row in stocks] == [100, 100]


def test_delete_pending_shortage_returns_only_consumed_fabric(client, auth_headers, passport_cutting):
    stocks, _, work, payload = passport_cutting
    with SessionLocal() as db:
        db.get(StockBatch, stocks[0]["id"]).quantity = 0
        db.commit()
    _cut(client, auth_headers, payload)
    response = client.delete(f"/api/work-orders/{work['id']}/batches/{payload['production_batch_id']}", headers=auth_headers)
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        assert [float(db.get(StockBatch, row["id"]).quantity) for row in stocks] == [0, 100]
        assert db.query(StockMovement).filter_by(reference_type="CuttingBatchDeletion").count() == 1


def test_sibling_output_does_not_lock_unsewn_batch(client, auth_headers, passport_cutting):
    _, order, work, payload = passport_cutting
    _cut(client, auth_headers, payload)
    with SessionLocal() as db:
        sibling = ProductionBatch(production_order_id=order["id"], batch_no="KEEP-02",
                                  batch_index=2, planned_quantity=5)
        db.add(sibling)
        db.flush()
        sewing = db.query(WorkOrder).filter_by(production_order_id=order["id"], operation="sewing").one()
        db.add(SewingRecord(work_order_id=sewing.id, production_batch_id=sibling.id,
                           input_qty=1, sewn_qty=1, passed_qty=1))
        db.commit()
        sibling_id = sibling.id
    url = f"/api/work-orders/{work['id']}/batches/{payload['production_batch_id']}"
    assert client.patch(url, headers=auth_headers, json={"name": "Unsewn"}).status_code == 200
    response = client.delete(url, headers=auth_headers)
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        assert db.get(ProductionBatch, sibling_id)
        assert db.query(SewingRecord).filter_by(production_batch_id=sibling_id).count() == 1


def test_delete_rejects_linked_printing_history(client, auth_headers, passport_cutting):
    from app.models import PrintingRecord
    stocks, order, work, payload = passport_cutting
    _cut(client, auth_headers, payload)
    with SessionLocal() as db:
        printing = WorkOrder(production_order_id=order["id"], department_id=work["department_id"],
                             operation="printing", status="in_progress")
        db.add(printing)
        db.flush()
        db.add(PrintingRecord(work_order_id=printing.id, production_batch_id=payload["production_batch_id"],
                              input_qty=10, printed_qty=10, passed_qty=10))
        db.commit()
    response = client.delete(f"/api/work-orders/{work['id']}/batches/{payload['production_batch_id']}", headers=auth_headers)
    assert response.status_code == 409, response.text
    with SessionLocal() as db:
        assert [float(db.get(StockBatch, row["id"]).quantity) for row in stocks] == [93.5, 93.5]


@pytest.mark.parametrize("factory,permissions", [("ECO", ["cutting.records"]), ("MIL", ["cutting.workspace"])])
def test_delete_requires_cutting_permission_and_matching_factory(client, auth_headers, passport_cutting, factory, permissions):
    from app.core.security import create_access_token
    from app.models import User
    _, _, work, payload = passport_cutting
    with SessionLocal() as db:
        user = User(name="Scoped delete", email="scoped-delete@example.invalid", password_hash="unused",
                    factory_code=factory, extra_permissions=permissions)
        db.add(user)
        db.commit()
        token = create_access_token(user.id, extra={"factory_code": factory})
    response = client.delete(f"/api/work-orders/{work['id']}/batches/{payload['production_batch_id']}",
                             headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403, response.text
