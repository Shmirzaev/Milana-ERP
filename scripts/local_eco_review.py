"""Serve a disposable, loopback-only demo for PR #375 local review.

Run with the repository's test Python environment. This deliberately uses the
isolated test fixtures (never a configured production database or .env). Login
uses the existing demo admin fixture from backend/app/tests/conftest.py. All
changes made in this demo are temporary and disappear when a fresh run starts.
"""
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main():
    import uvicorn
    import secrets
    from app.tests import conftest as fixtures
    from app.core.config import settings
    settings.CORS_ORIGINS = "http://127.0.0.1:13085"
    # Cookies are shared across localhost ports. Do not collide with another
    # engineer's local preview or the user's existing local ERP session.
    settings.AUTH_COOKIE_NAME = "erp_eco_review"
    settings.JWT_SECRET = secrets.token_urlsafe(48)
    from app.schemas import BrandedPlanningOrder, CuttingPassport, Department, Item, Model, ProductionOrder, StockBatch, User, Warehouse, WorkOrder
    from app.schemas.inventory.eco_inventory import EcoMaterialBatch
    setup = fixtures.setup_db.__wrapped__()
    next(setup)
    with fixtures.TestSessionLocal() as db:
        user = db.query(User).filter_by(email="admin@example.com").one()
        model = db.query(Model).first()
        fabric = Item(sku="LOCAL-ECO-FABRIC", name="Local review cotton", category="fabric", unit="kg")
        accessory = Item(sku="LOCAL-ECO-BUTTON", name="Local review buttons", category="accessory", unit="pcs")
        warehouse = Warehouse(name="Local review Milana fabric store", type="fabric_storage")
        bso = BrandedPlanningOrder(order_no="BSO-LOCAL-REVIEW", ordered_for_type="eco_cotton", ordered_for_name="ECO COTTON", status="open")
        db.add_all([fabric, accessory, warehouse, bso]); db.flush()
        db.add(StockBatch(item_id=fabric.id, batch_no="LOCAL-MIL-001", quantity=100, unit="kg", cost_per_unit=0,
            warehouse_id=warehouse.id, qc_status="passed"))
        db.add(EcoMaterialBatch(item_id=accessory.id, kind="accessory", batch_no="LOCAL-ECO-001", unit="pcs",
            quantity=1000, reserved_quantity=0, created_by=user.id))
        order = ProductionOrder(production_no="PO-LOCAL-REVIEW", production_type="branded_stock", planning_order_id=bso.id,
            model_id=model.id, planned_quantity=100, status="cutting")
        db.add(order); db.flush()
        for code, operation in [("CUT", "cutting"), ("ECO", "sewing"), ("ECP", "packaging")]:
            dept = db.query(Department).filter_by(code=code).one()
            db.add(WorkOrder(production_order_id=order.id, department_id=dept.id, operation=operation,
                planned_input_qty=100, planned_output_qty=100))
        db.add(CuttingPassport(passport_no="LOCAL-REVIEW", date=datetime.now(timezone.utc), model_code=model.code,
            variant="LOCAL", pieces=100, fabric_type="Local review cotton", planned_kg=50, notes="Disposable local-review fixture"))
        db.commit()
    # Existing package regression fixture supplies actual sewing evidence and a
    # mixed-origin package to inspect with the new warehouse factory filter.
    from app.tests.test_package_origin import _seed
    _seed()
    print("Disposable local review API: http://127.0.0.1:18085 (no production connection)")
    uvicorn.run(fixtures.app, host="127.0.0.1", port=18085, log_level="warning")


if __name__ == "__main__":
    main()
