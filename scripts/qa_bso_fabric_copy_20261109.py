"""Loopback-only synthetic candidate QA; never uses production credentials/data."""
import json
import os
from pathlib import Path
import secrets
import sys

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".qa-bso-fabric-copy"
STATE.mkdir(exist_ok=True)
os.environ.update({
    "ENV": "development", "DATABASE_URL": f"sqlite:///{(STATE / 'qa.db').as_posix()}",
    "SHARED_STORE_URL": f"sqlite:///{(STATE / 'counters.db').as_posix()}",
    "JWT_SECRET": secrets.token_urlsafe(48), "FILE_SIGNING_SECRET": secrets.token_urlsafe(48),
    # Deliberately synthetic, local-only fixture account, as in app/tests/conftest.py.
    "INITIAL_ADMIN_EMAIL": "admin@example.com", "INITIAL_ADMIN_PASSWORD": "test-admin-password-123!",
    "SEED_SAMPLE_DATA": "true", "SEED_DEMO_USERS": "false", "IMPORT_LEGACY_MODELS": "false",
    "RUN_SEED_ON_STARTUP": "false", "STARTUP_SCHEMA_SYNC": "false",
    "CORS_ORIGINS": "http://127.0.0.1:13109", "FRONTEND_BASE_URL": "http://127.0.0.1:13109",
    **{name: str(STATE / folder) for name, folder in {
        "BARCODE_STORAGE_DIR": "barcodes", "MODEL_FILES_DIR": "models", "SALES_ORDER_FILES_DIR": "sales",
        "ATTENDANCE_PHOTOS_DIR": "attendance", "HR_DOCUMENTS_DIR": "hr", "TURNSTILE_PHOTOS_DIR": "turnstile",
    }.items()},
})
sys.path.insert(0, str(ROOT / "backend"))


def init():
    if (STATE / "qa.db").exists():
        raise SystemExit("Owned fixture already exists; retained without overwriting")
    from app.db.base import Base
    from app.db.session import engine, SessionLocal
    from app.db.seed import seed
    from app.schemas import Model, Item, Warehouse, StockBatch, StockMovement, Department, BrandedPlanningOrder, ProductionOrder, WorkOrder
    Base.metadata.create_all(engine)
    seed(ensure_schema=False)
    with SessionLocal() as db:
        source = Model(code="QA9001", name="QA Copy source", details_json={"paid_operations": [
            {"id": f"qa-{factory}", "name": f"QA {factory} operation", "code": "QA-OP", "section": "sewing",
             "rate": str(rate), "selected": True, "sewingFactory": factory, "quantityMode": "batch",
             "customQuantity": 0, "copies": 1, "splitMode": "none", "splitQuantities": []}
            for factory, rate in [("milana", 123), ("besttex", 456), ("eco_cotton", 789)]
        ]})
        target = Model(code="QA9002", name="QA Copy target", details_json={"paid_operations": [], "general": {"full_name": "Target details retained"}})
        db.add_all([source, target]); db.flush()
        item = Item(sku="QA-FABRIC", name="QA Receipt fabric", category="fabric", unit="kg", default_cost=2, track_batch=True)
        db.add(item); db.flush()
        warehouse = db.query(Warehouse).first()
        batch = StockBatch(item_id=item.id, batch_no="QA-RECEIVED-100", quantity=60, unit="kg", cost_per_unit=2, warehouse_id=warehouse.id)
        db.add(batch); db.flush()
        db.add(StockMovement(movement_type="receive", item_id=item.id, batch_id=batch.id, quantity=100, unit="kg", to_warehouse_id=warehouse.id))
        db.add(StockMovement(movement_type="consume", item_id=item.id, batch_id=batch.id, quantity=40, unit="kg", from_warehouse_id=warehouse.id))
        order = BrandedPlanningOrder(order_no="BSO-QA", ordered_for_type="milana", ordered_for_name="QA Milana")
        db.add(order); db.flush()
        production = ProductionOrder(production_no="PO-QA", production_type="branded_stock", planning_order_id=order.id, model_id=target.id, planned_quantity=24)
        db.add(production); db.flush()
        for code in ("CUT", "ECT"):
            department = db.query(Department).filter_by(code=code).one()
            db.add(WorkOrder(production_order_id=production.id, department_id=department.id, operation="cutting", status="new"))
        db.commit()
        (STATE / "fixtures.json").write_text(json.dumps({"source": source.id, "target": target.id, "bso": order.id, "batch": batch.id}))
    print("Synthetic BSO, fabric and model fixtures initialized in owned SQLite only")


if __name__ == "__main__":
    if sys.argv[1:] == ["init"]:
        init()
    elif sys.argv[1:] == ["serve"]:
        import uvicorn
        uvicorn.run("app.main:app", host="127.0.0.1", port=18109)
    elif sys.argv[1:] == ["readback"]:
        from app.db.session import SessionLocal
        from app.schemas import Model, StockBatch
        ids = json.loads((STATE / "fixtures.json").read_text())
        with SessionLocal() as db:
            source, target = db.get(Model, ids["source"]), db.get(Model, ids["target"])
            assert [(r["sewingFactory"], r["rate"]) for r in target.details_json["paid_operations"]] == [("milana", "123"), ("besttex", "456"), ("eco_cotton", "789")]
            assert target.details_json["general"]["full_name"] == "Target details retained"
            assert len(source.details_json["paid_operations"]) == 3
            assert float(db.get(StockBatch, ids["batch"]).quantity) == 60
        print("PASS persisted target operations/rates/details, source definitions and fabric balance")
    else:
        raise SystemExit("Use init, serve or readback")
