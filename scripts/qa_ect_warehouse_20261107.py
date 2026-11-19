"""Owned, loopback-only synthetic QA fixture. Never connects to production.

Run `python scripts/qa_ect_warehouse_20261107.py init`, then `... serve`.
Private generated credentials and retained SQLite data stay under .qa-ect-warehouse.
"""
import json
import os
from pathlib import Path
import secrets
import sys

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".qa-ect-warehouse"
STATE.mkdir(exist_ok=True)
PRIVATE = STATE / "private.json"
if not PRIVATE.exists():
    PRIVATE.write_text(json.dumps({"password": secrets.token_urlsafe(24), "jwt": secrets.token_urlsafe(48)}))
private = json.loads(PRIVATE.read_text())
os.environ.update({
    "ENV": "development", "DATABASE_URL": f"sqlite:///{(STATE / 'qa.db').as_posix()}",
    "SHARED_STORE_URL": f"sqlite:///{(STATE / 'counters.db').as_posix()}",
    "JWT_SECRET": private["jwt"], "FILE_SIGNING_SECRET": private["jwt"],
    "INITIAL_ADMIN_EMAIL": "ect-warehouse-qa@example.com", "INITIAL_ADMIN_PASSWORD": private["password"],
    "SEED_SAMPLE_DATA": "true", "SEED_DEMO_USERS": "false", "IMPORT_LEGACY_MODELS": "false",
    "RUN_SEED_ON_STARTUP": "false", "STARTUP_SCHEMA_SYNC": "false",
    "CORS_ORIGINS": "http://127.0.0.1:3107,http://localhost:3107",
    "FRONTEND_BASE_URL": "http://127.0.0.1:3107", "ERP_PUBLIC_BASE_URL": "http://127.0.0.1:3107",
    **{name: str(STATE / folder) for name, folder in {
        "BARCODE_STORAGE_DIR": "barcodes", "MODEL_FILES_DIR": "model_files",
        "SALES_ORDER_FILES_DIR": "sales_files", "ATTENDANCE_PHOTOS_DIR": "attendance_photos",
        "HR_DOCUMENTS_DIR": "hr_documents", "TURNSTILE_PHOTOS_DIR": "turnstile_photos",
    }.items()},
})
sys.path.insert(0, str(ROOT / "backend"))


def init():
    if (STATE / "init.done").exists():
        raise SystemExit("Owned QA database already exists; retained rather than overwritten")
    from datetime import datetime, timezone
    from app.db.base import Base
    from app.db.session import engine, SessionLocal
    from app.db.seed import seed
    from app.schemas import Model, ModelSize, ModelColor, LegacyStockReceipt, Package, PackageItem
    Base.metadata.create_all(engine)
    seed(ensure_schema=False)
    with SessionLocal() as db:
        models = []
        for variant, color in (("3372", "Blue"), ("3373", "Red")):
            model = Model(code=f"SJ4044-{variant}", name="QA Cotton set", status="approved", details_json={"general": {"model_no": "SJ4044", "variant_no": variant}})
            db.add(model); db.flush()
            db.add_all([ModelSize(model_id=model.id, size=size) for size in ("M", "L")])
            db.add(ModelColor(model_id=model.id, color_name=color))
            models.append(model.id)
            for index, (cell, quantity) in enumerate((("A-01", 60), ("A-02", 35), (None, 20))):
                receipt = LegacyStockReceipt(source_system="ECT_WORKSPACE_QA", source_warehouse_id="QA", source_record_id=f"{variant}-{index}", source_checksum="0" * 64, source_payload={"model": "SJ4044", "variant": variant})
                db.add(receipt); db.flush()
                package = Package(package_no=f"QA-{variant}-{index}", barcode=f"QA-CODE-{variant}-{index}", model_id=model.id, color=color, legacy_receipt_id=receipt.id, total_quantity=quantity, capacity=60, status="received_in_storage", storage_cell=cell, storage_shelf="S1" if cell else None)
                db.add(package); db.flush()
                db.add(PackageItem(package_id=package.id, model_id=model.id, color=color, size="M", quantity=quantity))
        from app.tests.test_warehouse_shipment_report import add_shipment
        add_shipment(db, "SH-QA-2026-001", datetime(2026, 11, 7, 8, tzinfo=timezone.utc))
        db.commit()
    (STATE / "init.done").write_text("Synthetic fixture initialized")
    print("Synthetic warehouse and shipment fixtures initialized in owned SQLite only")


def extras():
    if (STATE / "extras.done").exists():
        raise SystemExit("Extra QA fixtures already exist; retained rather than duplicated")
    import httpx
    import runpy
    from app.db.session import SessionLocal
    from app.schemas import WorkOrder, CuttingPassport
    results = {}
    packaging = ROOT / "backend/app/tests/test_multi_nastil_packaging.py"
    if packaging.exists():
        order_id, model_id, batches = runpy.run_path(str(packaging))["seed_nastils"]("ECO", sessions=SessionLocal)
        with SessionLocal() as db:
            work = db.query(WorkOrder).filter_by(production_order_id=order_id, operation="packaging", production_batch_id=None).one()
            results["packaging_url"] = f"/work-orders/{work.id}/packaging?packaging_department=ECP"
            db.add(CuttingPassport(passport_no="QA-800", date=__import__("datetime").date(2026, 11, 7), production_order_id=order_id, model_code="T-SHIRT-001", variant="001", order_no="QA-Order", pieces=75))
            db.commit()
    fixture = ROOT / "backend/app/tests/sewing_receipt_browser_fixture.py"
    if fixture.exists():
        with httpx.Client(base_url="http://127.0.0.1:18107", timeout=30) as client:
            response = client.post("/api/auth/token", data={"username": "ect-warehouse-qa@example.com", "password": private["password"]})
            response.raise_for_status()
            client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"
            results["sewing"] = runpy.run_path(str(fixture))["seed_sewing_receipt_browser"](client, model_id=1, report_date="2026-11-07")
    (STATE / "fixtures.json").write_text(json.dumps(results, indent=2, default=str))
    (STATE / "extras.done").write_text("Synthetic extras initialized")
    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "init":
        init()
    elif command == "extras":
        extras()
    elif command == "serve":
        import uvicorn
        uvicorn.run("app.main:app", host="127.0.0.1", port=18107)
    else:
        raise SystemExit("Use init, extras or serve")
