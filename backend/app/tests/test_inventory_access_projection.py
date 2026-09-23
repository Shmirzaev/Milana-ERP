from uuid import uuid4

from sqlalchemy import event

from app.models import Item, MaterialReservation, Model, ProductionOrder, StockBatch, User, Warehouse
from app.services.inventory_access import require_batch, require_item, require_reservation
from app.tests.conftest import TestSessionLocal


def test_material_access_checks_select_only_fields_needed_for_scope():
    marker = uuid4().hex[:10]
    with TestSessionLocal() as db:
        item = Item(
            sku=f"SCOPE-{marker}", name=f"Scope material {marker}", category="fabric",
            unit="kg", default_cost=0, reorder_level=0,
        )
        warehouse = Warehouse(name=f"Scope warehouse {marker}", type="fabric_storage")
        user = User(
            name=f"Scope user {marker}", email=f"scope-{marker}@example.com",
            password_hash="unused", extra_permissions=["inventory.materials_only"],
        )
        db.add_all([item, warehouse, user])
        db.flush()
        batch = StockBatch(
            item_id=item.id, warehouse_id=warehouse.id, batch_no=f"SCOPE-{marker}",
            quantity=1, unit="kg", qc_status="passed",
        )
        db.add(batch)
        db.commit()
        item_id = int(item.id)
        batch_id = int(batch.id)
        user_id = int(user.id)

    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().lower().startswith("select"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(TestSessionLocal.kw["bind"], "before_cursor_execute", capture)
    try:
        with TestSessionLocal() as db:
            user = db.get(User, user_id)
            require_item(db, user, item_id)
            require_batch(db, user, batch_id)
    finally:
        event.remove(TestSessionLocal.kw["bind"], "before_cursor_execute", capture)

    item_selects = [sql for sql in statements if " from items " in sql and "stock_batches" not in sql]
    batch_selects = [sql for sql in statements if " from stock_batches " in sql]
    assert len(item_selects) == 1, statements
    assert "select items.category as items_category" in item_selects[0], item_selects
    assert len(batch_selects) == 1, statements
    assert "select stock_batches.item_id" in batch_selects[0]
    assert "items.category" in batch_selects[0]


def test_reservation_scope_check_loads_only_reference_ids():
    marker = uuid4().hex[:10]
    with TestSessionLocal() as db:
        item = db.query(Item).filter_by(category="fabric").first()
        warehouse = db.query(Warehouse).first()
        batch = StockBatch(
            item_id=item.id,
            warehouse_id=warehouse.id,
            batch_no=f"RES-SCOPE-{marker}",
            quantity=1,
            unit="kg",
            qc_status="passed",
        )
        user = User(
            name=f"Reservation scope user {marker}",
            email=f"reservation-scope-{marker}@example.com",
            password_hash="unused",
            extra_permissions=["inventory.materials_only"],
        )
        db.add_all([batch, user])
        db.flush()
        order = ProductionOrder(
            production_no=f"RES-SCOPE-PO-{marker}",
            production_type="branded_stock",
            model_id=db.query(Model.id).first()[0],
            planned_quantity=1,
        )
        db.add(order)
        db.flush()
        reservation = MaterialReservation(
            reservation_no=f"RES-SCOPE-{marker}",
            production_order_id=order.id,
            item_id=item.id,
            stock_batch_id=batch.id,
            warehouse_id=warehouse.id,
            reserved_quantity=1,
            unit="kg",
            status="reserved",
            reservation_type="material",
            source="manual",
        )
        db.add(reservation)
        db.commit()
        reservation_id = int(reservation.id)
        user_id = int(user.id)

    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().lower().startswith("select"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(TestSessionLocal.kw["bind"], "before_cursor_execute", capture)
    try:
        with TestSessionLocal() as db:
            require_reservation(db, db.get(User, user_id), reservation_id)
    finally:
        event.remove(TestSessionLocal.kw["bind"], "before_cursor_execute", capture)

    reservation_reads = [sql for sql in statements if " from material_reservations " in sql]
    assert len(reservation_reads) == 1, statements
    selected_columns = reservation_reads[0].split(" from material_reservations ", maxsplit=1)[0]
    assert "material_reservations.id" in selected_columns
    assert "material_reservations.item_id" in selected_columns
    assert "material_reservations.stock_batch_id" in selected_columns
    assert "reserved_quantity" not in selected_columns
    assert " join " not in reservation_reads[0]
