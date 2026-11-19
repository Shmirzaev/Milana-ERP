"""Transferred ECO fabric keeps its source identity but owns its physical ledger."""
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models.factory_scope_service import bind_session_factory
from app.models.production.ect_passport_fabric_service import list_passport_fabrics, REVERSAL_REFERENCE
from app.schemas import (Bundle, CuttingRecord, Department, MaterialReservation, ProductionOrder,
                         ProductionOrderMaterial, Role, StockBatch, StockMovement, User, WorkOrder)
from app.schemas.inventory.eco_inventory import EcoMaterialBatch, EcoMaterialMovement
from app.tests.test_passport_cutting_submission import passport_cutting  # noqa: F401


@pytest.fixture
def transferred_cutting(passport_cutting):
    stocks, order, work, payload = passport_cutting
    with SessionLocal() as db:
        actor = db.query(User).filter_by(email="admin@example.com").one()
        department = db.query(Department).filter_by(code="ECT").one()
        db.get(WorkOrder, work["id"]).department_id = department.id
        source = db.get(StockBatch, stocks[0]["id"])
        source.quantity = 0
        source.archived_at = datetime.now(timezone.utc)
        rows = [EcoMaterialBatch(item_id=source.item_id, kind="fabric", batch_no=source.batch_no,
            unit=source.unit, quantity=quantity, reserved_quantity=0,
            source_stock_batch_id=source.id, created_by=actor.id) for quantity in (Decimal("5"), Decimal("146.8"))]
        db.add_all(rows)
        db.commit()
        headers = {"Authorization": f"Bearer {create_access_token(actor.id, extra={'factory_code': 'ECO'})}"}
        ids = [row.id for row in rows]
    return stocks, order, work, payload, headers, ids


def test_archived_source_split_receipts_cut_edit_retry_and_delete(client, transferred_cutting):
    stocks, order, work, payload, headers, eco_ids = transferred_cutting
    passport_url = f"/api/cutting-passports/{payload['cutting_passport_id']}"
    saved = client.get(passport_url, headers=headers)
    assert saved.status_code == 200, saved.text
    # Saving a passport validates the physical ECO balance, even with zero in Milana.
    changed = client.patch(passport_url, headers=headers, json={**saved.json(), "notes": "ECT transfer"})
    assert changed.status_code == 200, changed.text
    with SessionLocal() as db:
        actor = db.query(User).filter_by(email="admin@example.com").one()
        bind_session_factory(actor, "ECO")
        options = list_passport_fabrics(db, actor, order["id"], stocks[0]["batch_no"])
        option = next(row for row in options if row["id"] == stocks[0]["id"])
        assert option["available_quantity"] == 151.8
        assert option["warehouse_name"] == "Eco Cotton"
        assert "cost_per_unit" not in option
    cut = client.post("/api/cutting/records", headers=headers, json=payload)
    assert cut.status_code == 201, cut.text
    record_id = cut.json()["id"]
    with SessionLocal() as db:
        assert [db.get(EcoMaterialBatch, key).quantity for key in eco_ids] == [Decimal("0"), Decimal("145.3")]
        assert db.get(StockBatch, stocks[0]["id"]).quantity == 0
        assert db.get(StockBatch, stocks[1]["id"]).quantity == Decimal("93.5")
        assert db.query(EcoMaterialMovement).filter_by(reference_type="CuttingRecord", reference_id=record_id).count() == 2
        assert db.query(StockMovement).filter_by(reference_type="CuttingRecord", reference_id=record_id).count() == 1
        assert all(not row.consumed_quantity for row in db.query(MaterialReservation).filter_by(
            production_order_id=order["id"], stock_batch_id=stocks[0]["id"]))
    reported = client.get("/api/inventory/cutting-fabric-usage", headers=headers,
                          params={"batch_id": stocks[0]["id"]})
    assert reported.status_code == 200, reported.text
    assert reported.json()["total"] == 1
    assert reported.json()["rows"][0]["quantity"] == 6.5
    assert reported.json()["rows"][0]["movement_count"] == 2
    assert reported.json()["rows"][0]["batch_id"] == stocks[0]["id"]
    # Edits credit this passport's own prior debit; retries do not consume again.
    saved = client.get(passport_url, headers=headers).json()
    assert client.patch(passport_url, headers=headers, json={**saved, "notes": "After cutting"}).status_code == 200
    assert client.post("/api/cutting/records", headers=headers, json=payload).status_code in (400, 409)
    delete_url = f"/api/work-orders/{work['id']}/batches/{payload['production_batch_id']}"
    removed = client.delete(delete_url, headers=headers)
    assert removed.status_code == 200, removed.text
    with SessionLocal() as db:
        assert [db.get(EcoMaterialBatch, key).quantity for key in eco_ids] == [Decimal("5"), Decimal("146.8")]
        assert db.get(StockBatch, stocks[0]["id"]).quantity == 0
        assert db.get(StockBatch, stocks[0]["id"]).archived_at is not None
        assert db.get(StockBatch, stocks[1]["id"]).quantity == 100
        assert db.query(EcoMaterialMovement).filter_by(reference_type=REVERSAL_REFERENCE).count() == 2
        assert db.query(EcoMaterialMovement).filter_by(reference_type="CuttingRecord", reference_id=record_id).count() == 2
    assert client.delete(delete_url, headers=headers).status_code == 404
    report = client.get("/api/inventory/cutting-fabric-usage", headers=headers,
                        params={"batch_id": stocks[0]["id"]}).json()
    assert report["total"] == 0 and report["totals"] == []


def test_mapped_eco_shortage_never_falls_back_or_leaves_partial_cut(client, transferred_cutting):
    stocks, order, work, payload, headers, eco_ids = transferred_cutting
    with SessionLocal() as db:
        db.get(StockBatch, stocks[0]["id"]).quantity = 1000
        for key in eco_ids:
            db.get(EcoMaterialBatch, key).quantity = 1
        before = db.get(WorkOrder, work["id"]).passed_qty
        db.commit()
    result = client.post("/api/cutting/records", headers=headers, json=payload)
    assert result.status_code == 409, result.text
    assert "transferred Eco Cotton fabric" in result.text
    with SessionLocal() as db:
        assert [db.get(EcoMaterialBatch, key).quantity for key in eco_ids] == [1, 1]
        assert db.get(StockBatch, stocks[0]["id"]).quantity == 1000
        assert db.get(StockBatch, stocks[1]["id"]).quantity == 100
        assert db.get(WorkOrder, work["id"]).passed_qty == before
        assert db.query(CuttingRecord).filter_by(work_order_id=work["id"]).count() == 0
        assert db.query(Bundle).filter_by(production_order_id=order["id"]).count() == 0
        assert db.query(EcoMaterialMovement).filter_by(reference_type="CuttingRecord").count() == 0


def test_unproven_eco_movement_blocks_deletion_without_stock_returns(client, transferred_cutting):
    stocks, _, work, payload, headers, eco_ids = transferred_cutting
    cut = client.post("/api/cutting/records", headers=headers, json=payload)
    assert cut.status_code == 201, cut.text
    with SessionLocal() as db:
        db.query(EcoMaterialMovement).filter_by(reference_type="CuttingRecord", reference_id=cut.json()["id"]).first().quantity += 1
        db.commit()
    response = client.delete(f"/api/work-orders/{work['id']}/batches/{payload['production_batch_id']}", headers=headers)
    assert response.status_code == 409, response.text
    with SessionLocal() as db:
        assert [db.get(EcoMaterialBatch, key).quantity for key in eco_ids] == [0, Decimal("145.3")]
        assert db.get(StockBatch, stocks[0]["id"]).quantity == 0
        assert db.get(StockBatch, stocks[1]["id"]).quantity == Decimal("93.5")
        assert db.get(CuttingRecord, cut.json()["id"]) is not None
        assert db.query(EcoMaterialMovement).filter_by(reference_type=REVERSAL_REFERENCE).count() == 0


def test_eco_report_excludes_explicitly_reversed_consumption(client, transferred_cutting):
    stocks, _, _, payload, headers, _ = transferred_cutting
    cut = client.post("/api/cutting/records", headers=headers, json=payload)
    assert cut.status_code == 201, cut.text
    from app.models.production.ect_passport_fabric_service import cutting_eco_consumption, reverse_cutting_eco_consumption
    with SessionLocal() as db:
        actor = db.query(User).filter_by(email="admin@example.com").one()
        bind_session_factory(actor, "ECO")
        _, movements = cutting_eco_consumption(db, [cut.json()["id"]], lock=True)
        reverse_cutting_eco_consumption(db, movements, actor)
        db.commit()
    # Reversal is excluded even while its original record still exists.
    report = client.get("/api/inventory/cutting-fabric-usage", headers=headers,
                        params={"batch_id": stocks[0]["id"]})
    assert report.status_code == 200, report.text
    assert report.json()["total"] == 0 and report.json()["totals"] == []


def test_qc_and_reserved_eco_stock_are_unavailable(client, transferred_cutting):
    stocks, order, _, payload, headers, eco_ids = transferred_cutting
    with SessionLocal() as db:
        db.get(EcoMaterialBatch, eco_ids[0]).receipt_details = {"qc_status": "pending"}
        other = db.get(EcoMaterialBatch, eco_ids[1])
        other.reserved_quantity = other.quantity
        db.commit()
    url = f"/api/cutting-passports/{payload['cutting_passport_id']}"
    saved = client.get(url, headers=headers).json()
    response = client.patch(url, headers=headers, json=saved)
    assert response.status_code == 409, response.text
    with SessionLocal() as db:
        actor = db.query(User).filter_by(email="admin@example.com").one()
        bind_session_factory(actor, "ECO")
        assert not any(row["id"] == stocks[0]["id"] for row in list_passport_fabrics(db, actor, order["id"]))


def test_cutting_only_lookup_add_transferred_fabric_and_permissions(client, auth_headers, transferred_cutting):
    stocks, order, _, payload, _, eco_ids = transferred_cutting
    with SessionLocal() as db:
        # The missing fabric is selected in the passport rather than Planning.
        db.query(ProductionOrderMaterial).filter_by(production_order_id=order["id"], stock_batch_id=stocks[0]["id"]).delete()
        db.query(MaterialReservation).filter_by(production_order_id=order["id"], stock_batch_id=stocks[0]["id"]).delete()
        db.get(ProductionOrder, order["id"]).fabric_batch_id = stocks[1]["id"]
        role = Role(name="ECT passport only", permissions=["cutting.records", "cutting.bundles"])
        actor = User(name="ECT cutting", email="ect-passport@example.invalid", password_hash="unused",
                     factory_code="ECO", role=role)
        denied = User(name="ECT sewing", email="ect-denied@example.invalid", password_hash="unused",
                      factory_code="ECO", role=Role(name="ECT no cutting", permissions=["sewing.records"]))
        db.add_all([actor, denied])
        db.commit()
        cutting_headers = {"Authorization": f"Bearer {create_access_token(actor.id, extra={'factory_code': 'ECO'})}"}
        denied_headers = {"Authorization": f"Bearer {create_access_token(denied.id, extra={'factory_code': 'ECO'})}"}
    url = f"/api/cutting-passports/material-batches?production_order_id={order['id']}&q={stocks[0]['batch_no']}"
    assert client.get(url, headers=auth_headers).status_code == 403  # Wrong selected factory.
    assert client.get(url, headers=denied_headers).status_code == 403
    found = client.get(url, headers=cutting_headers)
    assert found.status_code == 200, found.text
    row = next(row for row in found.json() if row["id"] == stocks[0]["id"])
    assert row["quantity"] == row["available_quantity"] == 151.8
    assert "cost_per_unit" not in row
    body = {"date": "2026-11-06T00:00:00Z", "passport_no": "ECT-ADD-TRANSFER",
        "production_order_id": order["id"], "pieces": 10,
        "materials": [{"stock_batch_id": row["id"], "planned_kg": 6.5, "pieces": 10} for row in [stocks[1], stocks[0]]],
        "additional_materials": [{"stock_batch_id": stocks[0]["id"], "estimated_quantity": 6.5, "unit": "kg"}]}
    rejected = client.post("/api/cutting-passports", headers=cutting_headers, json={**body,
        "additional_materials": [{**body["additional_materials"][0], "estimated_quantity": 152}]})
    assert rejected.status_code == 409, rejected.text
    result = client.post("/api/cutting-passports", headers=cutting_headers, json=body)
    assert result.status_code == 201, result.text
    with SessionLocal() as db:
        assert db.query(ProductionOrderMaterial).filter_by(production_order_id=order["id"], stock_batch_id=stocks[0]["id"]).one()
        assert db.query(MaterialReservation).filter_by(production_order_id=order["id"], stock_batch_id=stocks[0]["id"]).count() == 0
        assert [db.get(EcoMaterialBatch, key).quantity for key in eco_ids] == [5, Decimal("146.8")]
        assert db.get(StockBatch, stocks[0]["id"]).quantity == 0


def test_milana_and_unlinked_ect_stock_keep_central_ledger(client, auth_headers, passport_cutting):
    stocks, order, work, payload = passport_cutting
    # An unrelated direct ECO receipt has no inferred relationship to Milana.
    with SessionLocal() as db:
        actor = db.query(User).filter_by(email="admin@example.com").one()
        source = db.get(StockBatch, stocks[0]["id"])
        db.add(EcoMaterialBatch(item_id=source.item_id, kind="fabric", batch_no=source.batch_no,
            unit="kg", quantity=123, reserved_quantity=0, created_by=actor.id))
        db.get(WorkOrder, work["id"]).department_id = db.query(Department.id).filter_by(code="ECT").scalar()
        db.commit()
        headers = {"Authorization": f"Bearer {create_access_token(actor.id, extra={'factory_code': 'ECO'})}"}
    result = client.post("/api/cutting/records", headers=headers, json=payload)
    assert result.status_code == 201, result.text
    with SessionLocal() as db:
        assert [db.get(StockBatch, row["id"]).quantity for row in stocks] == [Decimal("93.5"), Decimal("93.5")]
        assert db.query(EcoMaterialBatch).one().quantity == 123
        assert db.query(EcoMaterialMovement).count() == 0


def test_old_central_consumption_keeps_own_credit_after_later_transfer(client, auth_headers, passport_cutting):
    stocks, _, work, payload = passport_cutting
    cut = client.post("/api/cutting/records", headers=auth_headers, json=payload)
    assert cut.status_code == 201, cut.text
    with SessionLocal() as db:
        actor = db.query(User).filter_by(email="admin@example.com").one()
        source = db.get(StockBatch, stocks[0]["id"])
        source.quantity = 0
        source.archived_at = datetime.now(timezone.utc)
        db.get(WorkOrder, work["id"]).department_id = db.query(Department.id).filter_by(code="ECT").scalar()
        db.add(EcoMaterialBatch(item_id=source.item_id, kind="fabric", batch_no=source.batch_no,
            unit=source.unit, quantity=0, reserved_quantity=0, source_stock_batch_id=source.id, created_by=actor.id))
        db.commit()
        headers = {"Authorization": f"Bearer {create_access_token(actor.id, extra={'factory_code': 'ECO'})}"}
    url = f"/api/cutting-passports/{payload['cutting_passport_id']}"
    saved = client.get(url, headers=headers).json()
    updated = client.patch(url, headers=headers, json={**saved, "notes": "Historical central debit"})
    assert updated.status_code == 200, updated.text
    with SessionLocal() as db:
        assert db.query(EcoMaterialMovement).count() == 0
        assert db.get(StockBatch, stocks[0]["id"]).quantity == 0
