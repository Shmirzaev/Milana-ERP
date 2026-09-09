from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models import (
    AuditLog, BusinessOrderAlias, CuttingMaterialUsage, CuttingPassport, CuttingRecord,
    Department, Item, MaterialReservation, Model, ProductionOrder, ProductionOrderItem,
    Role, StockBatch, StockMovement, User, Warehouse, WorkOrder,
)
from app.services.cutting_fabric_usage import cutting_fabric_usage
from app.services.inventory import consume_material_reservations_for_stock_batch
from app.services.workflow import consume_stock_batch

URL = "/api/inventory/cutting-fabric-usage"


def _headers(permissions, factory="MIL"):
    with SessionLocal() as db:
        token = uuid4().hex
        role = Role(name=f"Fabric report {token}", permissions=permissions)
        db.add(role)
        db.flush()
        user = User(name="Fabric report reader", email=f"fabric-{token}@example.com", password_hash="unused-test-password-hash", role_id=role.id, factory_code=factory, is_active=True)
        db.add(user)
        db.commit()
        return {"Authorization": f"Bearer {create_access_token(user.id, extra={'factory_code': factory})}"}


@pytest.fixture
def usage():
    with SessionLocal() as db:
        key = "CFU-" + uuid4().hex[:8]
        model = Model(code=key, name="Cutting usage fixture")
        warehouse = Warehouse(name=key, type="fabric_storage")
        db.add_all([model, warehouse])
        db.flush()
        items = []
        batches = []
        for category, unit in (("fabric", "kg"), ("semi_finished", "m"), ("accessory", "pcs")):
            item = Item(sku=f"{key}-{category}", name=f"{key} {category}", category=category, unit=unit)
            db.add(item)
            db.flush()
            batch = StockBatch(item_id=item.id, batch_no=f"{key}-{unit}", warehouse_id=warehouse.id, quantity=100, unit=unit, color="Blue", qc_status="passed")
            db.add(batch)
            db.flush()
            items.append(item)
            batches.append(batch)
        records = []
        orders = []
        for index, department in enumerate(("CUT", "CUT", "ECT", "CUT")):
            po = ProductionOrder(production_no=f"{key}-PO-{index}", production_type="branded_stock", model_id=model.id, status="cutting", planned_quantity=100)
            db.add(po)
            db.flush()
            wo = WorkOrder(production_order_id=po.id, department_id=db.query(Department.id).filter(Department.code == department).scalar(), operation="cutting", status="in_progress")
            db.add(wo)
            db.flush()
            record = CuttingRecord(work_order_id=wo.id, fabric_batch_id=batches[0].id, input_quantity=999, input_unit="kg", cut_pieces=100,
                                   approval_status="pending" if index == 3 else "approved",
                                   created_at=datetime(2026, 9, 9, 18 if index == 0 else 19, 59 if index == 0 else 0, 59 if index == 0 else 0, tzinfo=timezone.utc))
            db.add(record)
            db.flush()
            # Multiple size rows must never multiply a ledger consumption.
            for size in ("48", "50"):
                db.add(ProductionOrderItem(production_order_id=po.id, model_id=model.id, color="Blue", size=size, planned_quantity=50))
            orders.append(po)
            records.append(record)
        reservation = MaterialReservation(reservation_no=key, production_order_id=orders[0].id, item_id=items[0].id,
                                          stock_batch_id=batches[0].id, warehouse_id=warehouse.id, reserved_quantity=20,
                                          consumed_quantity=0, released_quantity=0, unit="kg", status="reserved", reservation_type="material", source="manual")
        db.add(reservation)
        db.flush()
        consume_material_reservations_for_stock_batch(db, production_order_id=orders[0].id, stock_batch_id=batches[0].id,
                                                     quantity=2, reference_type="CuttingRecord", reference_id=records[0].id, user_id=None)
        consume_stock_batch(db, batch_id=batches[0].id, quantity=3, unit="kg", reference_type="CuttingRecord", reference_id=records[0].id, user_id=None)
        consume_stock_batch(db, batch_id=batches[1].id, quantity=7, unit="m", reference_type="CuttingRecord", reference_id=records[1].id, user_id=None)
        # Accessory, other factory and unapproved cutting are not fabric usage here.
        for rec, batch, amount in ((records[0], batches[2], 8), (records[2], batches[0], 12), (records[3], batches[0], 20)):
            consume_stock_batch(db, batch_id=batch.id, quantity=amount, unit=batch.unit, reference_type="CuttingRecord", reference_id=rec.id, user_id=None)
        db.add_all([
            CuttingMaterialUsage(cutting_record_id=records[0].id, stock_batch_id=batches[0].id, quantity=99, unit="kg", position=1),
            CuttingPassport(passport_no=key, date=datetime(2026, 9, 9, tzinfo=timezone.utc), production_order_id=orders[0].id, planned_kg=1000),
            StockMovement(movement_type="issue", item_id=items[0].id, batch_id=batches[0].id, quantity=30, unit="kg", reference_type="CuttingRecord", reference_id=records[0].id),
            StockMovement(movement_type="consume", item_id=items[0].id, batch_id=batches[0].id, quantity=40, unit="kg", reference_type="MaterialReservation", reference_id=reservation.id),
            StockMovement(movement_type="consume", item_id=items[0].id, batch_id=batches[0].id, quantity=1, unit="kg", reference_type="CuttingRecord", reference_id=99999999),
        ])
        # A depleted/archived batch is still part of historical actual usage.
        batches[1].quantity = 0
        batches[1].archived_at = datetime(2026, 9, 10, tzinfo=timezone.utc)
        db.commit()
        return {"key": key, "records": [r.id for r in records], "orders": [o.id for o in orders],
                "items": [i.id for i in items], "batches": [b.id for b in batches]}


def test_reports_actual_consumption_once_and_keeps_totals_across_pages(client, usage):
    headers = _headers(["storage.items", "inventory.materials_only"])
    with SessionLocal() as db:
        before = ([(r.id, r.quantity) for r in db.query(StockBatch).order_by(StockBatch.id)], db.query(StockMovement).count(), db.query(AuditLog).count())
    response = client.get(URL, params={"q": usage["key"], "page_size": 1}, headers=headers)
    assert response.status_code == 200, response.text
    first = response.json()
    second = client.get(URL, params={"q": usage["key"], "page_size": 1, "page": 2}, headers=headers).json()
    assert first["total"] == second["total"] == 2
    assert first["totals"] == second["totals"] == [{"unit": "kg", "quantity": 5}, {"unit": "m", "quantity": 7}]
    assert first["rows"][0]["cutting_record_id"] == usage["records"][1]
    fabric = second["rows"][0]
    assert fabric["quantity"] == 5 and fabric["movement_count"] == 2
    assert fabric["evidence"] == "stock_consumption" and fabric["model_code"] == usage["key"]
    assert fabric["id"] != first["rows"][0]["id"]
    with SessionLocal() as db:
        after = ([(r.id, r.quantity) for r in db.query(StockBatch).order_by(StockBatch.id)], db.query(StockMovement).count(), db.query(AuditLog).count())
    assert after == before


def test_tashkent_date_boundaries_and_material_filters(client, usage):
    headers = _headers(["storage.receive"])
    response = client.get(URL, params={"q": usage["key"], "date_from": "2026-09-09", "date_to": "2026-09-09"}, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["totals"] == [{"unit": "kg", "quantity": 5}]
    next_day = client.get(URL, params={"q": usage["key"], "date_from": "2026-09-10", "date_to": "2026-09-10", "batch_id": usage["batches"][1]}, headers=headers).json()
    assert next_day["total"] == 1 and next_day["totals"] == [{"unit": "m", "quantity": 7}]
    accessory = client.get(URL, params={"item_id": usage["items"][2]}, headers=headers).json()
    assert accessory["rows"] == [] and accessory["totals"] == []
    assert client.get(URL, params={"date_from": "2026-09-10", "date_to": "2026-09-09"}, headers=headers).status_code == 400


def test_read_permission_and_factory_scope_are_authoritative(client, usage):
    assert client.get(URL, params={"q": usage["key"]}).status_code == 401
    assert client.get(URL, headers=_headers(["inventory.materials_only"])).status_code == 403
    assert client.get(URL, headers=_headers(["sales.orders"])).status_code == 403
    mil = _headers(["cutting.records"])
    assert client.get(URL, params={"cutting_department": "ECT"}, headers=mil).status_code == 403
    eco = client.get(URL, params={"q": usage["key"]}, headers=_headers(["planning.production"], "ECO"))
    assert eco.status_code == 200, eco.text
    assert eco.json()["cutting_department"] == "ECT" and eco.json()["totals"] == [{"unit": "kg", "quantity": 12}]
    assert client.get(URL, headers=_headers(["storage.items"], "BST")).status_code == 403


def test_historical_order_alias_search_returns_current_order(client, usage):
    with SessionLocal() as db:
        po = db.get(ProductionOrder, usage["orders"][0])
        po.production_no = "PO-0909"
        db.add(BusinessOrderAlias(namespace="PO", entity_id=po.id, reference="PO-2026-000909", canonical_reference="PO-0909"))
        db.commit()
    response = client.get(URL, params={"q": "PO-2026-000909"}, headers=_headers(["storage.items"]))
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1
    assert response.json()["rows"][0]["order_no"] == "PO-0909"


def test_report_uses_bounded_projection_queries_without_relationship_loading(usage):
    with SessionLocal() as db:
        user = User(factory_code="MIL")
        statements = []

        def capture(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            result = cutting_fabric_usage(db, user, q=usage["key"], page_size=200)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
        assert result["total"] == 2
        assert len(statements) == 3
        assert all(statement.lstrip().upper().startswith("SELECT") for statement in statements)
        assert not any("JOIN production_order_items" in statement or "JOIN bundles" in statement for statement in statements)
