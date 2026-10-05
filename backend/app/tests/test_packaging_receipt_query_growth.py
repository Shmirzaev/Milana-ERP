from uuid import uuid4

import pytest
from fastapi.encoders import jsonable_encoder
from sqlalchemy import event

from app.api.routes import production as production_routes
from app.models import (
    Bundle,
    Department,
    Model,
    PackagingReceipt,
    ProductionBatch,
    ProductionOrder,
    SalesOrder,
    WorkOrder,
)
from app.tests.conftest import TestSessionLocal, test_engine


def _seed_receipts(receipt_count: int, *, include_optional_refs: bool = True) -> list[int]:
    marker = uuid4().hex[:8]
    with TestSessionLocal() as db:
        packaging_department = db.query(Department).filter(Department.code == "PKG").one()
        sewing_department = db.query(Department).filter(Department.code == "SEW").one()
        models = [
            Model(
                code=f"PERF20-R-{marker}-{index:04d}",
                name=f"Receipt model {index}",
                product_type="shirt",
            )
            for index in range(receipt_count)
        ]
        db.add_all(models)
        db.flush()
        sales_orders = [
            SalesOrder(
                order_no=f"PERF20-R-SO-{marker}-{index:04d}",
                order_type="client_order",
                status="production",
                total_amount=0,
            )
            for index in range(receipt_count)
        ]
        db.add_all(sales_orders)
        db.flush()
        orders = [
            ProductionOrder(
                production_no=f"PERF20-R-PO-{marker}-{index:04d}",
                production_type="client_order",
                sales_order_id=sales_orders[index].id,
                model_id=models[index].id,
                planned_quantity=1,
                status="packaging",
            )
            for index in range(receipt_count)
        ]
        db.add_all(orders)
        db.flush()
        batches = [
            ProductionBatch(
                production_order_id=orders[index].id,
                batch_no=f"R-{index:04d}",
                batch_index=1,
                name=f"Receipt batch {index}",
                planned_quantity=1,
            )
            for index in range(receipt_count)
        ]
        db.add_all(batches)
        db.flush()
        source_orders = [
            WorkOrder(
                production_order_id=orders[index].id,
                production_batch_id=batches[index].id,
                department_id=sewing_department.id,
                operation="sewing",
                planned_input_qty=1,
                planned_output_qty=1,
                status="completed",
            )
            for index in range(receipt_count)
        ]
        target_orders = [
            WorkOrder(
                production_order_id=orders[index].id,
                production_batch_id=batches[index].id,
                department_id=packaging_department.id,
                operation="packaging",
                planned_input_qty=1,
                planned_output_qty=1,
                status="collected",
            )
            for index in range(receipt_count)
        ]
        db.add_all([*source_orders, *target_orders])
        db.flush()
        bundles = [
            Bundle(
                bundle_no=f"PERF20-R-BND-{marker}-{index:04d}",
                barcode=f"PERF20-R-BC-{marker}-{index:04d}",
                production_order_id=orders[index].id,
                production_batch_id=batches[index].id,
                model_id=models[index].id,
                color=f"color-{index}",
                size=f"S{index}",
                quantity=1,
                status="received_sewing",
            )
            for index in range(receipt_count)
        ]
        db.add_all(bundles)
        db.flush()
        receipts = [
            PackagingReceipt(
                packaging_department_code="PKG",
                work_order_id=target_orders[index].id,
                source_work_order_id=source_orders[index].id,
                production_order_id=orders[index].id,
                production_batch_id=(
                    batches[index].id
                    if include_optional_refs or index != 0
                    else None
                ),
                bundle_id=(
                    bundles[index].id
                    if include_optional_refs or index != 0
                    else None
                ),
                quantity=1,
                receive_method="scan" if include_optional_refs or index != 0 else "manual",
            )
            for index in range(receipt_count)
        ]
        db.add_all(receipts)
        db.commit()
        return [int(receipt.id) for receipt in receipts]


def _captured_receipts(client, auth_headers, receipt_count: int):
    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(test_engine, "before_cursor_execute", capture)
    try:
        response = client.get(
            f"/api/packaging/receipts?limit={receipt_count}",
            headers=auth_headers,
        )
    finally:
        event.remove(test_engine, "before_cursor_execute", capture)
    return response, statements


@pytest.mark.parametrize(
    ("receipt_count", "expected_rows"),
    [(1, 1), (50, 50), (401, 200)],
)
def test_packaging_receipt_list_batches_reference_reads(
    client,
    auth_headers,
    receipt_count,
    expected_rows,
):
    receipt_ids = _seed_receipts(receipt_count)

    response, statements = _captured_receipts(client, auth_headers, receipt_count)

    assert response.status_code == 200, response.text
    assert len(response.json()) == expected_rows
    assert [row["id"] for row in response.json()] == sorted(receipt_ids, reverse=True)[:expected_rows]
    receipt_reference_reads = [
        statement
        for statement in statements
        if any(
            f" from {table} " in statement
            for table in (
                "packaging_receipts",
                "production_orders",
                "production_batches",
                "bundles",
                "models",
                "sales_orders",
            )
        )
    ]
    print(
        f"Packaging receipts {receipt_count}: "
        f"{len(statements)} total SELECTs, {len(receipt_reference_reads)} receipt/reference reads"
    )
    assert len(receipt_reference_reads) == 1


def test_packaging_receipt_list_matches_scalar_payload_and_is_read_only(client, auth_headers):
    receipt_ids = _seed_receipts(3, include_optional_refs=False)
    with TestSessionLocal() as db:
        rows = (
            db.query(PackagingReceipt)
            .filter(PackagingReceipt.id.in_(receipt_ids))
            .order_by(PackagingReceipt.id.desc())
            .all()
        )
        expected = [
            jsonable_encoder(production_routes._packaging_receipt_payload(db, row))
            for row in rows
        ]
        before_count = db.query(PackagingReceipt).count()

    response = client.get("/api/packaging/receipts?limit=3", headers=auth_headers)

    assert response.status_code == 200, response.text
    assert response.json() == expected
    with TestSessionLocal() as db:
        assert db.query(PackagingReceipt).count() == before_count


def test_packaging_receipt_list_failure_rolls_back_without_mutation(
    client,
    auth_headers,
    monkeypatch,
):
    receipt_ids = _seed_receipts(3)
    with TestSessionLocal() as db:
        before = [
            (row.id, row.quantity, row.receive_method)
            for row in (
                db.query(PackagingReceipt)
                .filter(PackagingReceipt.id.in_(receipt_ids))
                .order_by(PackagingReceipt.id)
                .all()
            )
        ]
    original = production_routes._packaging_receipt_payload_from_refs
    calls = 0

    def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("synthetic receipt serialization failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(
        production_routes,
        "_packaging_receipt_payload_from_refs",
        fail_second,
    )

    with pytest.raises(RuntimeError, match="synthetic receipt serialization failure"):
        client.get("/api/packaging/receipts?limit=3", headers=auth_headers)

    with TestSessionLocal() as db:
        after = [
            (row.id, row.quantity, row.receive_method)
            for row in (
                db.query(PackagingReceipt)
                .filter(PackagingReceipt.id.in_(receipt_ids))
                .order_by(PackagingReceipt.id)
                .all()
            )
        ]
    assert after == before


def test_packaging_receipt_list_rejects_unauthenticated_and_cross_factory_reads(
    client,
    auth_headers,
):
    receipt_ids = _seed_receipts(1)

    assert client.get("/api/packaging/receipts?limit=1").status_code == 401
    forbidden = client.get(
        "/api/packaging/receipts?limit=1&packaging_department_code=BPK",
        headers=auth_headers,
    )
    assert forbidden.status_code == 403
    with TestSessionLocal() as db:
        assert db.query(PackagingReceipt).filter(PackagingReceipt.id.in_(receipt_ids)).count() == 1
