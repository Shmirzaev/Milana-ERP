"""Actual inventory auto route against the approved disposable PostgreSQL target."""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token
from app.db.session import get_db
from app.main import app
from app.schemas import AuditLog, Item, MaterialReservation, Model, ModelBOM, ProductionOrder, Role, StockBatch, User, Warehouse
from app.tests.test_stock_movement_and_reservation_postgres import pg, pg_engine  # noqa: F401


@pytest.mark.parametrize("mode, expected", [
    ("full_remaining", {"short", "covered"}),
    ("shortage_only", {"short"}),
    (None, {"short", "covered"}),
])
def test_inventory_auto_route_persists_selected_bom_lines_and_audit(pg, mode, expected):
    marker = uuid4().hex[:10]
    with pg() as db:
        role = Role(name=f"Auto QA {marker}", permissions=["*"])
        model = Model(code=f"AUTO-{marker}", name="Auto QA", status="approved")
        warehouse = Warehouse(name=f"Auto QA {marker}", type="fabric_storage")
        items = {name: Item(sku=f"AUTO-{marker}-{name}", name=name, category="fabric", unit="kg")
                 for name in ("short", "covered", "control")}
        db.add_all([role, model, warehouse, *items.values()])
        db.flush()
        user = User(name="Auto QA", email=f"auto-{marker}@example.test", password_hash="unused", role_id=role.id)
        order = ProductionOrder(production_no=f"AUTO-{marker}", production_type="branded_stock",
                                model_id=model.id, planned_quantity=10)
        db.add_all([user, order])
        db.flush()
        for name, quantity in (("short", 5), ("covered", 10), ("control", 7)):
            db.add(StockBatch(item_id=items[name].id, warehouse_id=warehouse.id,
                              batch_no=f"AUTO-{marker}-{name}", quantity=quantity, unit="kg", qc_status="passed"))
            if name != "control":
                db.add(ModelBOM(model_id=model.id, item_id=items[name].id,
                                quantity_per_piece=1, unit="kg", waste_percent=0))
        db.commit()
        user_id, order_id = user.id, order.id
        item_ids = {name: item.id for name, item in items.items()}

    def override_db():
        with pg() as db:
            yield db

    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_db
    try:
        headers = {"Authorization": f"Bearer {create_access_token(user_id)}"}
        payload = {"production_order_id": order_id, "reserve_materials": True,
                   "reserve_accessories": False, "reserve_packaging": False}
        if mode is not None:
            payload["mode"] = mode
        client = TestClient(app)
        denied = client.post("/api/inventory/reservations/auto", json=payload)
        assert denied.status_code == 401, denied.text
        with pg() as db:
            assert db.query(MaterialReservation).filter_by(production_order_id=order_id).count() == 0
            assert db.query(AuditLog).filter_by(entity_type="ProductionOrder", entity_id=order_id,
                                                   action="auto_reserve_materials").count() == 0
        response = client.post("/api/inventory/reservations/auto", headers=headers, json=payload)
        assert response.status_code == 201, response.text
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous

    with pg() as db:
        rows = db.query(MaterialReservation).filter_by(production_order_id=order_id).all()
        assert len(rows) == len(expected)
        assert {row.item_id for row in rows} == {item_ids[name] for name in expected}
        assert {row.item_id: float(row.reserved_quantity) for row in rows} == {
            item_ids[name]: 5 if name == "short" else 10 for name in expected
        }
        assert all(row.source == "auto_bom" for row in rows)
        assert response.json()["created_count"] == len(rows)
        audit = db.query(AuditLog).filter_by(entity_type="ProductionOrder", entity_id=order_id,
                                              action="auto_reserve_materials").one()
        assert audit.user_id == user_id
        assert audit.new_value_json["mode"] == (mode or "full_remaining")
        assert audit.new_value_json["created_count"] == len(rows)
        assert set(audit.new_value_json["reservation_ids"]) == {row.id for row in rows}
        control = db.query(StockBatch).filter_by(item_id=item_ids["control"]).one()
        assert float(control.quantity) == 7
        assert db.query(MaterialReservation).filter_by(item_id=item_ids["control"]).count() == 0
