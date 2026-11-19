"""Actual PostgreSQL precision, paging and read-only receipt projection."""
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import text

from app.models.inventory.stock_service import list_batches
from app.schemas import Item, Role, StockBatch, StockMovement, User, Warehouse
from app.tests.test_modelsize_create_postgres import pg_sessions as pg_sessions


def test_pg_received_projection_precision_paging_and_read_only(pg_sessions):
    suffix = uuid4().hex[:10]
    with pg_sessions.begin() as db:
        role = Role(name=f"Receipt QA {suffix}", permissions=["*"])
        warehouse = Warehouse(name=f"Receipt QA {suffix}", type="fabric_storage")
        item = Item(sku=f"RQ-{suffix}", name=f"Receipt {suffix}", category="fabric", unit="kg", default_cost=1)
        db.add_all([role, warehouse, item]); db.flush()
        actor = User(name="Receipt QA", email=f"rq-{suffix}@example.invalid", password_hash="unused",
                     role_id=role.id, factory_code="MIL", is_active=True)
        db.add(actor); db.flush()
        for index in range(3):
            batch = StockBatch(item_id=item.id, warehouse_id=warehouse.id, batch_no=f"RQ-{suffix}-{index}",
                               quantity=Decimal("0.125"), unit="kg", cost_per_unit=1)
            db.add(batch); db.flush()
            for kind, qty in [("receive", "0.1234"), ("receive", "0.0001"), ("return", "8"), ("adjustment", "6")]:
                db.add(StockMovement(item_id=item.id, batch_id=batch.id, movement_type=kind, quantity=Decimal(qty), unit="kg"))
        actor_id, item_id = actor.id, item.id
    with pg_sessions() as db:
        db.execute(text("SET TRANSACTION READ ONLY"))
        actor = db.get(User, actor_id)
        for page in (1, 2):
            result = list_batches(db, actor, item_id=item_id, group="materials", page=page, page_size=2, include_total=True)
            assert result["total"] == 3
            assert len(result["rows"]) == (2 if page == 1 else 1)
            assert all(row["received_quantity"] == 0.1235 for row in result["rows"])
            assert all(row["quantity"] == Decimal("0.125") for row in result["rows"])
        assert not db.new and not db.dirty and not db.deleted
