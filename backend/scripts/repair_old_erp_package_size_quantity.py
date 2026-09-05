"""Repair legacy finished-goods package quantities and size breakdowns.

The script is manifest-bound and dry-run by default.  It changes only package
quantity/capacity, PackageItem size rows, and the matching FinishedGoodsStock
rows.  Duplicate package rows may be consolidated when their model record and
color are identical; every removed barcode remains scannable as an alias on a
retained package.  Model, variant, color, weight, and immutable legacy receipt
evidence are never edited.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import func, text

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import (
    FinishedGoodsStock,
    LegacyStockReceipt,
    Package,
    PackageBarcodeAlias,
    PackageBatchAllocation,
    PackageChangeRequest,
    PackageItem,
    PackageScanLog,
    ShipmentPackage,
    ShipmentScanLog,
    StockReservation,
    User,
    Warehouse,
)
from app.services.audit import log_action


EXPECTED_ALEMBIC_HEAD = "0113_variant_selling_price"
EXPECTED_WAREHOUSE_ID = 8
EXPECTED_WAREHOUSE_NAME = "Finished Goods"
EXPECTED_WAREHOUSE_TYPE = "finished_goods"
EXPECTED_ACTOR_ID = 1
ALLOWED_SOURCE_SYSTEMS = {"UZERP_STICKER_PHOTO", "UZERP_LIVE_STOCK"}
SUFFIX_RE = re.compile(r"(?:_|-)(\d+)$")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def as_int(value: Any) -> int:
    return int(value or 0)


def package_rank(package: dict[str, Any]) -> tuple[int, int]:
    values = (str(package.get("barcode") or ""), str(package.get("package_no") or ""))
    suffixes = [int(match.group(1)) for value in values if (match := SUFFIX_RE.search(value))]
    return (min(suffixes) if suffixes else 10**9, int(package["package_id"]))


def choose_package_quantities(
    packages: list[dict[str, Any]],
    target_quantity: int,
    forced_ids: set[int] | None = None,
) -> dict[int, int]:
    """Choose retained packages and their corrected positive quantities."""

    forced_ids = set(forced_ids or set())
    ordered = sorted(packages, key=package_rank)
    by_id = {int(package["package_id"]): package for package in ordered}
    if forced_ids - set(by_id):
        raise ValueError("Forced package is absent from the guarded package set")
    forced_total = sum(as_int(by_id[package_id]["total_quantity"]) for package_id in forced_ids)
    if forced_total > target_quantity:
        raise ValueError("Protected package quantity exceeds the old ERP target")

    optional = [package for package in ordered if int(package["package_id"]) not in forced_ids]
    dp: dict[int, tuple[int, ...]] = {forced_total: tuple(sorted(forced_ids, key=lambda item: package_rank(by_id[item])))}
    for package in optional:
        package_id = int(package["package_id"])
        quantity = as_int(package["total_quantity"])
        for total, ids in list(dp.items()):
            next_total = total + quantity
            if next_total > target_quantity:
                continue
            candidate = ids + (package_id,)
            prior = dp.get(next_total)
            if prior is None or (len(candidate), candidate) < (len(prior), prior):
                dp[next_total] = candidate
    if target_quantity in dp and dp[target_quantity]:
        return {package_id: as_int(by_id[package_id]["total_quantity"]) for package_id in dp[target_quantity]}

    positive_quantities = [as_int(package["total_quantity"]) for package in ordered if as_int(package["total_quantity"]) > 0]
    if not positive_quantities:
        raise ValueError("Guarded packages have no positive quantity")
    frequencies = Counter(positive_quantities)
    modal_quantity = min(frequencies, key=lambda quantity: (-frequencies[quantity], quantity))
    desired_count = max(
        1,
        int(math.floor(Decimal(target_quantity) / Decimal(modal_quantity) + Decimal("0.5"))),
    )
    desired_count = min(desired_count, len(ordered), target_quantity)
    desired_count = max(desired_count, len(forced_ids))
    retained = [by_id[package_id] for package_id in sorted(forced_ids, key=lambda item: package_rank(by_id[item]))]
    retained.extend(package for package in optional if len(retained) < desired_count)
    if not retained:
        retained = [ordered[0]]

    result = {int(package["package_id"]): as_int(package["total_quantity"]) for package in retained if int(package["package_id"]) in forced_ids}
    remaining = target_quantity - sum(result.values())
    adjustable = [package for package in retained if int(package["package_id"]) not in forced_ids]
    if remaining < len(adjustable):
        raise ValueError("Old ERP target cannot keep all protected packages with positive adjusted rows")
    for index, package in enumerate(adjustable):
        package_id = int(package["package_id"])
        slots_after = len(adjustable) - index - 1
        if slots_after == 0:
            quantity = remaining
        else:
            quantity = min(as_int(package["total_quantity"]), remaining - slots_after)
        if quantity <= 0:
            raise ValueError("Correction planned a non-positive retained package")
        result[package_id] = quantity
        remaining -= quantity
    if remaining or sum(result.values()) != target_quantity:
        raise ValueError("Corrected package quantities do not equal the old ERP target")
    return result


def allocate_sizes(target_sizes: dict[str, int], package_quantities: dict[int, int]) -> dict[int, list[dict[str, int | str]]]:
    """Allocate an exact aggregate size vector across retained package totals."""

    ordered_ids = list(package_quantities)
    capacities = {package_id: int(package_quantities[package_id]) for package_id in ordered_ids}
    if any(quantity <= 0 for quantity in capacities.values()):
        raise ValueError("Package quantities must be positive")
    if sum(capacities.values()) != sum(int(quantity) for quantity in target_sizes.values()):
        raise ValueError("Size and package totals differ")
    allocation: dict[int, list[dict[str, int | str]]] = {package_id: [] for package_id in ordered_ids}
    sizes = list(target_sizes.items())
    for size_index, (size, raw_quantity) in enumerate(sizes):
        quantity = int(raw_quantity)
        total_remaining = sum(capacities.values())
        if size_index == len(sizes) - 1:
            shares = dict(capacities)
        else:
            ideals = {
                package_id: Decimal(quantity) * Decimal(capacity) / Decimal(total_remaining)
                for package_id, capacity in capacities.items()
            }
            shares = {
                package_id: min(capacities[package_id], int(ideal))
                for package_id, ideal in ideals.items()
            }
            remainder = quantity - sum(shares.values())
            order = sorted(
                ordered_ids,
                key=lambda package_id: (-(ideals[package_id] - int(ideals[package_id])), ordered_ids.index(package_id)),
            )
            for package_id in order:
                if remainder <= 0:
                    break
                if shares[package_id] < capacities[package_id]:
                    shares[package_id] += 1
                    remainder -= 1
            if remainder:
                raise ValueError(f"Could not allocate size {size}")
        if sum(shares.values()) != quantity:
            raise ValueError(f"Allocated size quantity differs for {size}")
        for package_id in ordered_ids:
            share = shares[package_id]
            if share:
                allocation[package_id].append({"size": size, "quantity": share})
            capacities[package_id] -= share
            if capacities[package_id] < 0:
                raise ValueError("Size allocation exceeded a package quantity")
    if any(capacities.values()):
        raise ValueError("Size allocation left package capacity unused")
    return allocation


def read_manifest(path: Path, expected_hash: str) -> dict[str, Any]:
    if sha256(path) != expected_hash:
        raise ValueError("Correction manifest SHA-256 changed")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("version") != 1 or payload.get("warehouse_id") != EXPECTED_WAREHOUSE_ID:
        raise ValueError("Correction manifest identity guard failed")
    rows = payload.get("rows") or []
    if payload.get("summary", {}).get("correction_groups") != len(rows):
        raise ValueError("Correction manifest group count changed")
    if len({str(row.get("external_qr")) for row in rows}) != len(rows):
        raise ValueError("Correction manifest repeats an external QR")
    for row in rows:
        target = as_int(row.get("target_quantity"))
        sizes = {str(size): as_int(quantity) for size, quantity in (row.get("target_sizes") or {}).items()}
        packages = row.get("packages") or []
        if target <= 0 or not sizes or sum(sizes.values()) != target or any(value <= 0 for value in sizes.values()):
            raise ValueError(f"Invalid target sizes for QR {row.get('external_qr')}")
        if not packages or len({as_int(package.get("package_id")) for package in packages}) != len(packages):
            raise ValueError(f"Invalid guarded packages for QR {row.get('external_qr')}")
        if len({as_int(package.get("model_id")) for package in packages}) != 1:
            raise ValueError(f"QR {row.get('external_qr')} crosses model records")
        if len({str(package.get("color")) for package in packages}) != 1:
            raise ValueError(f"QR {row.get('external_qr')} crosses colors")
    return payload


def database_totals(db) -> dict[str, int]:
    packages = db.query(Package).filter(Package.warehouse_id == EXPECTED_WAREHOUSE_ID)
    stocks = db.query(FinishedGoodsStock).filter(FinishedGoodsStock.warehouse_id == EXPECTED_WAREHOUSE_ID)
    sums = db.query(
        func.count(FinishedGoodsStock.id),
        func.coalesce(func.sum(FinishedGoodsStock.quantity), 0),
        func.coalesce(func.sum(FinishedGoodsStock.available_qty), 0),
        func.coalesce(func.sum(FinishedGoodsStock.reserved_qty), 0),
        func.coalesce(func.sum(FinishedGoodsStock.sold_qty), 0),
    ).filter(FinishedGoodsStock.warehouse_id == EXPECTED_WAREHOUSE_ID).one()
    return {
        "packages": packages.count(),
        "package_quantity": as_int(packages.with_entities(func.coalesce(func.sum(Package.total_quantity), 0)).scalar()),
        "stock_rows": as_int(sums[0]),
        "stock_quantity": as_int(sums[1]),
        "available_quantity": as_int(sums[2]),
        "reserved_quantity": as_int(sums[3]),
        "sold_quantity": as_int(sums[4]),
        "balance_failures": stocks.filter(
            FinishedGoodsStock.quantity
            != FinishedGoodsStock.available_qty + FinishedGoodsStock.reserved_qty + FinishedGoodsStock.sold_qty
        ).count(),
    }


def assert_target(db, args: argparse.Namespace, payload: dict[str, Any]) -> tuple[Warehouse, User]:
    parsed = urlparse(settings.DATABASE_URL.replace("postgresql+psycopg2://", "postgresql://", 1))
    current_database = str(db.execute(text("select current_database()" )).scalar() or "")
    server_address = str(db.execute(text("select inet_server_addr()" )).scalar() or "")
    heads = [str(row[0]) for row in db.execute(text("select version_num from alembic_version order by version_num"))]
    if (parsed.hostname or "").casefold() != args.expected_database_host.casefold() or current_database != args.expected_database_name:
        raise ValueError(
            "Production database identity guard failed: "
            f"configured_host={parsed.hostname!r}, server_address={server_address!r}, database={current_database!r}"
        )
    if heads != [EXPECTED_ALEMBIC_HEAD] or payload.get("expected_alembic_head") != EXPECTED_ALEMBIC_HEAD:
        raise ValueError(f"Expected Alembic {EXPECTED_ALEMBIC_HEAD}, found {heads}")
    warehouse = db.get(Warehouse, EXPECTED_WAREHOUSE_ID)
    if not warehouse or warehouse.name != EXPECTED_WAREHOUSE_NAME or warehouse.type != EXPECTED_WAREHOUSE_TYPE:
        raise ValueError("Finished Goods warehouse guard failed")
    actor = db.get(User, args.actor_id)
    permissions = set((actor.role.permissions if actor and actor.role else []) + ((actor.extra_permissions or []) if actor else []))
    if not actor or not actor.is_active or "*" not in permissions:
        raise ValueError("Correction actor is not an active wildcard administrator")
    return warehouse, actor


def current_package_guard(db, package: Package) -> dict[str, Any]:
    receipt = db.get(LegacyStockReceipt, package.legacy_receipt_id) if package.legacy_receipt_id else None
    items = db.query(PackageItem).filter(PackageItem.package_id == package.id).order_by(PackageItem.id).all()
    stocks = db.query(FinishedGoodsStock).filter(FinishedGoodsStock.package_id == package.id).order_by(FinishedGoodsStock.id).all()
    aliases = db.query(PackageBarcodeAlias).filter(PackageBarcodeAlias.package_id == package.id).all()
    return {
        "package_id": int(package.id),
        "package_no": package.package_no,
        "barcode": package.barcode,
        "status": package.status,
        "total_quantity": as_int(package.total_quantity),
        "capacity": as_int(package.capacity),
        "warehouse_id": as_int(package.warehouse_id),
        "model_id": as_int(package.model_id),
        "color": package.color,
        "legacy_receipt_id": as_int(receipt.id) if receipt else None,
        "legacy_source_system": receipt.source_system if receipt else None,
        "legacy_source_record_id": receipt.source_record_id if receipt else None,
        "items": [
            {"id": as_int(item.id), "model_id": as_int(item.model_id), "color": item.color, "size": item.size, "quantity": as_int(item.quantity)}
            for item in items
        ],
        "stocks": [
            {
                "id": as_int(stock.id), "model_id": as_int(stock.model_id), "color": stock.color,
                "size": stock.size, "quantity": as_int(stock.quantity), "available_qty": as_int(stock.available_qty),
                "reserved_qty": as_int(stock.reserved_qty), "sold_qty": as_int(stock.sold_qty), "status": stock.status,
            }
            for stock in stocks
        ],
        "aliases": sorted(
            [{"code": alias.code, "code_type": alias.code_type} for alias in aliases],
            key=lambda row: (row["code"], row["code_type"]),
        ),
    }


@dataclass
class GroupPlan:
    external_qr: str
    target_quantity: int
    target_sizes: dict[str, int]
    package_quantities: dict[int, int]
    size_allocations: dict[int, list[dict[str, int | str]]]
    removed_ids: list[int]
    protected_ids: list[int]


def plan_group(db, row: dict[str, Any]) -> GroupPlan:
    expected_packages = sorted(row["packages"], key=package_rank)
    package_ids = [as_int(package["package_id"]) for package in expected_packages]
    packages = (
        db.query(Package)
        .filter(Package.id.in_(package_ids))
        .order_by(Package.id)
        .with_for_update()
        .all()
    )
    if {as_int(package.id) for package in packages} != set(package_ids):
        raise ValueError(f"QR {row['external_qr']}: guarded package disappeared")
    expected_by_id = {as_int(package["package_id"]): package for package in expected_packages}
    for package in packages:
        if current_package_guard(db, package) != expected_by_id[as_int(package.id)]:
            raise ValueError(f"QR {row['external_qr']}: package {package.id} changed after the audit")
        if package.status != "received_in_storage" or package.warehouse_id != EXPECTED_WAREHOUSE_ID:
            raise ValueError(f"QR {row['external_qr']}: package {package.id} is no longer editable legacy stock")
        receipt = db.get(LegacyStockReceipt, package.legacy_receipt_id) if package.legacy_receipt_id else None
        if not receipt or receipt.source_system not in ALLOWED_SOURCE_SYSTEMS:
            raise ValueError(f"QR {row['external_qr']}: package {package.id} lacks approved legacy evidence")

    shipment_links = db.query(ShipmentPackage.package_id).filter(ShipmentPackage.package_id.in_(package_ids)).all()
    shipment_scans = db.query(ShipmentScanLog.package_id).filter(ShipmentScanLog.package_id.in_(package_ids)).all()
    allocations = db.query(PackageBatchAllocation.package_id).filter(PackageBatchAllocation.package_id.in_(package_ids)).all()
    pending = db.query(PackageChangeRequest.package_id).filter(
        PackageChangeRequest.package_id.in_(package_ids), PackageChangeRequest.status == "pending"
    ).all()
    if shipment_links or shipment_scans or allocations or pending:
        raise ValueError(f"QR {row['external_qr']}: shipment, batch, or pending-change linkage blocks correction")

    reservation_ids = {as_int(value[0]) for value in db.query(StockReservation.package_id).filter(StockReservation.package_id.in_(package_ids)).all() if value[0]}
    stock_protected_ids = {
        as_int(value[0])
        for value in db.query(FinishedGoodsStock.package_id).filter(
            FinishedGoodsStock.package_id.in_(package_ids),
            (FinishedGoodsStock.reserved_qty > 0) | (FinishedGoodsStock.sold_qty > 0),
        ).all()
        if value[0]
    }
    protected_ids = reservation_ids | stock_protected_ids
    package_quantities = choose_package_quantities(expected_packages, as_int(row["target_quantity"]), protected_ids)
    size_allocations = allocate_sizes(
        {str(size): as_int(quantity) for size, quantity in row["target_sizes"].items()},
        package_quantities,
    )
    return GroupPlan(
        external_qr=str(row["external_qr"]),
        target_quantity=as_int(row["target_quantity"]),
        target_sizes={str(size): as_int(quantity) for size, quantity in row["target_sizes"].items()},
        package_quantities=package_quantities,
        size_allocations=size_allocations,
        removed_ids=sorted(set(package_ids) - set(package_quantities)),
        protected_ids=sorted(protected_ids),
    )


def apply_group(db, row: dict[str, Any], plan: GroupPlan, actor: User) -> None:
    package_ids = [as_int(package["package_id"]) for package in row["packages"]]
    packages = {as_int(package.id): package for package in db.query(Package).filter(Package.id.in_(package_ids)).all()}
    retained_ids = list(plan.package_quantities)
    alias_target_id = retained_ids[0]
    prior_codes: dict[str, str] = {}
    for package in packages.values():
        prior_codes.setdefault(package.barcode, "legacy_package_qr")
        for alias in db.query(PackageBarcodeAlias).filter(PackageBarcodeAlias.package_id == package.id).all():
            prior_codes.setdefault(alias.code, alias.code_type)

    for package_id in plan.removed_ids:
        package = packages[package_id]
        db.query(PackageScanLog).filter(PackageScanLog.package_id == package_id).update(
            {PackageScanLog.package_id: alias_target_id}, synchronize_session=False
        )
        db.query(PackageBarcodeAlias).filter(PackageBarcodeAlias.package_id == package_id).delete(synchronize_session=False)
        db.query(FinishedGoodsStock).filter(FinishedGoodsStock.package_id == package_id).delete(synchronize_session=False)
        db.query(PackageItem).filter(PackageItem.package_id == package_id).delete(synchronize_session=False)
        db.flush()
        db.delete(package)
    db.flush()

    for package_id, corrected_quantity in plan.package_quantities.items():
        package = packages[package_id]
        allocation = plan.size_allocations[package_id]
        package.total_quantity = corrected_quantity
        package.capacity = corrected_quantity
        db.query(PackageItem).filter(PackageItem.package_id == package_id).delete(synchronize_session=False)
        for item in allocation:
            db.add(
                PackageItem(
                    package_id=package_id,
                    model_id=package.model_id,
                    color=package.color,
                    size=str(item["size"]),
                    quantity=as_int(item["quantity"]),
                )
            )

        stocks = db.query(FinishedGoodsStock).filter(FinishedGoodsStock.package_id == package_id).order_by(FinishedGoodsStock.id).all()
        if package_id in plan.protected_ids:
            if sum(as_int(stock.quantity) for stock in stocks) != corrected_quantity:
                raise ValueError(f"QR {plan.external_qr}: protected package {package_id} quantity cannot change")
        else:
            if not stocks or any(as_int(stock.reserved_qty) or as_int(stock.sold_qty) for stock in stocks):
                raise ValueError(f"QR {plan.external_qr}: package {package_id} stock is not safely replaceable")
            template = stocks[0]
            stable = {
                (
                    stock.production_order_id, stock.sales_order_id, stock.model_id, stock.collection_id,
                    stock.brand_id, stock.color, Decimal(stock.cost_per_piece or 0), Decimal(stock.selling_price or 0),
                    stock.warehouse_id,
                )
                for stock in stocks
            }
            if len(stable) != 1:
                raise ValueError(f"QR {plan.external_qr}: package {package_id} stock metadata is mixed")
            db.query(FinishedGoodsStock).filter(FinishedGoodsStock.package_id == package_id).delete(synchronize_session=False)
            db.flush()
            for item in allocation:
                quantity = as_int(item["quantity"])
                db.add(
                    FinishedGoodsStock(
                        production_order_id=template.production_order_id,
                        sales_order_id=template.sales_order_id,
                        package_id=package_id,
                        model_id=template.model_id,
                        collection_id=template.collection_id,
                        brand_id=template.brand_id,
                        color=template.color,
                        size=str(item["size"]),
                        quantity=quantity,
                        available_qty=quantity,
                        reserved_qty=0,
                        sold_qty=0,
                        cost_per_piece=template.cost_per_piece,
                        selling_price=template.selling_price,
                        warehouse_id=template.warehouse_id,
                        status="available",
                    )
                )
        db.add(
            PackageScanLog(
                package_id=package_id,
                scanned_by=actor.id,
                scan_type="legacy_size_quantity_repair",
                location=EXPECTED_WAREHOUSE_NAME,
            )
        )

    db.flush()
    existing_codes = {
        alias.code
        for alias in db.query(PackageBarcodeAlias).filter(PackageBarcodeAlias.package_id == alias_target_id).all()
    }
    existing_codes.add(packages[alias_target_id].barcode)
    for code, code_type in sorted(prior_codes.items()):
        if code not in existing_codes:
            db.add(PackageBarcodeAlias(package_id=alias_target_id, code=code, code_type=code_type))
            existing_codes.add(code)
    db.flush()


def verify_group(db, row: dict[str, Any], plan: GroupPlan) -> dict[str, Any]:
    retained_ids = list(plan.package_quantities)
    packages = db.query(Package).filter(Package.id.in_(retained_ids)).all()
    if {as_int(package.id) for package in packages} != set(retained_ids):
        raise ValueError(f"QR {plan.external_qr}: retained package readback failed")
    if db.query(Package.id).filter(Package.id.in_(plan.removed_ids or [-1])).count():
        raise ValueError(f"QR {plan.external_qr}: duplicate package deletion readback failed")
    if sum(as_int(package.total_quantity) for package in packages) != plan.target_quantity:
        raise ValueError(f"QR {plan.external_qr}: package quantity readback failed")
    if {as_int(package.model_id) for package in packages} != {as_int(row["expected_model_id"])}:
        raise ValueError(f"QR {plan.external_qr}: model record changed")
    if {package.color for package in packages} != {str(row["expected_color"])}:
        raise ValueError(f"QR {plan.external_qr}: color changed")
    items = db.query(PackageItem).filter(PackageItem.package_id.in_(retained_ids)).all()
    item_sizes: dict[str, int] = defaultdict(int)
    for item in items:
        item_sizes[item.size] += as_int(item.quantity)
    if dict(sorted(item_sizes.items())) != dict(sorted(plan.target_sizes.items())):
        raise ValueError(f"QR {plan.external_qr}: size breakdown readback failed")
    stocks = db.query(FinishedGoodsStock).filter(FinishedGoodsStock.package_id.in_(retained_ids)).all()
    if sum(as_int(stock.quantity) for stock in stocks) != plan.target_quantity:
        raise ValueError(f"QR {plan.external_qr}: stock quantity readback failed")
    if any(as_int(stock.quantity) != as_int(stock.available_qty) + as_int(stock.reserved_qty) + as_int(stock.sold_qty) for stock in stocks):
        raise ValueError(f"QR {plan.external_qr}: stock balance readback failed")
    prior_codes = {package["barcode"] for package in row["packages"]}
    prior_codes.update(alias["code"] for package in row["packages"] for alias in package["aliases"])
    active_codes = {package.barcode for package in packages}
    active_codes.update(
        alias.code for alias in db.query(PackageBarcodeAlias).filter(PackageBarcodeAlias.package_id.in_(retained_ids)).all()
    )
    if not prior_codes <= active_codes:
        raise ValueError(f"QR {plan.external_qr}: a prior QR code is no longer scannable")
    return {
        "external_qr": plan.external_qr,
        "retained_package_ids": retained_ids,
        "removed_package_ids": plan.removed_ids,
        "target_quantity": plan.target_quantity,
        "size_rows": len(items),
        "protected_package_ids": plan.protected_ids,
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    payload = read_manifest(args.input, args.expected_manifest_sha256)
    with SessionLocal() as db:
        _, actor = assert_target(db, args, payload)
        actor_id = as_int(actor.id)
        before = database_totals(db)
        expected_before = {key: as_int(value) for key, value in payload["pre_totals"].items()}
        if before != expected_before:
            raise ValueError(f"Warehouse changed after the guarded snapshot: {before} != {expected_before}")
        plans = []
        blocked_groups = []
        for row in payload["rows"]:
            try:
                plans.append(plan_group(db, row))
            except ValueError as exc:
                if args.mode == "dry-run" and "linkage blocks correction" in str(exc):
                    blocked_groups.append({"external_qr": row["external_qr"], "reason": str(exc)})
                    continue
                raise
        if blocked_groups:
            raise ValueError(f"Linked package groups block correction: {json.dumps(blocked_groups, sort_keys=True)}")
        summary = {
            "mode": args.mode,
            "manifest_sha256": args.expected_manifest_sha256,
            "groups": len(plans),
            "guarded_packages": sum(len(row["packages"]) for row in payload["rows"]),
            "retained_packages": sum(len(plan.package_quantities) for plan in plans),
            "removed_duplicate_packages": sum(len(plan.removed_ids) for plan in plans),
            "protected_packages": sum(len(plan.protected_ids) for plan in plans),
            "current_quantity": sum(sum(as_int(package["total_quantity"]) for package in row["packages"]) for row in payload["rows"]),
            "target_quantity": sum(plan.target_quantity for plan in plans),
            "excluded_groups": len(payload.get("excluded") or []),
            "before": before,
        }
        if args.mode == "dry-run":
            db.rollback()
            return summary
        confirmation = f"APPLY-{len(plans)}-OLD-ERP-SIZE-QUANTITY-{args.expected_manifest_sha256[:12].upper()}"
        if args.confirm != confirmation:
            raise ValueError("Apply confirmation phrase is missing or incorrect")
        try:
            results = []
            for row, plan in zip(payload["rows"], plans, strict=True):
                apply_group(db, row, plan, actor)
                results.append(verify_group(db, row, plan))
            audit = log_action(
                db,
                actor,
                "legacy_package_size_quantity_repair",
                "Package",
                None,
                old_value={"warehouse_totals": before},
                new_value={
                    "manifest_sha256": args.expected_manifest_sha256,
                    "groups": len(plans),
                    "retained_packages": summary["retained_packages"],
                    "removed_duplicate_packages": summary["removed_duplicate_packages"],
                    "target_quantity": summary["target_quantity"],
                    "excluded_groups": summary["excluded_groups"],
                },
            )
            db.flush()
            audit_id = as_int(audit.id)
            after_in_transaction = database_totals(db)
            db.commit()
        except Exception:
            db.rollback()
            raise

    with SessionLocal() as verify_db:
        assert_target(verify_db, args, payload)
        verified = [verify_group(verify_db, row, plan) for row, plan in zip(payload["rows"], plans, strict=True)]
        after = database_totals(verify_db)
        audit_row = verify_db.execute(
            text("select action, user_id, entry_hash from audit_logs where id=:id"), {"id": audit_id}
        ).mappings().one()
        if audit_row["action"] != "legacy_package_size_quantity_repair" or audit_row["user_id"] != actor_id or not audit_row["entry_hash"]:
            raise ValueError("Committed audit readback failed")
        verify_db.rollback()
    if after != after_in_transaction:
        raise ValueError("Warehouse changed during committed readback")
    return {**summary, "committed": True, "audit_id": audit_id, "after": after, "verified_groups": len(verified)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--expected-database-host", required=True)
    parser.add_argument("--expected-database-name", required=True)
    parser.add_argument("--actor-id", type=int, default=EXPECTED_ACTOR_ID)
    parser.add_argument("--mode", choices=("dry-run", "apply"), default="dry-run")
    parser.add_argument("--confirm")
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(run(parse_args()), ensure_ascii=False, indent=2, sort_keys=True, default=str))
