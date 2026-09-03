from __future__ import annotations

import argparse
import json
from collections import defaultdict

from sqlalchemy import func

from app.db.session import SessionLocal
from app.models import (
    FinishedGoodsStock,
    Package,
    PackageItem,
    SalesOrder,
    Shipment,
    ShipmentPackage,
    StockReservation,
    User,
)
from app.services.audit import log_action
from app.services.packages import receive_at_storage


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Receive validated packed packages and reconcile one order to whole-package reservations.",
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-packed-count", type=int, required=True)
    parser.add_argument("--sales-order", required=True)
    parser.add_argument("--user-id", type=int, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    db = SessionLocal()
    try:
        user = db.get(User, args.user_id)
        if not user or not user.is_active:
            raise RuntimeError("Active audit user not found")

        package_query = db.query(Package).filter(Package.status == "packed").order_by(Package.id.asc())
        if db.bind and db.bind.dialect.name == "postgresql":
            package_query = package_query.with_for_update(of=Package)
        packed_packages = package_query.all()
        if len(packed_packages) != args.confirm_packed_count:
            raise RuntimeError(
                f"Packed-package count changed: expected {args.confirm_packed_count}, found {len(packed_packages)}",
            )

        packed_ids = [int(package.id) for package in packed_packages]
        item_totals = dict(
            db.query(PackageItem.package_id, func.coalesce(func.sum(PackageItem.quantity), 0))
            .filter(PackageItem.package_id.in_(packed_ids))
            .group_by(PackageItem.package_id)
            .all()
        ) if packed_ids else {}
        stock_totals = dict(
            db.query(FinishedGoodsStock.package_id, func.coalesce(func.sum(FinishedGoodsStock.quantity), 0))
            .filter(FinishedGoodsStock.package_id.in_(packed_ids))
            .group_by(FinishedGoodsStock.package_id)
            .all()
        ) if packed_ids else {}
        linked_ids = {
            int(package_id)
            for (package_id,) in db.query(ShipmentPackage.package_id)
            .filter(ShipmentPackage.package_id.in_(packed_ids))
            .distinct()
            .all()
        } if packed_ids else set()

        invalid = [
            package.package_no
            for package in packed_packages
            if int(item_totals.get(int(package.id), 0) or 0) != int(package.total_quantity or 0)
            or int(stock_totals.get(int(package.id), 0) or 0) != int(package.total_quantity or 0)
            or int(package.id) in linked_ids
        ]
        if invalid:
            raise RuntimeError(f"Packed-package evidence mismatch: {', '.join(invalid[:10])}")

        order = db.query(SalesOrder).filter(SalesOrder.order_no == args.sales_order).one_or_none()
        if not order:
            raise RuntimeError(f"Sales order not found: {args.sales_order}")
        shipment = (
            db.query(Shipment)
            .filter(
                Shipment.sales_order_id == order.id,
                Shipment.status.in_(("draft", "created")),
            )
            .order_by(Shipment.id.asc())
            .one_or_none()
        )
        if not shipment:
            raise RuntimeError(f"Open shipment not found for {args.sales_order}")

        reservation_rows = (
            db.query(StockReservation, FinishedGoodsStock, Package)
            .join(FinishedGoodsStock, FinishedGoodsStock.id == StockReservation.finished_goods_stock_id)
            .join(Package, Package.id == StockReservation.package_id)
            .filter(
                StockReservation.sales_order_id == order.id,
                Package.legacy_receipt_id.is_(None),
            )
            .order_by(Package.id.asc(), StockReservation.id.asc())
            .all()
        )
        reservations_by_package: dict[int, list[tuple[StockReservation, FinishedGoodsStock, Package]]] = defaultdict(list)
        for reservation, stock, package in reservation_rows:
            reservations_by_package[int(package.id)].append((reservation, stock, package))

        released_package_ids: list[int] = []
        released_qty = 0
        full_package_ids: list[int] = []
        for package_id, rows in reservations_by_package.items():
            package = rows[0][2]
            reserved_qty = sum(int(reservation.quantity or 0) for reservation, _stock, _package in rows)
            if reserved_qty == int(package.total_quantity or 0):
                full_package_ids.append(package_id)
                continue
            if reserved_qty > int(package.total_quantity or 0):
                raise RuntimeError(f"Over-reserved package: {package.package_no}")
            other_order_count = (
                db.query(StockReservation.id)
                .filter(
                    StockReservation.package_id == package_id,
                    StockReservation.sales_order_id != order.id,
                )
                .count()
            )
            if other_order_count:
                raise RuntimeError(f"Partially reserved package has another order: {package.package_no}")
            released_package_ids.append(package_id)
            for reservation, stock, _package in rows:
                quantity = int(reservation.quantity or 0)
                stock.reserved_qty = max(0, int(stock.reserved_qty or 0) - quantity)
                stock.available_qty = int(stock.available_qty or 0) + quantity
                if int(stock.available_qty or 0) > 0:
                    stock.status = "available"
                db.delete(reservation)
                released_qty += quantity

        existing_attachment_ids = {
            int(package_id)
            for (package_id,) in db.query(ShipmentPackage.package_id)
            .filter(ShipmentPackage.shipment_id == shipment.id)
            .all()
        }
        attached_package_ids: list[int] = []
        full_packages = {
            int(package.id): package
            for package in db.query(Package).filter(Package.id.in_(full_package_ids)).all()
        } if full_package_ids else {}
        for package_id in full_package_ids:
            if package_id in existing_attachment_ids:
                continue
            package = full_packages[package_id]
            db.add(
                ShipmentPackage(
                    shipment_id=shipment.id,
                    package_id=package.id,
                    quantity=package.total_quantity,
                )
            )
            attached_package_ids.append(package_id)

        summary = {
            "packed_packages_received": len(packed_packages),
            "packed_quantity_received": sum(int(package.total_quantity or 0) for package in packed_packages),
            "partial_reservation_packages_released": released_package_ids,
            "partial_reservation_quantity_released": released_qty,
            "whole_packages_attached": attached_package_ids,
            "whole_package_quantity_attached": sum(
                int(full_packages[package_id].total_quantity or 0)
                for package_id in attached_package_ids
            ),
        }

        if not args.apply:
            db.rollback()
            print(json.dumps({"mode": "dry-run", **summary}, sort_keys=True))
            return 0

        for package in packed_packages:
            receive_at_storage(db, package, package.warehouse_id, user.id)
            log_action(
                db,
                user,
                "receive_storage_bulk_correction",
                "Package",
                package.id,
                old_value={"status": "packed"},
                new_value={"status": "received_in_storage"},
            )

        if released_qty:
            order.status = "reserved"
        log_action(
            db,
            user,
            "reconcile_whole_package_reservations",
            "SalesOrder",
            order.id,
            old_value={"partial_package_ids": released_package_ids, "released_qty": released_qty},
            new_value={"whole_package_ids": full_package_ids},
        )
        log_action(
            db,
            user,
            "attach_reserved_whole_packages",
            "Shipment",
            shipment.id,
            new_value={"package_ids": attached_package_ids},
        )
        db.commit()
        print(json.dumps({"mode": "applied", **summary}, sort_keys=True))
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
