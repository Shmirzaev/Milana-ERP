"""Real migration and racing allocations; only an explicitly disposable local DB."""
import importlib.util
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from sqlalchemy import text
from app.db.base import Base
from app.db.session import engine, SessionLocal
from app.db.seed import seed
from app.models import Department, FinishedGoodsStock, Model, Package, PackagingRecord, ProductionOrder, ProductionOrderItem, SewingRecord, WorkOrder
from app.services.packages import create_package

assert os.environ.get("FIRST_GRADE_DISPOSABLE") == "1"
assert engine.url.host in {"127.0.0.1", "localhost"} and engine.url.database.startswith("first_grade_qa_")
assert engine.dialect.name == "postgresql"
with engine.connect() as conn:
    assert conn.execute(text("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")).scalar() == 0
Base.metadata.create_all(engine)
seed()
path = Path(__file__).resolve().parents[1] / "backend/alembic/versions/0132_first_grade_singles.py"
spec = importlib.util.spec_from_file_location("migration", path)
migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
with engine.begin() as conn:
    conn.execute(text("ALTER TABLE packages DROP CONSTRAINT ck_packages_single_quantity"))
    conn.execute(text("ALTER TABLE packages DROP CONSTRAINT ck_packages_stock_kind"))
    conn.execute(text("ALTER TABLE packages DROP COLUMN stock_kind"))
    conn.execute(text("ALTER TABLE shipments DROP COLUMN deleted_at"))
    migration.op = Operations(MigrationContext.configure(conn))
    migration.upgrade(); migration.downgrade(); migration.upgrade()

with SessionLocal() as db:
    model = db.query(Model).filter_by(code="T-SHIRT-001").one()
    po = ProductionOrder(production_no="PO-PG-SINGLE", production_type="branded_stock", model_id=model.id, planned_quantity=3)
    db.add(po); db.flush()
    for size, quantity in [("S", 1), ("M", 2)]:
        db.add(ProductionOrderItem(production_order_id=po.id, model_id=model.id, color="White", size=size, planned_quantity=quantity))
    sew = WorkOrder(production_order_id=po.id, department_id=db.query(Department.id).filter_by(code="SEW").scalar(), operation="sewing", passed_qty=3)
    pkg = WorkOrder(production_order_id=po.id, department_id=db.query(Department.id).filter_by(code="PKG").scalar(), operation="packaging", passed_qty=3)
    db.add_all([sew, pkg]); db.flush()
    db.add(SewingRecord(work_order_id=sew.id, input_qty=3, sewn_qty=3, passed_qty=3, size_quantities=[{"size": "S", "quantity": 1}, {"size": "M", "quantity": 2}]))
    db.add(PackagingRecord(work_order_id=pkg.id, input_qty=3, packed_qty=3))
    db.commit(); poid = po.id; mid = model.id

barrier = Barrier(2)
def allocate():
    with SessionLocal() as db:
        barrier.wait(timeout=10)
        try:
            package = create_package(db, production_order_id=poid, model_id=mid, color="White", capacity=1,
                stock_kind="first_grade", items=[{"model_id": mid, "color": "White", "size": "S", "quantity": 1}])
            db.commit()
            return "created", package.id
        except HTTPException as exc:
            db.rollback()
            return "rejected", exc.detail

with ThreadPoolExecutor(max_workers=2) as pool:
    results = list(pool.map(lambda _: allocate(), range(2)))
assert sorted(result[0] for result in results) == ["created", "rejected"], results
assert ("rejected", "FIRST_GRADE_SIZE_EXCEEDED") in results, results
with SessionLocal() as db:
    assert db.query(Package).filter_by(stock_kind="first_grade").count() == 1
    assert sum(row.quantity for row in db.query(FinishedGoodsStock).filter_by(production_order_id=poid)) == 1
try:
    with engine.begin() as conn:
        migration.op = Operations(MigrationContext.configure(conn)); migration.downgrade()
except RuntimeError as exc:
    assert "reconciled" in str(exc)
else:
    raise AssertionError("Downgrade must not erase live First Grade classification")
print("PostgreSQL migration up/down/up, concurrent exact-size allocation, stock conservation and downgrade guard passed.")
