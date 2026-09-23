from uuid import uuid4

from sqlalchemy import event

from app.models import Item, StockBatch, User, Warehouse
from app.services.inventory_access import require_batch, require_item
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
