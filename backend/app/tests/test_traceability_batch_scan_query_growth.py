from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.db.session import SessionLocal
from app.models import (
    Model,
    Package,
    PackageBatchAllocation,
    PackageScanLog,
    ProductionBatch,
    ProductionOrder,
)
from app.services.traceability import _batch_packages, _package_scans


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


def _batch_case(db, package_count):
    suffix = uuid4().hex[:8].upper()
    model_id = db.query(Model.id).order_by(Model.id).first()[0]
    order = ProductionOrder(
        production_no=f"PERF21-BS-PO-{suffix}",
        production_type="branded_stock",
        model_id=model_id,
        status="packaging",
        planned_quantity=package_count,
    )
    db.add(order)
    db.flush()
    batch = ProductionBatch(
        production_order_id=order.id,
        batch_no=f"PERF21-BS-B-{suffix}",
        batch_index=1,
        planned_quantity=package_count,
    )
    db.add(batch)
    db.flush()
    packages = [
        Package(
            package_no=f"PERF21-BS-P-{suffix}-{number:04d}",
            barcode=f"PERF21-BS-BC-{suffix}-{number:04d}",
            production_order_id=order.id,
            model_id=model_id,
            color="navy",
            total_quantity=1,
            capacity=1,
            status="packed",
        )
        for number in range(package_count)
    ]
    db.add_all(packages)
    db.flush()
    allocations = [
        PackageBatchAllocation(
            package_id=package.id,
            production_batch_id=batch.id,
            quantity=1,
        )
        for package in packages
    ]
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    scans = [
        PackageScanLog(
            package_id=package.id,
            scan_type="created",
            location=f"cell-{number}",
            scanned_at=base_time + timedelta(seconds=number),
        )
        for number, package in enumerate(packages)
    ]
    db.add_all([*allocations, *scans])
    db.commit()
    return {
        "batch_id": batch.id,
        "order_id": order.id,
        "package_ids": [package.id for package in packages],
        "scan_ids": [scan.id for scan in scans],
    }


@pytest.mark.parametrize("package_count", [1, 50, 401])
def test_batch_package_scans_are_bulk_loaded_at_graph_boundaries(package_count):
    with SessionLocal() as db:
        case = _batch_case(db, package_count)

    with SessionLocal() as db:
        def load_graph_slice():
            packages, quantities = _batch_packages(db, case["batch_id"], case["order_id"])
            scans = [scan for package in packages for scan in _package_scans(package)]
            return packages, quantities, scans

        (packages, quantities, scans), statements = _select_trace(db, load_graph_slice)

    scan_queries = [statement for statement in statements if " from package_scan_logs " in statement]
    assert len(scan_queries) == 1, statements
    assert len(statements) == 3, statements
    assert [package.id for package in packages] == case["package_ids"]
    assert quantities == {package_id: 1 for package_id in case["package_ids"]}
    assert [scan["id"] for scan in scans] == case["scan_ids"]


def test_batch_package_scan_bulk_load_preserves_direct_and_allocated_precedence_and_order():
    with SessionLocal() as db:
        suffix = uuid4().hex[:8].upper()
        model_id = db.query(Model.id).order_by(Model.id).first()[0]
        order = ProductionOrder(
            production_no=f"PERF21-BS-SPO-{suffix}",
            production_type="branded_stock",
            model_id=model_id,
            status="packaging",
            planned_quantity=13,
        )
        db.add(order)
        db.flush()
        batch = ProductionBatch(
            production_order_id=order.id,
            batch_no=f"PERF21-BS-SB-{suffix}",
            batch_index=1,
            planned_quantity=13,
        )
        db.add(batch)
        db.flush()
        allocated = Package(
            package_no=f"PERF21-BS-SP-{suffix}-A",
            barcode=f"PERF21-BS-SBC-{suffix}-A",
            production_order_id=order.id,
            model_id=model_id,
            color="navy",
            total_quantity=9,
            capacity=10,
            status="packed",
        )
        overlap = Package(
            package_no=f"PERF21-BS-SP-{suffix}-O",
            barcode=f"PERF21-BS-SBC-{suffix}-O",
            production_order_id=order.id,
            production_batch_id=batch.id,
            model_id=model_id,
            color="navy",
            total_quantity=8,
            capacity=10,
            status="packed",
        )
        direct = Package(
            package_no=f"PERF21-BS-SP-{suffix}-D",
            barcode=f"PERF21-BS-SBC-{suffix}-D",
            production_order_id=order.id,
            production_batch_id=batch.id,
            model_id=model_id,
            color="navy",
            total_quantity=6,
            capacity=10,
            status="packed",
        )
        db.add_all([allocated, overlap, direct])
        db.flush()
        db.add_all(
            [
                PackageBatchAllocation(
                    package_id=allocated.id,
                    production_batch_id=batch.id,
                    quantity=4,
                ),
                PackageBatchAllocation(
                    package_id=overlap.id,
                    production_batch_id=batch.id,
                    quantity=3,
                ),
            ]
        )
        later = datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)
        earlier = later - timedelta(hours=1)
        db.add_all(
            [
                PackageScanLog(
                    package_id=allocated.id,
                    scan_type="received",
                    location="B",
                    scanned_at=later,
                ),
                PackageScanLog(
                    package_id=allocated.id,
                    scan_type="created",
                    location="A",
                    scanned_at=earlier,
                ),
                PackageScanLog(
                    package_id=direct.id,
                    scan_type="created",
                    location="C",
                    scanned_at=earlier,
                ),
            ]
        )
        db.commit()
        case = {
            "batch_id": batch.id,
            "order_id": order.id,
            "package_ids": sorted([allocated.id, overlap.id, direct.id]),
            "quantities": {allocated.id: 4, overlap.id: 3, direct.id: 6},
            "allocated_id": allocated.id,
        }

    with SessionLocal() as db:
        def load_graph_slice():
            packages, quantities = _batch_packages(db, case["batch_id"], case["order_id"])
            scans = {package.id: _package_scans(package) for package in packages}
            return packages, quantities, scans

        (packages, quantities, scans), statements = _select_trace(db, load_graph_slice)

    scan_queries = [statement for statement in statements if " from package_scan_logs " in statement]
    assert len(scan_queries) == 2, statements
    assert [package.id for package in packages] == case["package_ids"]
    assert quantities == case["quantities"]
    assert [scan["scan_type"] for scan in scans[case["allocated_id"]]] == ["created", "received"]
