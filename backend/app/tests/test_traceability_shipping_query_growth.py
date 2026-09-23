from math import ceil
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.db.session import SessionLocal
from app.models import Customer, Model, Package, ProductionOrder, SalesOrder, Shipment, ShipmentPackage, Warehouse
from app.services import traceability


def _select_trace(db, callback):
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().lower().startswith("select"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(db.bind, "before_cursor_execute", capture)
    try:
        result = callback()
    finally:
        event.remove(db.bind, "before_cursor_execute", capture)
    return result, statements


def _reference_counts(statements):
    return {
        "warehouses": sum(" from warehouses " in statement for statement in statements),
        "sales_orders": sum(" from sales_orders " in statement for statement in statements),
        "customers": sum(" from customers " in statement for statement in statements),
        "total": len(statements),
    }


def _shipping_case(db, row_count):
    suffix = uuid4().hex[:8].upper()
    model_id = db.query(Model.id).order_by(Model.id).first()[0]
    production_order = ProductionOrder(
        production_no=f"PERF21-S-PO-{suffix}",
        production_type="branded_stock",
        model_id=model_id,
        status="packaging",
        planned_quantity=row_count,
    )
    warehouses = [
        Warehouse(name=f"PERF21 ship warehouse {suffix} {number}", type="finished_goods")
        for number in range(row_count)
    ]
    customers = [Customer(name=f"PERF21 ship customer {suffix} {number}") for number in range(row_count)]
    db.add_all([production_order, *warehouses, *customers])
    db.flush()
    orders = [
        SalesOrder(
            order_no=f"PERF21-S-SO-{suffix}-{number:04d}",
            customer_id=customer.id,
            status="confirmed",
        )
        for number, customer in enumerate(customers)
    ]
    packages = [
        Package(
            package_no=f"PERF21-S-PKG-{suffix}-{number:04d}",
            barcode=f"PERF21-S-BC-{suffix}-{number:04d}",
            production_order_id=production_order.id,
            model_id=model_id,
            color=f"color-{number}",
            total_quantity=1,
            capacity=1,
            warehouse_id=warehouse.id,
            status="received_in_storage",
        )
        for number, warehouse in enumerate(warehouses)
    ]
    db.add_all([*orders, *packages])
    db.flush()
    shipments = [
        Shipment(
            shipment_no=f"PERF21-S-SH-{suffix}-{number:04d}",
            sales_order_id=order.id,
            customer_id=customer.id,
            status="created",
        )
        for number, (order, customer) in enumerate(zip(orders, customers, strict=True))
    ]
    db.add_all(shipments)
    db.commit()
    return {
        "package_ids": [row.id for row in packages],
        "shipment_ids": [row.id for row in shipments],
        "warehouse_names": [row.name for row in warehouses],
        "order_nos": [row.order_no for row in orders],
        "customer_names": [row.name for row in customers],
    }


@pytest.mark.parametrize("row_count", [1, 50, 401])
def test_traceability_batches_package_and_shipment_references(row_count):
    with SessionLocal() as db:
        case = _shipping_case(db, row_count)

    with SessionLocal() as db:
        packages = db.query(Package).filter(Package.id.in_(case["package_ids"])).order_by(Package.id).all()
        package_payloads, package_statements = _select_trace(
            db,
            lambda: traceability._package_payloads(db, packages),
        )

    with SessionLocal() as db:
        shipments = db.query(Shipment).filter(Shipment.id.in_(case["shipment_ids"])).order_by(Shipment.id).all()
        shipment_payloads, shipment_statements = _select_trace(
            db,
            lambda: traceability._shipment_payloads(db, shipments),
        )

    expected_chunks = ceil(row_count / 400)
    package_counts = _reference_counts(package_statements)
    shipment_counts = _reference_counts(shipment_statements)
    assert package_counts == {
        "warehouses": expected_chunks,
        "sales_orders": 0,
        "customers": 0,
        "total": expected_chunks,
    }
    assert shipment_counts == {
        "warehouses": 0,
        "sales_orders": expected_chunks,
        "customers": expected_chunks,
        "total": 2 * expected_chunks,
    }
    assert [row["warehouse_name"] for row in package_payloads] == case["warehouse_names"]
    assert [row["sales_order_no"] for row in shipment_payloads] == case["order_nos"]
    assert [row["customer_name"] for row in shipment_payloads] == case["customer_names"]


@pytest.mark.parametrize("package_count", [1, 50, 401])
def test_shipment_traceability_reuses_package_warehouse_map(package_count):
    with SessionLocal() as db:
        suffix = uuid4().hex[:8].upper()
        model_id = db.query(Model.id).order_by(Model.id).first()[0]
        production_order = ProductionOrder(
            production_no=f"PERF21-S-WPO-{suffix}",
            production_type="branded_stock",
            model_id=model_id,
            status="packaging",
            planned_quantity=package_count,
        )
        warehouses = [
            Warehouse(name=f"PERF21 ship reuse warehouse {suffix} {number}", type="finished_goods")
            for number in range(package_count)
        ]
        db.add_all([production_order, *warehouses])
        db.flush()
        packages = [
            Package(
                package_no=f"PERF21-S-WPKG-{suffix}-{number:04d}",
                barcode=f"PERF21-S-WBC-{suffix}-{number:04d}",
                production_order_id=production_order.id,
                model_id=model_id,
                color="navy",
                total_quantity=1,
                capacity=1,
                warehouse_id=warehouse.id,
                status="shipped",
            )
            for number, warehouse in enumerate(warehouses)
        ]
        shipment = Shipment(shipment_no=f"PERF21-S-WSH-{suffix}", status="shipped")
        db.add_all([shipment, *packages])
        db.flush()
        db.add_all(
            ShipmentPackage(shipment_id=shipment.id, package_id=package.id, quantity=1)
            for package in packages
        )
        db.commit()
        shipment_id = shipment.id
        expected_names = [warehouse.name for warehouse in warehouses]

    with SessionLocal() as db:
        shipment = db.get(Shipment, shipment_id)
        payload, statements = _select_trace(db, lambda: traceability.shipment_traceability(db, shipment))

    warehouse_queries = [statement for statement in statements if " from warehouses " in statement]
    assert len(warehouse_queries) == ceil(package_count / 400), statements
    assert sum(" from package_items " in statement for statement in statements) == 1, statements
    assert sum(" from package_scan_logs " in statement for statement in statements) == 1, statements
    assert sum(" from package_batch_allocations " in statement for statement in statements) == 1, statements
    assert len(payload["packages"]) == package_count
    assert [row["warehouse_name"] for row in payload["packages"]] == expected_names
    assert payload["shipment"]["shipment_no"].endswith(suffix)


def test_traceability_shipping_maps_match_scalar_precedence_missing_and_order():
    with SessionLocal() as db:
        suffix = uuid4().hex[:8].upper()
        model_id = db.query(Model.id).order_by(Model.id).first()[0]
        production_order = ProductionOrder(
            production_no=f"PERF21-S-SPO-{suffix}",
            production_type="branded_stock",
            model_id=model_id,
            status="packaging",
            planned_quantity=4,
        )
        warehouse = Warehouse(name=f"PERF21 semantic warehouse {suffix}", type="finished_goods")
        direct = Customer(name=f"PERF21 direct customer {suffix}")
        fallback = Customer(name=f"PERF21 fallback customer {suffix}")
        db.add_all([production_order, warehouse, direct, fallback])
        db.flush()
        order = SalesOrder(
            order_no=f"PERF21-S-SSO-{suffix}",
            customer_id=fallback.id,
            status="confirmed",
        )
        packages = [
            Package(
                package_no=f"PERF21-S-SPKG-{suffix}-{number}",
                barcode=f"PERF21-S-SBC-{suffix}-{number}",
                production_order_id=production_order.id,
                model_id=model_id,
                color="navy",
                total_quantity=1,
                capacity=1,
                warehouse_id=warehouse.id if number != 1 else None,
                status="received_in_storage",
            )
            for number in range(2)
        ]
        db.add_all([order, *packages])
        db.flush()
        shipments = [
            Shipment(
                shipment_no=f"PERF21-S-SSH-{suffix}-0",
                sales_order_id=order.id,
                customer_id=direct.id,
                status="created",
            ),
            Shipment(
                shipment_no=f"PERF21-S-SSH-{suffix}-1",
                sales_order_id=order.id,
                customer_id=None,
                status="created",
            ),
            Shipment(
                shipment_no=f"PERF21-S-SSH-{suffix}-2",
                sales_order_id=None,
                customer_id=direct.id,
                status="created",
            ),
            Shipment(
                shipment_no=f"PERF21-S-SSH-{suffix}-3",
                sales_order_id=None,
                customer_id=None,
                status="created",
            ),
        ]
        db.add_all(shipments)
        db.commit()
        package_ids = [row.id for row in packages]
        shipment_ids = [row.id for row in shipments]
        warehouse_name = warehouse.name
        direct_name = direct.name
        fallback_name = fallback.name

    with SessionLocal() as db:
        packages = [db.get(Package, row_id) for row_id in package_ids]
        shipments = [db.get(Shipment, row_id) for row_id in shipment_ids]
        scalar_packages = [traceability._package_payload(db, row) for row in packages]
        scalar_shipments = [traceability._shipment_payload(db, row) for row in shipments]

    with SessionLocal() as db:
        packages = [db.get(Package, row_id) for row_id in package_ids]
        shipments = [db.get(Shipment, row_id) for row_id in shipment_ids]
        batched_packages = traceability._package_payloads(db, packages)
        batched_shipments = traceability._shipment_payloads(db, shipments)
        unknown_package, unknown_package_statements = _select_trace(
            db,
            lambda: traceability._package_payload(db, packages[0], warehouses={}),
        )
        unknown_shipment, unknown_shipment_statements = _select_trace(
            db,
            lambda: traceability._shipment_payload(
                db,
                shipments[0],
                sales_orders={},
                customers={},
            ),
        )
        sales_orders, customers = traceability._shipment_reference_maps(db, shipments)
        shipments[0].customer_id = 0
        zero_override = traceability._shipment_payload(
            db,
            shipments[0],
            sales_orders=sales_orders,
            customers=customers,
        )

    assert batched_packages == scalar_packages
    assert batched_shipments == scalar_shipments
    assert [row["warehouse_name"] for row in batched_packages] == [warehouse_name, None]
    assert [row["customer_name"] for row in batched_shipments] == [
        direct_name,
        fallback_name,
        direct_name,
        None,
    ]
    assert [row["shipment_no"] for row in batched_shipments] == [
        f"PERF21-S-SSH-{suffix}-{number}" for number in range(4)
    ]
    assert unknown_package["warehouse_name"] is None
    assert unknown_shipment["sales_order_no"] is None
    assert unknown_shipment["customer_name"] is None
    assert unknown_package_statements == unknown_shipment_statements == []
    assert zero_override["customer_name"] == fallback_name
