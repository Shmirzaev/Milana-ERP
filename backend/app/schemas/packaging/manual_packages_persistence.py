"""Persistence only; the calling Packaging operation owns policy and transaction."""
from uuid import uuid4
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.libs.enums.packaging import PackageScanType, PackageStatus, PackageStockKind, PackagingDepartment
from app.libs.enums.fulfillment import FinishedGoodsStatus
from app.schemas import (
    FinishedGoodsStock, ManualPackageReceipt, Package, PackageItem,
    PackagePrintRun, PackagePrintRunMember, PackageScanLog, SystemSetting,
)


def insert_manual_evidence(db: Session, *, receipt_no: str, actor_id: int,
                           evidence: dict, evidence_hash: str) -> ManualPackageReceipt:
    row = ManualPackageReceipt(receipt_no=receipt_no, created_by=actor_id,
                               evidence=evidence, evidence_hash=evidence_hash)
    db.add(row)
    db.flush()
    return row


def insert_manual_package(db: Session, *, package_no: str, barcode: str,
                          receipt_id: int, model_id: int, brand_id: int | None,
                          collection_id: int | None, color: str, size: str,
                          quantity: int, weight_kg: float, actor_id: int,
                          department: PackagingDepartment, reason: str | None) -> Package:
    row = Package(
        package_no=package_no, barcode=barcode, manual_receipt_id=receipt_id,
        model_id=model_id, brand_id=brand_id, collection_id=collection_id,
        color=color, capacity=quantity, total_quantity=quantity, weight_kg=weight_kg,
        packed_by=actor_id, packaging_department_code=department.value,
        status=PackageStatus.PACKED.value, stock_kind=PackageStockKind.STANDARD.value,
        notes=reason,
    )
    row.items = [PackageItem(model_id=model_id, color=color, size=size, quantity=quantity)]
    db.add(row)
    db.flush()
    # Match validated production Packaging: stock exists, but only received
    # packages are eligible for warehouse reservation/dispatch.
    db.add(FinishedGoodsStock(package_id=row.id, model_id=model_id, color=color,
                             size=size, quantity=quantity, available_qty=quantity,
                             brand_id=brand_id, collection_id=collection_id,
                             status=FinishedGoodsStatus.AVAILABLE.value))
    db.add(PackageScanLog(package_id=row.id, scanned_by=actor_id, scan_type=PackageScanType.PACKED.value))
    db.flush()
    return row


def write_retired_label_floor(db: Session, *, key: str, number: int) -> None:
    row = db.query(SystemSetting).filter_by(key=key).populate_existing().first()
    if row:
        row.value_json = {"number": max(number, int(row.value_json.get("number", 0)))}
    else:
        db.add(SystemSetting(key=key, value_json={"number": number}))


def apply_manual_run_deletion(db: Session, *, run: PackagePrintRun,
                              deleted_ids: list[int], fully_deleted: bool,
                              stocks: list[FinishedGoodsStock], packages: list[Package]) -> None:
    run.deleted_package_ids = deleted_ids
    if fully_deleted:
        run.deleted_at = datetime.now(timezone.utc)
    db.flush()
    for row in stocks:
        db.delete(row)
    for package in packages:
        db.delete(package)
    db.flush()


def set_manual_package_qr(package: Package, *, qr_url: str) -> None:
    package.qr_code_url = qr_url


def insert_manual_print_run(db: Session, *, run_no: str, actor_id: int,
                            department: PackagingDepartment, packages: list[Package],
                            snapshots: list[dict]) -> PackagePrintRun:
    row = PackagePrintRun(run_no=run_no, code=f"PACKRUN:{uuid4().hex}",
                          packaging_department_code=department.value,
                          created_by=actor_id, package_ids=[p.id for p in packages])
    db.add(row)
    db.flush()
    db.add_all([PackagePrintRunMember(run_id=row.id, package_id=p.id, snapshot=snapshot)
                for p, snapshot in zip(packages, snapshots, strict=True)])
    db.flush()
    return row
