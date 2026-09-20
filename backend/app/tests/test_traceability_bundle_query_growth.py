from datetime import datetime, timedelta, timezone
from math import ceil
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.db.session import SessionLocal
from app.models import (
    Bundle,
    BundleScanLog,
    Department,
    Model,
    Package,
    PackageItem,
    ProductionBatch,
    ProductionOrder,
)
from app.services.traceability import build_traceability


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


def _bundle_case(db, bundle_count):
    suffix = uuid4().hex[:8].upper()
    model_id = db.query(Model.id).order_by(Model.id).first()[0]
    order = ProductionOrder(
        production_no=f"PERF21-PO-{suffix}",
        production_type="branded_stock",
        model_id=model_id,
        status="sewing",
        planned_quantity=bundle_count,
    )
    departments = [
        Department(name=f"PERF21 department {suffix} {number}", code=f"P21{suffix[:5]}{number:04d}")
        for number in range(bundle_count)
    ]
    db.add_all([order, *departments])
    db.flush()
    bundles = [
        Bundle(
            bundle_no=f"PERF21-B-{suffix}-{number:04d}",
            barcode=f"PERF21-BC-{suffix}-{number:04d}",
            production_order_id=order.id,
            model_id=model_id,
            color="navy",
            size="M",
            quantity=1,
            current_department_id=department.id,
            status="received_sewing",
        )
        for number, department in enumerate(departments)
    ]
    db.add_all(bundles)
    db.flush()
    started = datetime(2098, 9, 1, tzinfo=timezone.utc)
    db.add_all([
        BundleScanLog(
            bundle_id=bundle.id,
            scan_type="received_sewing",
            to_department_id=department.id,
            location=f"Line {number}",
            scanned_at=started + timedelta(seconds=number),
        )
        for number, (bundle, department) in enumerate(zip(bundles, departments, strict=True))
    ])
    db.commit()
    return {
        "order_id": order.id,
        "bundle_ids": [bundle.id for bundle in bundles],
        "department_names": [department.name for department in departments],
    }


@pytest.mark.parametrize("bundle_count", [1, 50, 401])
def test_traceability_batches_bundle_department_names(bundle_count):
    with SessionLocal() as db:
        case = _bundle_case(db, bundle_count)

    with SessionLocal() as db:
        order = db.get(ProductionOrder, case["order_id"])
        payload, statements = _select_trace(
            db,
            lambda: build_traceability(
                db,
                subject_type="production_order",
                production_order=order,
            ),
        )

    department_selects = sum(" from departments " in statement for statement in statements)
    assert department_selects == ceil(bundle_count / 400), {
        "departments": department_selects,
        "total": len(statements),
    }
    assert len(statements) == 8 + ceil(bundle_count / 400)
    assert [row["id"] for row in payload["bundles"]] == case["bundle_ids"]
    assert [row["current_department_name"] for row in payload["bundles"]] == case["department_names"]
    assert all(row["next_department_id"] is None for row in payload["bundles"])
    assert [row["scan_logs"][0]["scan_type"] for row in payload["bundles"]] == [
        "received_sewing",
    ] * bundle_count


def test_traceability_bundle_department_map_preserves_strict_batch_scope_and_scan_order():
    with SessionLocal() as db:
        suffix = uuid4().hex[:8].upper()
        model_id = db.query(Model.id).order_by(Model.id).first()[0]
        current = Department(name=f"PERF21 current {suffix}", code=f"P21C{suffix[:7]}")
        following = Department(name=f"PERF21 next {suffix}", code=f"P21N{suffix[:7]}")
        order = ProductionOrder(
            production_no=f"PERF21-S-PO-{suffix}", production_type="branded_stock",
            model_id=model_id, status="sewing", planned_quantity=20,
        )
        db.add_all([current, following, order])
        db.flush()
        batches = [
            ProductionBatch(
                production_order_id=order.id,
                batch_no=f"PERF21-PB-{suffix}-{number}",
                batch_index=number + 1,
                planned_quantity=10,
            )
            for number in range(2)
        ]
        db.add_all(batches)
        db.flush()
        target = Bundle(
            bundle_no=f"PERF21-S-B-{suffix}-0", barcode=f"PERF21-S-BC-{suffix}-0",
            production_order_id=order.id, production_batch_id=batches[0].id,
            model_id=model_id, color="black", size="L", quantity=10,
            current_department_id=current.id, next_department_id=following.id,
            status="received_sewing",
        )
        excluded = Bundle(
            bundle_no=f"PERF21-S-B-{suffix}-1", barcode=f"PERF21-S-BC-{suffix}-1",
            production_order_id=order.id, production_batch_id=batches[1].id,
            model_id=model_id, color="white", size="S", quantity=10,
            status="created",
        )
        db.add_all([target, excluded])
        db.flush()
        later = datetime(2098, 9, 2, 12, 0, tzinfo=timezone.utc)
        db.add_all([
            BundleScanLog(
                bundle_id=target.id, scan_type="received_sewing",
                to_department_id=current.id, scanned_at=later,
            ),
            BundleScanLog(
                bundle_id=target.id, scan_type="sent_sewing",
                from_department_id=current.id, to_department_id=following.id,
                scanned_at=later - timedelta(hours=1),
            ),
        ])
        db.commit()
        ids = {"order": order.id, "batch": batches[0].id, "bundle": target.id}

    with SessionLocal() as db:
        payload = build_traceability(
            db,
            subject_type="production_batch",
            production_order=db.get(ProductionOrder, ids["order"]),
            production_batch_id=ids["batch"],
        )

    assert [row["id"] for row in payload["bundles"]] == [ids["bundle"]]
    bundle = payload["bundles"][0]
    assert bundle["current_department_name"] == current.name
    assert bundle["next_department_name"] == following.name
    assert [row["scan_type"] for row in bundle["scan_logs"]] == ["sent_sewing", "received_sewing"]
    assert "Bundle history missing sewing receive scan" not in payload["gaps"]


def test_traceability_bundle_batching_preserves_package_variant_match_and_fallback():
    with SessionLocal() as db:
        suffix = uuid4().hex[:8].upper()
        model_id = db.query(Model.id).order_by(Model.id).first()[0]
        department = Department(name=f"PERF21 package {suffix}", code=f"P21P{suffix[:7]}")
        order = ProductionOrder(
            production_no=f"PERF21-P-PO-{suffix}", production_type="branded_stock",
            model_id=model_id, status="sewing", planned_quantity=20,
        )
        db.add_all([department, order])
        db.flush()
        bundles = [
            Bundle(
                bundle_no=f"PERF21-P-B-{suffix}-{number}",
                barcode=f"PERF21-P-BC-{suffix}-{number}",
                production_order_id=order.id, model_id=model_id,
                color=color, size=size, quantity=10,
                current_department_id=department.id if number == 0 else None,
                status="received_sewing",
            )
            for number, (color, size) in enumerate((("black", "M"), ("white", "L")))
        ]
        packages = [
            Package(
                package_no=f"PERF21-P-PKG-{suffix}-{number}",
                barcode=f"PERF21-P-PBC-{suffix}-{number}",
                production_order_id=order.id, model_id=model_id,
                color=color, total_quantity=10, capacity=20, status="packed",
            )
            for number, color in enumerate(("black", "green"))
        ]
        db.add_all([*bundles, *packages])
        db.flush()
        db.add_all([
            PackageItem(
                package_id=packages[0].id, model_id=model_id,
                color="black", size="M", quantity=10,
            ),
            PackageItem(
                package_id=packages[1].id, model_id=model_id,
                color="green", size="XL", quantity=10,
            ),
        ])
        db.commit()
        ids = {
            "matching_package": packages[0].id,
            "fallback_package": packages[1].id,
            "bundles": [bundle.id for bundle in bundles],
            "department_name": department.name,
        }

    with SessionLocal() as db:
        matched = build_traceability(
            db,
            subject_type="package",
            production_order=None,
            package=db.get(Package, ids["matching_package"]),
        )
    with SessionLocal() as db:
        fallback = build_traceability(
            db,
            subject_type="package",
            production_order=None,
            package=db.get(Package, ids["fallback_package"]),
        )

    assert [row["id"] for row in matched["bundles"]] == ids["bundles"][:1]
    assert matched["bundles"][0]["current_department_name"] == ids["department_name"]
    assert [row["id"] for row in fallback["bundles"]] == ids["bundles"]
