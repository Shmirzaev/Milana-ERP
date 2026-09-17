"""Destructive QA only for an empty, explicitly named loopback PostgreSQL test DB.
Run with ECO_QA_DATABASE_URL pointing to a disposable erp_qa database.
"""
import os
from pathlib import Path
import importlib.util
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException

url = make_url(os.environ["ECO_QA_DATABASE_URL"])
assert url.host in ("localhost", "127.0.0.1") and url.database == "erp_qa"
os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)
from app.db.base import Base
from app.models import (User, Role, Item, Warehouse, StockBatch, EcoFabricDispatch, EcoFabricRoll,
    StockMovement, Department, Model, ProductionOrder, WorkOrder, SewingFlow, SewingAssignment, SewingRecord)
from app.api.routes.eco_transfers import send, receive, SendIn, ReturnIn
from app.api.routes.sewing_corrections import update, Correction
from app.core.deps import user_permissions

engine = create_engine(url)
assert not inspect(engine).get_table_names(), "QA database must be empty"
Base.metadata.create_all(engine)
Session = sessionmaker(engine, expire_on_commit=False)
with Session() as db:
    role = Role(name="QA", permissions=["storage.items", "inventory.materials_only"])
    mubina = User(name="QA Mubina", email="mubina@milanapremium.uz", password_hash="unused", role=role,
        access_policy={"MIL": {"allow": ["storage.items"], "deny": ["storage.accessories"]}})
    other = User(name="Other", email="other@example.test", password_hash="unused", role=role)
    db.add_all([mubina, other]); db.commit()
    user_id, other_id = mubina.id, other.id
# Reconstruct only the immediately preceding schema, then apply the real migrations.
with engine.begin() as connection:
    connection.execute(text("DROP TABLE eco_fabric_rolls"))
    connection.execute(text("DROP TABLE eco_fabric_dispatches"))
    for column in ["sewing_assignment_id", "assignment_applied_qty", "correction_version"]:
        connection.execute(text(f"ALTER TABLE sewing_records DROP COLUMN {column}"))
    with Operations.context(MigrationContext.configure(connection)):
        for filename in ["0130_eco_fabric_transfers.py", "0131_sewing_corrections.py"]:
            spec = importlib.util.spec_from_file_location("qa_migration", Path(__file__).parents[1]/"alembic/versions"/filename)
            module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
            module.upgrade()
with Session() as db:
    user = db.get(User, user_id)
    assert "inventory.eco_transfers" in user_permissions(user)
    assert "inventory.materials_only" in user_permissions(user)
    assert user.access_policy["MIL"]["deny"] == ["storage.accessories"]
    assert "inventory.eco_transfers" not in user_permissions(db.get(User, other_id))
    item = Item(sku="QA-FABRIC", name="QA Fabric", category="fabric", unit="kg")
    warehouse = Warehouse(name="QA", type="materials")
    db.add_all([item, warehouse]); db.flush()
    batch = StockBatch(item_id=item.id, warehouse_id=warehouse.id, batch_no="QA-ROLLS", quantity=30,
                       unit="kg", piece_count=2, roll_weights_kg=[10,20])
    db.add(batch); db.commit(); batch_id = batch.id


def simultaneous(function):
    barrier = Barrier(2)
    def call(_):
        with Session() as db:
            user = db.get(User, user_id)
            barrier.wait()
            try: return function(db, user)
            except HTTPException as error:
                db.rollback(); return error.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        return list(pool.map(call, range(2)))

key = uuid4()
results = simultaneous(lambda db, user: send(SendIn(request_key=key, codes=[f"B{batch_id}-R1"]), db, user))
assert all(isinstance(r, dict) for r in results) and results[0]["id"] == results[1]["id"]
dispatch_id = results[0]["id"]
with Session() as db:
    assert db.get(StockBatch,batch_id).quantity == 20
    assert db.query(EcoFabricDispatch).count() == 1
    assert db.query(StockMovement).count() == 1
results = simultaneous(lambda db,user: receive(ReturnIn(code=f"B{batch_id}-R1", dispatch_id=dispatch_id, request_key=uuid4()), db,user))
assert sum(isinstance(r,dict) for r in results) == 1 and 409 in results
with Session() as db:
    assert db.get(StockBatch,batch_id).quantity == 30
    assert db.query(StockMovement).count() == 2
    assert db.query(EcoFabricRoll).filter_by(returned_at=None).count() == 0
    department = Department(code="SEW", name="QA Sewing")
    model = Model(code="QA-MODEL", name="QA Model")
    flow = SewingFlow(code="QA-LINE", name="QA Line", factory_code="MIL")
    db.add_all([department, model, flow]); db.flush()
    po = ProductionOrder(production_no="QA-ORDER", production_type="branded_stock", model_id=model.id, planned_quantity=100)
    db.add(po); db.flush()
    wo = WorkOrder(production_order_id=po.id, department_id=department.id, operation="sewing", status="in_progress",
        actual_input_qty=100, actual_output_qty=80, passed_qty=80, planned_output_qty=100)
    db.add(wo); db.flush()
    assignment = SewingAssignment(work_order_id=wo.id, sewing_flow_id=flow.id, quantity=100, completed_qty=80, status="in_progress")
    db.add(assignment); db.flush()
    row = SewingRecord(work_order_id=wo.id, sewing_assignment_id=assignment.id, assignment_applied_qty=80,
        input_qty=100, sewn_qty=80, passed_qty=80, line_name=flow.name)
    db.add(row); db.commit(); rid, wid, aid = row.id, wo.id, assignment.id
results = simultaneous(lambda db,user: update(rid, Correction(expected_version=0,input_qty=90,sewn_qty=60,passed_qty=60), db,user))
assert sum(isinstance(r,dict) for r in results) == 1 and 409 in results
with Session() as db:
    assert db.get(WorkOrder,wid).passed_qty == 60
    assert db.get(SewingAssignment,aid).completed_qty == 60
print("PASS: both real PostgreSQL migrations, isolated Mubina grant, duplicate-send race, duplicate-return race, stale sewing edit race")
