from uuid import uuid4

from sqlalchemy import event

from app.models import Item, StockBatch, Supplier, Warehouse
from app.tests.conftest import TestSessionLocal, test_engine


def test_inventory_batch_list_projects_joined_master_data(client, auth_headers):
    marker = uuid4().hex[:10]
    image_url = f"/storage/inventory/{marker}.webp"
    with TestSessionLocal() as db:
        item = Item(
            sku=f"BATCH-PROJ-{marker}",
            name="Projected accessory",
            category="accessory",
            unit="pcs",
            image_url=image_url,
        )
        supplier = Supplier(name=f"Projected supplier {marker}")
        warehouse = Warehouse(name=f"Projected warehouse {marker}", type="accessory_storage")
        db.add_all([item, supplier, warehouse])
        db.flush()
        batch = StockBatch(
            item_id=item.id,
            batch_no=f"BATCH-{marker}",
            supplier_id=supplier.id,
            quantity=12,
            unit="pcs",
            warehouse_id=warehouse.id,
        )
        db.add(batch)
        db.commit()

    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(test_engine, "before_cursor_execute", capture)
    try:
        response = client.get(
            "/api/inventory/batches",
            params={"group": "accessories", "q": marker},
            headers=auth_headers,
        )
    finally:
        event.remove(test_engine, "before_cursor_execute", capture)

    assert response.status_code == 200, response.text
    row = response.json()[0]
    assert row["item_sku"] == f"BATCH-PROJ-{marker}"
    assert row["item_name"] == "Projected accessory"
    assert row["supplier_name"] == f"Projected supplier {marker}"
    assert row["warehouse_name"] == f"Projected warehouse {marker}"
    batch_query = next(statement for statement in statements if " from stock_batches " in statement)
    assert "items.sku" in batch_query and "items.name" in batch_query
    assert "warehouses.name" in batch_query and "suppliers.name" in batch_query
    assert "items.composition_json" not in batch_query
    assert "items.image_url" not in batch_query
    assert "suppliers.address" not in batch_query
    assert "warehouses.department_id" not in batch_query
