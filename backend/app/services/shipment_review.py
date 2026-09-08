"""Warehouse quantity corrections and read-only shipment document data.

Receipt/label evidence stays immutable. Corrections preserve stock-row identity
and record changed contents; increases require an explicit physical receipt.
"""
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
import json

from fastapi import HTTPException
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Customer, FinishedGoodsStock, Invoice, Model, Package, PackageBatchAllocation, Payment,
    PackageItem, SalesOrder, SalesOrderItem, Shipment, ShipmentPackage,
    StockReservation, User,
)
from app.schemas.shipment_review import ShipmentAmountReview, ShipmentQuantityReview
from app.models.shipment_review import PackageQuantityAdjustment
from app.core.deps import user_permissions
from app.services.audit import log_action
from app.services.shipment_invoice import build_invoice_rows, invoice_model_identity


def locked_shipment(db: Session, shipment_id: int) -> Shipment:
    shipment = db.query(Shipment).filter(Shipment.id == shipment_id).with_for_update().populate_existing().first()
    if not shipment:
        raise HTTPException(404, "Shipment not found")
    return shipment


def correct_received_quantity(db: Session, shipment: Shipment, package_id: int,
                              payload: ShipmentQuantityReview, user: User) -> None:
    if shipment.status not in {"draft", "created"}:
        raise HTTPException(409, "Quantities can only be corrected before shipment")
    if not payload.reason.strip() or len(payload.reason.strip()) < 3:
        raise HTTPException(422, "A correction reason is required")
    link = db.query(ShipmentPackage).filter_by(shipment_id=shipment.id, package_id=package_id).first()
    package = db.query(Package).filter_by(id=package_id).with_for_update().populate_existing().first()
    if not link or not package:
        raise HTTPException(404, "Package is not attached to this shipment")
    if package.status not in {"received_in_storage", "reserved"}:
        raise HTTPException(409, "Only received packages can be corrected")
    if package.total_quantity != payload.expected_quantity or link.quantity != package.total_quantity:
        raise HTTPException(409, "Package quantity changed; reload before correcting")
    if db.query(ShipmentPackage.id).filter(ShipmentPackage.package_id == package_id,
                                          ShipmentPackage.shipment_id != shipment.id).first():
        raise HTTPException(409, "Package is linked to another shipment")
    items = db.query(PackageItem).filter_by(package_id=package_id).order_by(PackageItem.id).with_for_update().all()
    proposed = {line.item_id: line.quantity for line in payload.items}
    if len(proposed) != len(payload.items) or set(proposed) != {item.id for item in items}:
        raise HTTPException(422, "Supply each package item exactly once")
    increases = sum(max(0, proposed[item.id] - item.quantity) for item in items)
    reductions = sum(max(0, item.quantity - proposed[item.id]) for item in items)
    if increases:
        permissions = set(user_permissions(user))
        if "*" not in permissions and not {"storage.shipment", "storage.packages"}.issubset(permissions):
            raise HTTPException(403, "Additional received pieces require both storage.shipment and storage.packages")
        if not payload.confirm_extra_receipt:
            raise HTTPException(409, "Confirm physical receipt of additional pieces and provide a reason")
    if sum(item.quantity for item in items) != package.total_quantity:
        raise HTTPException(409, "Package contents do not balance; reconcile the package first")
    total = sum(proposed.values())
    if total <= 0:
        raise HTTPException(409, "Remove the whole package from the shipment instead of setting its total to zero")
    if increases and total > 10000:
        raise HTTPException(409, "Confirmed physical receipt is limited to 10000 pieces per package")
    if not increases and not reductions:
        return
    allocations = db.query(PackageBatchAllocation).filter_by(package_id=package_id).with_for_update().all()
    stocks = db.query(FinishedGoodsStock).filter_by(package_id=package_id).order_by(FinishedGoodsStock.id).with_for_update().all()
    reservations = db.query(StockReservation).filter_by(package_id=package_id).order_by(StockReservation.id).with_for_update().all()
    if any(row.sales_order_id != shipment.sales_order_id for row in reservations):
        raise HTTPException(409, "Package is reserved for another sales order")
    keyed_stocks = defaultdict(list)
    for stock in stocks:
        if not stock.quantity and not stock.available_qty and not stock.reserved_qty and not stock.sold_qty:
            continue
        keyed_stocks[(stock.model_id, stock.color, stock.size)].append(stock)
    keyed_items = defaultdict(list)
    for item in items:
        keyed_items[(item.model_id, item.color, item.size)].append(item)
    if set(keyed_items) != set(keyed_stocks):
        raise HTTPException(409, "Package contents and warehouse stock do not match")
    before = {"quantity": package.total_quantity, "capacity": package.capacity, "items": [], "stocks": [], "reservations": []}
    after = {"quantity": total, "capacity": max(package.capacity, total), "items": [], "stocks": [], "reservations": [], "reason": payload.reason.strip()}
    for key, group in keyed_items.items():
        if len(keyed_stocks[key]) != 1:
            raise HTTPException(409, "Ambiguous warehouse stock rows require reconciliation")
        stock = keyed_stocks[key][0]
        old_qty = sum(item.quantity for item in group)
        new_qty = sum(proposed[item.id] for item in group)
        own_reservations = [row for row in reservations if row.finished_goods_stock_id == stock.id]
        if (stock.sold_qty or stock.quantity != old_qty or
                stock.available_qty + stock.reserved_qty != old_qty or
                sum(row.quantity for row in own_reservations) != stock.reserved_qty):
            raise HTTPException(409, "Stock/reservation quantities do not balance")
        before["stocks"].append({"id": stock.id, "quantity": stock.quantity,
                                  "available": stock.available_qty, "reserved": stock.reserved_qty})
        before["reservations"].extend({"id": row.id, "quantity": row.quantity} for row in own_reservations)
        if new_qty > old_qty:
            increase = new_qty - old_qty
            if own_reservations:
                own_reservations[0].quantity += increase
                stock.reserved_qty += increase
            else:
                stock.available_qty += increase
        else:
            reduction = old_qty - new_qty
            from_available = min(stock.available_qty, reduction)
            stock.available_qty -= from_available
            remaining = reduction - from_available
            for row in reversed(own_reservations):
                take = min(row.quantity, remaining)
                row.quantity -= take
                stock.reserved_qty -= take
                remaining -= take
                if row.quantity == 0:
                    db.delete(row)
        after["reservations"].extend({"id": row.id, "quantity": row.quantity} for row in own_reservations)
        stock.quantity = new_qty
        stock.status = "available" if stock.available_qty or not new_qty else "reserved"
        after["stocks"].append({"id": stock.id, "quantity": new_qty,
                                 "available": stock.available_qty, "reserved": stock.reserved_qty})
    for item in items:
        before["items"].append({"id": item.id, "quantity": item.quantity})
        item.quantity = proposed[item.id]
        after["items"].append({"id": item.id, "quantity": item.quantity})
        if item.quantity == 0:
            db.delete(item)
    if allocations:
        before["batch_allocations"] = [{"id": row.id, "quantity": row.quantity} for row in allocations]
        after["batch_allocations"] = [{"id": row.id, "quantity": row.quantity} for row in allocations]
    before["quantity_shortfall"] = int(package.quantity_shortfall or 0)
    restored_shortfall = min(increases, before["quantity_shortfall"] + reductions)
    extra_receipt = increases - restored_shortfall
    package.quantity_shortfall = before["quantity_shortfall"] + reductions - restored_shortfall
    after["quantity_shortfall"] = package.quantity_shortfall
    after["restored_shortfall_quantity"] = restored_shortfall
    after["extra_receipt_quantity"] = extra_receipt
    after["confirmed_extra_receipt"] = payload.confirm_extra_receipt
    db.add(PackageQuantityAdjustment(package_id=package_id, shipment_id=shipment.id, delta=total-package.total_quantity,
                                    before_json=before, after_json=after, reason=payload.reason.strip(), created_by=user.id,
                                    extra_receipt_quantity=extra_receipt))
    package.total_quantity = total
    package.capacity = after["capacity"]
    link.quantity = total
    log_action(db, user, "correct_shipment_package_quantity", "Shipment", shipment.id,
               old_value={"package_id": package_id, **before}, new_value={"package_id": package_id, **after})
    db.flush()


def shipment_document(db: Session, shipment: Shipment, *, scanned_ids: set[int] | None = None) -> dict:
    frozen = (shipment.dispatch_snapshot or {}).get("document")
    if shipment.status in {"shipped", "delivered"} and frozen:
        return frozen
    order = db.get(SalesOrder, shipment.sales_order_id) if shipment.sales_order_id else None
    customer_id = shipment.customer_id or (order.customer_id if order else None)
    customer = db.get(Customer, customer_id) if customer_id else None
    order_items = db.query(SalesOrderItem).filter_by(sales_order_id=order.id).all() if order else []
    rows = db.query(ShipmentPackage, Package).options(selectinload(Package.legacy_receipt)).join(Package, Package.id == ShipmentPackage.package_id).filter(
        ShipmentPackage.shipment_id == shipment.id).order_by(Package.id).all()
    package_ids = [package.id for _, package in rows]
    contents = db.query(PackageItem).filter(PackageItem.package_id.in_(package_ids)).order_by(PackageItem.id).all() if package_ids else []
    models = {model.id: model for model in db.query(Model).filter(Model.id.in_({i.model_id for i in contents})).all()} if contents else {}
    lines = []
    total = Decimal("0")
    unknown_prices = False
    pieces = 0
    pack_count = 0
    package_details = []
    for link, package in rows:
        if scanned_ids is not None and package.id not in scanned_ids:
            continue
        pack_count += 1
        pieces += link.quantity
        package_details.append({"package_no": package.package_no, "quantity": link.quantity,
                                "weight_kg": str(package.weight_kg) if package.weight_kg is not None else None})
        package_items = [item for item in contents if item.package_id == package.id]
        balanced = sum(item.quantity for item in package_items) == link.quantity
        if not balanced:
            unknown_prices = True
        for item in package_items:
            candidates = [line for line in order_items if line.model_id == item.model_id]
            exact = [line for line in candidates if line.color == item.color and line.size == item.size]
            wildcard = [line for line in candidates if (line.color.lower() in {"mixed", "any", "*", ""}) and
                        (line.size.lower() in {"any", "mixed", "*", "", "bag"} or line.size.lower().startswith("pack"))]
            prices = {Decimal(str(line.unit_price)) for line in (exact or wildcard)}
            price = next(iter(prices)) if len(prices) == 1 and balanced else None
            amount = (price * item.quantity).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if price is not None else None
            if amount is None:
                unknown_prices = True
            else:
                total += amount
            model = models.get(item.model_id)
            legacy_source = package.legacy_receipt.source_payload if package.legacy_receipt else {}
            model_no, variant_no = invoice_model_identity(model, legacy_source)
            model_details = model.details_json if model and isinstance(model.details_json, dict) else {}
            hidden = bool(model_details.get("legacy_import")) or bool(model and model.code.startswith("LEGACY-"))
            description = ((legacy_source.get("product") or legacy_source.get("finished_name")) if hidden else None) or ((model.name or model.description) if model else None)
            lines.append({"package_no": package.package_no, "model_code": model.code if model else "",
                          "model_no": model_no, "variant_no": variant_no,
                          "description": description,
                          "color": item.color, "size": item.size, "quantity": item.quantity,
                          "unit_price": str(price) if price is not None else None,
                          "amount": str(amount) if amount is not None else None})
    document = {"shipment_no": shipment.shipment_no, "sales_order_no": order.order_no if order else None,
            "customer": customer.name if customer else shipment.notes, "supplier": "Milana Tex",
            "transport_details": dict(shipment.transport_details or {}),
            "shipped_at": shipment.shipped_at.isoformat() if shipment.shipped_at else None,
            "packages_count": pack_count, "quantity": pieces, "lines": lines,
            "amount": None if unknown_prices else str(total.quantize(Decimal("0.01"))),
            "pricing_complete": not unknown_prices, "historical_reconstruction": False,
            "document_type": "commercial_invoice", "finance_posting_status": "unposted"}
    known_weight = sum((Decimal(row["weight_kg"]) for row in package_details if row["weight_kg"] is not None), Decimal("0"))
    missing_weight = sum(row["weight_kg"] is None for row in package_details)
    document.update({"package_details": package_details,
                     "invoice_rows": build_invoice_rows(lines, package_details),
                     "known_weight_kg": str(known_weight), "missing_weight_packages": missing_weight,
                     "total_weight_kg": str(known_weight) if not missing_weight else None,
                     "invoice_layout_version": 2})
    document["basis"] = sha256(json.dumps({"packages": [(p.id, link.quantity) for link, p in rows
                                                        if scanned_ids is None or p.id in scanned_ids],
                                         "lines": lines}, sort_keys=True).encode()).hexdigest()
    document["calculated_amount"] = document["amount"]
    review = (shipment.dispatch_snapshot or {}).get("review")
    document["review_stale"] = bool(review and review.get("basis") != document["basis"])
    if review and not document["review_stale"]:
        document["amount"] = review["amount"]
        document["adjustment_reason"] = review["reason"]
    return document


def review_shipment_amount(db: Session, shipment: Shipment, document: dict,
                           payload: ShipmentAmountReview, user: User) -> None:
    if shipment.status not in {"draft", "created"}:
        raise HTTPException(409, "Invoice amount can only be reviewed before shipment")
    if not document["packages_count"] or document["basis"] != payload.basis:
        raise HTTPException(409, "Scanned contents changed; reload and review again")
    if len(payload.reason.strip()) < 3:
        raise HTTPException(422, "A review reason is required")
    review = {"amount": str(payload.amount.quantize(Decimal("0.01"))), "reason": payload.reason.strip(),
              "basis": payload.basis, "reviewed_by": user.id}
    log_action(db, user, "review_shipment_amount", "Shipment", shipment.id,
               old_value={"amount": document["amount"], "review": (shipment.dispatch_snapshot or {}).get("review")},
               new_value=review)
    shipment.dispatch_snapshot = {"review": review}


def freeze_dispatch_document(db: Session, shipment: Shipment) -> None:
    document = shipment_document(db, shipment)
    if document["review_stale"]:
        raise HTTPException(409, "Scanned contents changed after amount review; review the invoice amount again")
    if document["amount"] is None and shipment.sales_order_id:
        raise HTTPException(409, "Some package prices are ambiguous; warehouse must review the invoice amount")
    shipment.dispatch_snapshot = {"document": document}


def detach_shipment_package(db: Session, shipment: Shipment, package_id: int, reason: str, user: User) -> None:
    if shipment.status not in {"draft", "created"} or len(reason.strip()) < 3:
        raise HTTPException(409, "Remove packages before dispatch with a reason")
    link = db.query(ShipmentPackage).filter_by(shipment_id=shipment.id, package_id=package_id).first()
    package = db.query(Package).filter_by(id=package_id).with_for_update().populate_existing().first()
    if not link or not package:
        raise HTTPException(404, "Package is not attached to this shipment")
    if package.status not in {"received_in_storage", "reserved"}:
        raise HTTPException(409, "Package is no longer in storage")
    rows = db.query(FinishedGoodsStock).filter_by(package_id=package_id).with_for_update().all()
    stocks = {row.id: row for row in rows}
    reservations = db.query(StockReservation).filter_by(package_id=package_id, sales_order_id=shipment.sales_order_id).with_for_update().all() if shipment.sales_order_id else []
    released = []
    for reservation in reservations:
        stock = stocks.get(reservation.finished_goods_stock_id)
        if not stock or stock.reserved_qty < reservation.quantity:
            raise HTTPException(409, "Reservation no longer matches warehouse stock")
        released.append({"reservation_id": reservation.id, "quantity": reservation.quantity})
        stock.reserved_qty -= reservation.quantity
        stock.available_qty += reservation.quantity
        stock.status = "available"
        db.delete(reservation)
    if package.status == "reserved" and all(row.reserved_qty == 0 for row in rows):
        package.status = "received_in_storage"
    db.delete(link)
    from app.models import ShipmentScanLog
    db.add(ShipmentScanLog(shipment_id=shipment.id, package_id=package_id, scanned_code=package.barcode,
                          scan_result="detached", message=reason.strip(), scanned_by=user.id))
    log_action(db, user, "detach_shipment_package", "Shipment", shipment.id,
               old_value={"package_id": package_id, "quantity": link.quantity},
               new_value={"reason": reason.strip(), "released_reservations": released})
    db.flush()
    db.expire(shipment, ["packages"])


def invoice_for_frozen_delivery(db: Session, shipment: Shipment, user: User) -> Invoice | None:
    """Post frozen commercial totals only during the explicit delivery action.

    Old shipments retain their original workflow. Mixed or incomplete evidence
    requires reconciliation, rather than guessing an order-level invoice amount.
    """
    from app.services.workflow import ensure_invoice_for_delivered_shipment
    if not shipment.sales_order_id or not (shipment.dispatch_snapshot or {}).get("document"):
        return ensure_invoice_for_delivered_shipment(db, sales_order_id=shipment.sales_order_id)
    db.query(SalesOrder).filter_by(id=shipment.sales_order_id).with_for_update().one()
    shipments = db.query(Shipment).filter(Shipment.sales_order_id == shipment.sales_order_id,
                                         Shipment.status != "cancelled").order_by(Shipment.id).all()
    amount = Decimal("0")
    for row in shipments:
        document = (row.dispatch_snapshot or {}).get("document")
        if row.status not in {"shipped", "delivered"} or not document or document.get("amount") is None:
            raise HTTPException(409, "Finance reconciliation required: order contains historical or incomplete shipment totals")
        amount += Decimal(document["amount"])
    if not amount.is_finite() or amount < 0 or amount > Decimal("999999999999.99"):
        raise HTTPException(409, "Finance reconciliation required: combined shipment amount is outside invoice limits")
    invoices = db.query(Invoice).filter_by(sales_order_id=shipment.sales_order_id).with_for_update().all()
    if len(invoices) > 1:
        raise HTTPException(409, "Finance reconciliation required: order has multiple ledger invoices")
    existing = invoices[0] if invoices else None
    if existing:
        if existing.status in {"unpaid", "paid", "partially_paid"} and Decimal(str(existing.amount)) == amount:
            return existing
        paid = db.query(Payment.id).filter_by(invoice_id=existing.id).first()
        if existing.status != "unpaid" or paid:
            raise HTTPException(409, "Finance reconciliation required: invoice is paid, partially paid or has payment records")
    invoice = existing or ensure_invoice_for_delivered_shipment(db, sales_order_id=shipment.sales_order_id)
    previous_amount = str(invoice.amount)
    invoice.amount = amount.quantize(Decimal("0.01"))
    db.flush()
    log_action(db, user, "reconcile_frozen_shipment_invoice", "Invoice", invoice.id,
               old_value={"amount": previous_amount, "existing_invoice": bool(existing)},
               new_value={"amount": str(invoice.amount), "shipment_ids": [row.id for row in shipments],
                          "source": "frozen_dispatch_totals"})
    return invoice
