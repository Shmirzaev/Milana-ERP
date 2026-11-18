from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.libs.enums.ceo_dashboard import FactoryFilter
from app.models.ceo_dashboard_balance_service import read_live_balances
from app.schemas import (
    Bundle, BundleScanLog, Customer, Department, FinishedGoodsStock, Item, Model, Package, PackageItem,
    PackagePrintRun, PackagePrintRunMember, PackageScanLog, PackagingRecord, PrintingRecord,
    ProductionBatch, ProductionOrder, SalesOrder, SewingRecord, Shipment, ShipmentPackage,
    StockBatch, StockMovement, StockReservation, User, Warehouse, WarehousePackReservation, WorkOrder,
)
from app.schemas.inventory.eco_inventory import EcoMaterialBatch


START = datetime(2026, 11, 17, 4, tzinfo=timezone.utc)
AS_OF = START + timedelta(days=1)


def add(db, cls, **values):
    row = cls(**values)
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def balances_db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def production(db, *, service=False):
    model = add(db, Model, code=f"MODEL-{service}", name="Shirt")
    order = add(db, ProductionOrder, production_no=f"PRODUCTION-{service}", model_id=model.id,
                production_type="client_order", source_type="usluga" if service else "standard")
    return model.id, order.id


def work(db, order, batch, department, operation):
    return add(db, WorkOrder, production_order_id=order, production_batch_id=batch,
               department_id=department, operation=operation)


def test_waiting_uses_physical_handoffs_and_known_ages(balances_db):
    db = balances_db
    dept = {code: add(db, Department, name=code, code=code).id for code in ("CUT", "ECT", "PRT", "MIL", "BST", "BPK")}
    model, order = production(db)
    _, service_order = production(db, service=True)
    batch = add(db, ProductionBatch, production_order_id=order, batch_no="N-1")
    printing = work(db, order, batch.id, dept["PRT"], "printing")
    sewing = work(db, order, batch.id, dept["BST"], "sewing")
    sewing_packaging = work(db, order, batch.id, dept["BPK"], "packaging")
    created_at = START + timedelta(hours=1)
    print_output = START + timedelta(hours=2)
    resend_at = START + timedelta(hours=4)
    for code, state, current, target, quantity in (
        ("CUT-PRINT", "created", "ECT", "PRT", 12),
        ("CUT-SEW", "sent_to_sewing", "MIL", "MIL", 16),
        ("PRINT-SEW", "received_printing", "PRT", "BST", 10),
        ("CANCEL", "cancelled", "CUT", "PRT", 500),
    ):
        add(db, Bundle, bundle_no=code, barcode=code, production_order_id=order,
            production_batch_id=batch.id, model_id=model, color="blue", size="L",
            current_department_id=dept[current], next_department_id=dept[target],
            status=state, quantity=quantity, created_at=created_at)
    direct = db.query(Bundle).filter_by(bundle_no="CUT-SEW").one()
    add(db, BundleScanLog, bundle_id=direct.id, from_department_id=dept["CUT"],
        to_department_id=dept["MIL"], scan_type="sent_sewing", scanned_at=created_at)
    add(db, PrintingRecord, work_order_id=printing.id, passed_qty=8, rejected_qty=2, created_at=print_output)
    add(db, SewingRecord, work_order_id=sewing.id, passed_qty=12, failed_qty=2, created_at=START)
    add(db, SewingRecord, work_order_id=sewing.id, passed_qty=8, created_at=created_at)
    add(db, PackagingRecord, work_order_id=sewing_packaging.id, input_qty=5, packed_qty=5)
    for code, po, state, quantity in (
        ("PENDING", order, "packed", 5), ("SITE", order, "returned_to_packaging", 4),
        ("USLUGA", service_order, "packed", 600), ("RECEIVED", order, "received_in_storage", 80),
    ):
        add(db, Package, package_no=code, barcode=code, production_order_id=po,
            model_id=model, packaging_department_code="BPK", status=state, color="blue",
            total_quantity=quantity, packed_at=START)
    pending = db.query(Package).filter_by(package_no="PENDING").one()
    returned = db.query(Package).filter_by(package_no="SITE").one()
    add(db, PackageScanLog, package_id=pending.id, scan_type="returned_to_packaging", scanned_at=print_output)
    add(db, PackageScanLog, package_id=returned.id, scan_type="returned_to_packaging", scanned_at=print_output)
    actor = add(db, User, name="Printer", email="print@example.test", password_hash="synthetic")
    run = add(db, PackagePrintRun, run_no="R-1", code="R-1", packaging_department_code="BPK",
              package_ids=[pending.id], created_by=actor.id, created_at=resend_at)
    add(db, PackagePrintRunMember, run_id=run.id, package_id=pending.id, snapshot={})

    result = read_live_balances(db, AS_OF, FactoryFilter.ALL)
    waiting = {
        (row.source, row.destination, row.factory): (row.pieces, row.bundles, row.packs, row.oldest_since)
        for row in result.waiting
    }
    assert waiting == {
        ("ECT", "PRT", "ECO"): (12, 1, 0, created_at),
        ("CUT", "MIL", "MIL"): (16, 1, 0, created_at),
        ("PRT", "BST", "MIL"): (8, 1, 0, print_output),
        ("BST", "BPK", "BST"): (15, 0, 0, None),
        ("BPK", "FGS", "BST"): (5, 0, 1, resend_at),
        ("FGS", "BPK", "BST"): (4, 0, 1, print_output),
    }
    scoped = read_live_balances(db, AS_OF, FactoryFilter.ECO)
    assert [(row.source, row.destination) for row in scoped.waiting] == [("ECT", "PRT")]


def test_physical_warehouse_balances_keep_partial_packs_and_unique_claims(balances_db):
    db = balances_db
    model, order = production(db)
    storage = add(db, Department, code="FGS", name="Central finished goods")
    eco = add(db, Department, code="ECO", name="Eco")
    shared = add(db, Warehouse, name="Central", type="finished_goods", department_id=storage.id)
    eco_stock = add(db, Warehouse, name="Eco", type="finished_goods", department_id=eco.id)
    sales = add(db, SalesOrder, order_no="SAME-SALE")
    other = add(db, SalesOrder, order_no="DIFFERENT-SALE")
    customer = add(db, Customer, name="Customer")
    actor = add(db, User, name="Warehouse worker", email="warehouse@example.test", password_hash="synthetic")

    def package(number, warehouse_id, state, pieces, dispatched=0, received_at=None):
        return add(db, Package, production_order_id=order, model_id=model, package_no=number, barcode=number,
                   warehouse_id=warehouse_id, status=state, color="blue", total_quantity=pieces,
                   dispatched_quantity=dispatched, received_at=received_at)

    partial = package("PARTIAL", shared.id, "received_in_storage", 20, dispatched=5)
    held = package("HELD", eco_stock.id, "reserved", 9)
    package("UNASSIGNED", None, "received_in_storage", 3)
    package("UNRECEIVED_RESERVED", eco_stock.id, "reserved", 95)
    package("PACKED", shared.id, "packed", 100)
    package("SHIPPED", shared.id, "shipped", 100)
    medium = add(db, PackageItem, package_id=partial.id, model_id=model, color="blue", size="M", quantity=12)
    large = add(db, PackageItem, package_id=partial.id, model_id=model, color="blue", size="L", quantity=8)
    partial.dispatched_quantities = {str(medium.id): 5}
    row = add(db, FinishedGoodsStock, package_id=partial.id, model_id=model, color="blue", size="M",
              quantity=12, sold_qty=5, reserved_qty=6, available_qty=1)
    add(db, FinishedGoodsStock, package_id=partial.id, model_id=model, color="blue", size="L",
        quantity=8, available_qty=8)
    add(db, StockReservation, sales_order_id=sales.id, package_id=partial.id,
        finished_goods_stock_id=row.id, quantity=6)
    add(db, WarehousePackReservation, package_id=held.id, customer_id=customer.id, reserved_by=actor.id, quantity=9)
    for code, sale, status, deleted, count in (
        ("OWN", sales.id, "created", None, 7), ("OTHER", other.id, "draft", None, 3),
        ("DELETED", None, "draft", START, 15), ("DONE", None, "shipped", None, 5),
    ):
        shipment = add(db, Shipment, shipment_no=code, sales_order_id=sale, status=status, deleted_at=deleted)
        if code == "OWN":
            shipment.dispatch_snapshot = {
                "package_quantities": {str(partial.id): {str(medium.id): 4, str(large.id): 3}},
            }
        add(db, ShipmentPackage, shipment_id=shipment.id, package_id=partial.id, quantity=count)

    result = read_live_balances(db, AS_OF, FactoryFilter.ALL).warehouse
    assert (result.packs, result.pieces, result.reserved_pieces, result.available_pieces) == (3, 27, 21, 6)
    assert [(row.factory, row.packs, row.pieces, row.reserved_pieces) for row in result.by_factory] == [
        ("ECO", 1, 9, 9), ("SHARED", 1, 15, 12), ("UNASSIGNED", 1, 3, 0),
    ]
    eco_only = read_live_balances(db, AS_OF, FactoryFilter.ECO).warehouse
    assert (eco_only.packs, eco_only.pieces, eco_only.available_pieces) == (1, 9, 0)


def test_material_balances_separate_units_ledgers_and_repeated_batch_labels(balances_db):
    db = balances_db
    central = add(db, Department, name="Supply", code="STR")
    eco = add(db, Department, name="Eco", code="ECO")
    warehouse = add(db, Warehouse, name="Materials", type="fabric_storage", department_id=central.id)
    eco_warehouse = add(db, Warehouse, name="Eco stock", type="fabric_storage", department_id=eco.id)
    actor = add(db, User, name="Stock worker", email="stock@example.test", password_hash="synthetic")
    fabric = add(db, Item, sku="FAB", name="Fabric", category="fabric", unit="kg")
    labels = add(db, Item, sku="LABEL", name="Labels", category="packaging", unit="pcs")
    for item, qty, unit, archived in (
        (fabric, 5, "kg", None), (fabric, 10, "kg", None), (fabric, 90, "kg", START), (labels, 80, "pcs", None),
    ):
        add(db, StockBatch, item_id=item.id, batch_no="REPEATED", quantity=qty,
            warehouse_id=warehouse.id, unit=unit, archived_at=archived)
    first = db.query(StockBatch.id).filter_by(item_id=fabric.id, quantity=5).scalar()
    add(db, StockMovement, movement_type="issue", item_id=fabric.id, batch_id=first,
        from_warehouse_id=warehouse.id, unit="kg", quantity=3)
    add(db, StockMovement, movement_type="transfer", item_id=labels.id, unit="pcs", quantity=10,
        from_warehouse_id=warehouse.id, to_warehouse_id=eco_warehouse.id)
    for qty, details, source_batch in (
        (3, {}, first), (4, {"warehouse_id": eco_warehouse.id}, None), (0, {"warehouse_id": eco_warehouse.id}, None),
    ):
        add(db, EcoMaterialBatch, kind="fabric", item_id=fabric.id, batch_no="REPEATED",
            unit="kilogram", quantity=qty, created_by=actor.id, receipt_details=details, source_stock_batch_id=source_batch)

    result = read_live_balances(db, AS_OF, FactoryFilter.ALL)
    assert {(row.factory, row.warehouse, row.unit): (row.quantity, row.active_batches) for row in result.materials} == {
        ("SHARED", "Materials", "kg"): (Decimal(15), 2),
        ("SHARED", "Materials", "pcs"): (Decimal(70), 1),
        ("ECO", "Eco stock", "pcs"): (Decimal(10), 0),
        ("ECO", "Eco stock", "kg"): (Decimal(4), 1),
        ("ECO", "ECO_LEDGER", "kg"): (Decimal(3), 1),
    }
    assert [(row.unit, row.quantity, row.active_batches, row.varieties) for row in result.material_totals] == [
        ("kg", Decimal(22), 4, 1), ("pcs", Decimal(80), 1, 1),
    ]
    assert [(row.item, row.unit, row.quantity) for row in result.material_varieties] == [
        ("Fabric", "kg", Decimal(22)), ("Labels", "pcs", Decimal(80)),
    ]
    scoped = read_live_balances(db, AS_OF, FactoryFilter.ECO)
    assert [(row.unit, row.quantity) for row in scoped.material_totals] == [("kg", Decimal(7)), ("pcs", Decimal(10))]
