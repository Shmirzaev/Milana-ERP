"""Remove the audited UZERP ready-product import and only its internal models.

Dry-run is the default. The command performs the same deletes inside a
transaction during dry-run, verifies the post-delete state, and then rolls the
transaction back. Apply mode commits only after every guard and invariant
passes.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.session import SessionLocal
from app.models import (
    Brand,
    CollectionModel,
    FinishedGoodsStock,
    LegacyStockReceipt,
    Model,
    ModelBOM,
    ModelColor,
    ModelImage,
    ModelSize,
    Package,
    PackageBarcodeAlias,
    PackageBatchAllocation,
    PackageChangeRequest,
    PackageItem,
    PackageScanLog,
    ShipmentPackage,
    ShipmentScanLog,
    StockReservation,
)
from app.services.audit import log_action


SOURCE_SYSTEM = "UZERP"
SOURCE_WAREHOUSE_ID = "18"
LEGACY_BRAND_NAME = "Legacy Stock"
LEGACY_BRAND_DESCRIPTION = (
    "Models created only to preserve finished-goods stock migrated from the legacy UZERP."
)
LEGACY_MODEL_DESCRIPTION = (
    "Created during verified UZERP ready-product inventory migration."
)

PRODUCTION_EXPECTATIONS = {
    "receipt_rows": 32361,
    "package_rows": 32361,
    "package_item_rows": 32361,
    "stock_rows": 32361,
    "package_quantity": 429687,
    "available_quantity": 429687,
    "alias_rows": 158079,
    "internal_model_rows": 511,
    "remaining_package_rows": 23,
    "remaining_package_quantity": 1340,
}


def _legacy_import_model(model: Model, legacy_brand_id: int | None) -> bool:
    details = model.details_json if isinstance(model.details_json, dict) else {}
    return (
        details.get("legacy_import") is True
        and model.description == LEGACY_MODEL_DESCRIPTION
        and legacy_brand_id is not None
        and model.brand_id == legacy_brand_id
    )


def _sum_int(db: Session, column, *criteria) -> int:
    value = db.query(func.coalesce(func.sum(column), 0)).filter(*criteria).scalar()
    return int(value or 0)


def _count_foreign_key_references(
    db: Session,
    *,
    target_table: str,
    target_id: int,
) -> dict[str, int]:
    references: dict[str, int] = {}
    for table in Base.metadata.sorted_tables:
        for column in table.columns:
            if not any(
                foreign_key.target_fullname == f"{target_table}.id"
                for foreign_key in column.foreign_keys
            ):
                continue
            count = int(
                db.execute(
                    select(func.count()).select_from(table).where(column == target_id)
                ).scalar_one()
            )
            if count:
                references[f"{table.name}.{column.name}"] = count
    return references


def purge(
    db: Session,
    *,
    apply: bool,
    expectations: dict[str, int] | None = None,
) -> dict[str, Any]:
    expected = expectations or {}
    receipts = (
        db.query(LegacyStockReceipt)
        .filter(
            LegacyStockReceipt.source_system == SOURCE_SYSTEM,
            LegacyStockReceipt.source_warehouse_id == SOURCE_WAREHOUSE_ID,
        )
        .with_for_update()
        .all()
    )
    receipt_ids = [row.id for row in receipts]
    packages = (
        db.query(Package)
        .filter(Package.legacy_receipt_id.in_(receipt_ids))
        .with_for_update()
        .all()
        if receipt_ids
        else []
    )
    package_ids = [row.id for row in packages]
    stocks = (
        db.query(FinishedGoodsStock)
        .filter(FinishedGoodsStock.package_id.in_(package_ids))
        .with_for_update()
        .all()
        if package_ids
        else []
    )
    stock_ids = [row.id for row in stocks]

    legacy_brand = (
        db.query(Brand)
        .filter(
            Brand.name == LEGACY_BRAND_NAME,
            Brand.description == LEGACY_BRAND_DESCRIPTION,
        )
        .one_or_none()
    )
    internal_models = [
        model
        for model in db.query(Model).all()
        if _legacy_import_model(model, legacy_brand.id if legacy_brand else None)
    ]
    internal_model_ids = [row.id for row in internal_models]

    before = {
        "receipt_rows": len(receipts),
        "package_rows": len(packages),
        "package_item_rows": (
            db.query(PackageItem).filter(PackageItem.package_id.in_(package_ids)).count()
            if package_ids
            else 0
        ),
        "stock_rows": len(stocks),
        "package_quantity": sum(int(row.total_quantity or 0) for row in packages),
        "available_quantity": sum(int(row.available_qty or 0) for row in stocks),
        "reserved_quantity": sum(int(row.reserved_qty or 0) for row in stocks),
        "sold_quantity": sum(int(row.sold_qty or 0) for row in stocks),
        "alias_rows": (
            db.query(PackageBarcodeAlias)
            .filter(PackageBarcodeAlias.package_id.in_(package_ids))
            .count()
            if package_ids
            else 0
        ),
        "scan_log_rows": (
            db.query(PackageScanLog)
            .filter(PackageScanLog.package_id.in_(package_ids))
            .count()
            if package_ids
            else 0
        ),
        "internal_model_rows": len(internal_models),
        "all_package_rows": db.query(Package).count(),
        "all_package_quantity": _sum_int(db, Package.total_quantity),
        "all_model_rows": db.query(Model).count(),
    }

    for key, expected_value in expected.items():
        if key.startswith("remaining_"):
            continue
        actual = before.get(key)
        if actual != expected_value:
            raise ValueError(
                f"production expectation changed for {key}: "
                f"expected {expected_value}, got {actual}"
            )

    if before["receipt_rows"] != before["package_rows"]:
        raise ValueError("expected exactly one imported package per legacy receipt")
    if before["package_item_rows"] != before["package_rows"]:
        raise ValueError("expected exactly one package item per imported package")
    if before["stock_rows"] != before["package_rows"]:
        raise ValueError("expected exactly one finished-goods row per imported package")
    if any(
        row.package_type != "legacy_stock"
        or row.production_order_id is not None
        or row.sales_order_id is not None
        or row.status != "received_in_storage"
        for row in packages
    ):
        raise ValueError("an imported package is no longer untouched legacy storage stock")
    if any(
        row.production_order_id is not None
        or row.sales_order_id is not None
        or int(row.reserved_qty or 0)
        or int(row.sold_qty or 0)
        or row.status != "available"
        for row in stocks
    ):
        raise ValueError("imported finished-goods stock has been linked, reserved, sold, or changed")

    blockers = {
        "stock_reservations": (
            db.query(StockReservation)
            .filter(StockReservation.finished_goods_stock_id.in_(stock_ids))
            .count()
            if stock_ids
            else 0
        ),
        "shipment_packages": (
            db.query(ShipmentPackage)
            .filter(ShipmentPackage.package_id.in_(package_ids))
            .count()
            if package_ids
            else 0
        ),
        "shipment_scan_logs": (
            db.query(ShipmentScanLog)
            .filter(ShipmentScanLog.package_id.in_(package_ids))
            .count()
            if package_ids
            else 0
        ),
        "batch_allocations": (
            db.query(PackageBatchAllocation)
            .filter(PackageBatchAllocation.package_id.in_(package_ids))
            .count()
            if package_ids
            else 0
        ),
        "non_import_scan_logs": (
            db.query(PackageScanLog)
            .filter(
                PackageScanLog.package_id.in_(package_ids),
                PackageScanLog.scan_type != "legacy_import",
            )
            .count()
            if package_ids
            else 0
        ),
    }
    if any(blockers.values()):
        raise ValueError(f"imported stock has downstream usage: {blockers}")

    deleted = {
        "package_change_requests": 0,
        "barcode_aliases": 0,
        "package_scan_logs": 0,
        "finished_goods_stock": 0,
        "package_items": 0,
        "packages": 0,
        "legacy_receipts": 0,
        "collection_models": 0,
        "model_images": 0,
        "model_sizes": 0,
        "model_colors": 0,
        "model_bom": 0,
        "models": 0,
        "legacy_brand": 0,
    }

    if package_ids:
        deleted["package_change_requests"] = (
            db.query(PackageChangeRequest)
            .filter(PackageChangeRequest.package_id.in_(package_ids))
            .delete(synchronize_session=False)
        )
        deleted["barcode_aliases"] = (
            db.query(PackageBarcodeAlias)
            .filter(PackageBarcodeAlias.package_id.in_(package_ids))
            .delete(synchronize_session=False)
        )
        deleted["package_scan_logs"] = (
            db.query(PackageScanLog)
            .filter(PackageScanLog.package_id.in_(package_ids))
            .delete(synchronize_session=False)
        )
        deleted["finished_goods_stock"] = (
            db.query(FinishedGoodsStock)
            .filter(FinishedGoodsStock.package_id.in_(package_ids))
            .delete(synchronize_session=False)
        )
        deleted["package_items"] = (
            db.query(PackageItem)
            .filter(PackageItem.package_id.in_(package_ids))
            .delete(synchronize_session=False)
        )
        deleted["packages"] = (
            db.query(Package)
            .filter(Package.id.in_(package_ids))
            .delete(synchronize_session=False)
        )
    if receipt_ids:
        deleted["legacy_receipts"] = (
            db.query(LegacyStockReceipt)
            .filter(LegacyStockReceipt.id.in_(receipt_ids))
            .delete(synchronize_session=False)
        )
    db.flush()

    if internal_model_ids:
        deleted["collection_models"] = (
            db.query(CollectionModel)
            .filter(CollectionModel.model_id.in_(internal_model_ids))
            .delete(synchronize_session=False)
        )
        deleted["model_images"] = (
            db.query(ModelImage)
            .filter(ModelImage.model_id.in_(internal_model_ids))
            .delete(synchronize_session=False)
        )
        deleted["model_sizes"] = (
            db.query(ModelSize)
            .filter(ModelSize.model_id.in_(internal_model_ids))
            .delete(synchronize_session=False)
        )
        deleted["model_colors"] = (
            db.query(ModelColor)
            .filter(ModelColor.model_id.in_(internal_model_ids))
            .delete(synchronize_session=False)
        )
        deleted["model_bom"] = (
            db.query(ModelBOM)
            .filter(ModelBOM.model_id.in_(internal_model_ids))
            .delete(synchronize_session=False)
        )
        db.flush()

        remaining_model_references: dict[str, int] = {}
        for model_id in internal_model_ids:
            for key, count in _count_foreign_key_references(
                db, target_table="models", target_id=model_id
            ).items():
                remaining_model_references[key] = (
                    remaining_model_references.get(key, 0) + count
                )
        if remaining_model_references:
            raise ValueError(
                "migration-only models still have non-import references: "
                f"{remaining_model_references}"
            )
        deleted["models"] = (
            db.query(Model)
            .filter(Model.id.in_(internal_model_ids))
            .delete(synchronize_session=False)
        )
    db.flush()

    legacy_brand_references: dict[str, int] = {}
    if legacy_brand is not None:
        legacy_brand_references = _count_foreign_key_references(
            db, target_table="brands", target_id=legacy_brand.id
        )
        if not legacy_brand_references:
            deleted["legacy_brand"] = (
                db.query(Brand)
                .filter(Brand.id == legacy_brand.id)
                .delete(synchronize_session=False)
            )
    db.flush()

    after = {
        "target_receipt_rows": (
            db.query(LegacyStockReceipt)
            .filter(
                LegacyStockReceipt.source_system == SOURCE_SYSTEM,
                LegacyStockReceipt.source_warehouse_id == SOURCE_WAREHOUSE_ID,
            )
            .count()
        ),
        "target_package_rows": (
            db.query(Package).filter(Package.id.in_(package_ids)).count()
            if package_ids
            else 0
        ),
        "target_stock_rows": (
            db.query(FinishedGoodsStock)
            .filter(FinishedGoodsStock.id.in_(stock_ids))
            .count()
            if stock_ids
            else 0
        ),
        "target_internal_model_rows": (
            db.query(Model).filter(Model.id.in_(internal_model_ids)).count()
            if internal_model_ids
            else 0
        ),
        "all_package_rows": db.query(Package).count(),
        "all_package_quantity": _sum_int(db, Package.total_quantity),
        "all_model_rows": db.query(Model).count(),
    }
    if any(
        after[key]
        for key in (
            "target_receipt_rows",
            "target_package_rows",
            "target_stock_rows",
            "target_internal_model_rows",
        )
    ):
        raise AssertionError(f"target legacy import rows remain after purge: {after}")
    if (
        before["all_package_rows"] - after["all_package_rows"]
        != before["package_rows"]
    ):
        raise AssertionError("purge changed an unexpected number of packages")
    if (
        before["all_package_quantity"] - after["all_package_quantity"]
        != before["package_quantity"]
    ):
        raise AssertionError("purge changed an unexpected finished-goods quantity")
    if (
        before["all_model_rows"] - after["all_model_rows"]
        != before["internal_model_rows"]
    ):
        raise AssertionError("purge changed an unexpected number of models")
    if (
        "remaining_package_rows" in expected
        and expected["remaining_package_rows"] != after["all_package_rows"]
    ):
        raise ValueError(
            "remaining package count does not match the reviewed production baseline"
        )
    if (
        "remaining_package_quantity" in expected
        and expected["remaining_package_quantity"] != after["all_package_quantity"]
    ):
        raise ValueError(
            "remaining package quantity does not match the reviewed production baseline"
        )

    result = {
        "mode": "apply" if apply else "dry_run",
        "source_system": SOURCE_SYSTEM,
        "source_warehouse_id": SOURCE_WAREHOUSE_ID,
        "before": before,
        "blockers": blockers,
        "deleted": deleted,
        "legacy_brand_references_after_purge": legacy_brand_references,
        "after": after,
    }
    if apply:
        log_action(
            db,
            None,
            "legacy_ready_stock_purge",
            "LegacyReadyStockImport",
            old_value=before,
            new_value={
                "deleted": deleted,
                "after": after,
                "source_system": SOURCE_SYSTEM,
                "source_warehouse_id": SOURCE_WAREHOUSE_ID,
            },
        )
        db.commit()
    else:
        db.rollback()
    db.expunge_all()
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit-output", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--production-expectations",
        action="store_true",
        help="Require the reviewed production counts before and after deletion.",
    )
    args = parser.parse_args()
    with SessionLocal() as db:
        result = purge(
            db,
            apply=args.apply,
            expectations=PRODUCTION_EXPECTATIONS if args.production_expectations else None,
        )
    args.audit_output.parent.mkdir(parents=True, exist_ok=True)
    args.audit_output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
