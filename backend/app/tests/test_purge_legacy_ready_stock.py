from uuid import uuid4

from app.db.session import SessionLocal
from app.models import (
    Brand,
    FinishedGoodsStock,
    LegacyStockReceipt,
    Model,
    Package,
    PackageBarcodeAlias,
    PackageItem,
    PackageScanLog,
)
from scripts.purge_legacy_ready_stock import (
    LEGACY_BRAND_DESCRIPTION,
    LEGACY_BRAND_NAME,
    LEGACY_MODEL_DESCRIPTION,
    purge,
)


def _stock_package(db, *, token: str, receipt: LegacyStockReceipt, model: Model):
    package = Package(
        package_no=f"LEG-PURGE-{token}",
        barcode=f"LEGACY:PURGE-{token}",
        legacy_receipt_id=receipt.id,
        model_id=model.id,
        brand_id=model.brand_id,
        color="BLUE",
        package_type="legacy_stock",
        total_quantity=7,
        capacity=60,
        status="received_in_storage",
    )
    db.add(package)
    db.flush()
    db.add_all(
        [
            PackageItem(
                package_id=package.id,
                model_id=model.id,
                color="BLUE",
                size="M",
                quantity=7,
            ),
            FinishedGoodsStock(
                package_id=package.id,
                model_id=model.id,
                brand_id=model.brand_id,
                color="BLUE",
                size="M",
                quantity=7,
                available_qty=7,
                reserved_qty=0,
                sold_qty=0,
                status="available",
            ),
            PackageBarcodeAlias(
                package_id=package.id,
                code=f"OLD-{token}",
                code_type="source_record_id",
            ),
            PackageScanLog(
                package_id=package.id,
                scan_type="legacy_import",
                location="TAYYOR MAHSULOT OMBORI",
            ),
        ]
    )
    return package


def test_purge_removes_only_reviewed_legacy_import_and_is_dry_run_safe():
    token = uuid4().hex[:10]
    db = SessionLocal()
    try:
        legacy_brand = Brand(
            name=LEGACY_BRAND_NAME,
            description=LEGACY_BRAND_DESCRIPTION,
            is_active=True,
        )
        db.add(legacy_brand)
        db.flush()
        imported_model = Model(
            code=f"LEGACY-PURGE-{token}",
            name="Imported placeholder",
            description=LEGACY_MODEL_DESCRIPTION,
            brand_id=legacy_brand.id,
            details_json={"legacy_import": True},
            status="approved",
        )
        real_model = Model(
            code=f"REAL-PURGE-{token}",
            name="Real catalog model",
            status="approved",
        )
        db.add_all([imported_model, real_model])
        db.flush()
        target_receipt = LegacyStockReceipt(
            source_system="UZERP",
            source_warehouse_id="18",
            source_record_id=f"target-{token}",
            source_checksum=f"{token:0<64}",
            source_payload={"row": token},
        )
        preserved_receipt = LegacyStockReceipt(
            source_system="OTHER",
            source_warehouse_id="18",
            source_record_id=f"preserve-{token}",
            source_checksum=f"{token:0<64}",
            source_payload={"row": token},
        )
        db.add_all([target_receipt, preserved_receipt])
        db.flush()
        target_package = _stock_package(
            db,
            token=f"target-{token}",
            receipt=target_receipt,
            model=imported_model,
        )
        preserved_package = _stock_package(
            db,
            token=f"preserve-{token}",
            receipt=preserved_receipt,
            model=real_model,
        )
        db.commit()
        target_ids = (target_receipt.id, target_package.id, imported_model.id)
        preserved_ids = (preserved_receipt.id, preserved_package.id, real_model.id)

        dry_run = purge(db, apply=False)
        assert dry_run["mode"] == "dry_run"
        assert dry_run["deleted"]["packages"] == 1
        assert db.get(LegacyStockReceipt, target_ids[0]) is not None
        assert db.get(Package, target_ids[1]) is not None
        assert db.get(Model, target_ids[2]) is not None

        applied = purge(db, apply=True)
        assert applied["mode"] == "apply"
        assert applied["deleted"]["packages"] == 1
        assert applied["deleted"]["models"] == 1
        assert db.get(LegacyStockReceipt, target_ids[0]) is None
        assert db.get(Package, target_ids[1]) is None
        assert db.get(Model, target_ids[2]) is None
        assert db.get(LegacyStockReceipt, preserved_ids[0]) is not None
        assert db.get(Package, preserved_ids[1]) is not None
        assert db.get(Model, preserved_ids[2]) is not None
    finally:
        db.close()
