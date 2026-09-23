from datetime import date, datetime, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app.api.routes import production as production_routes
from app.models import (
    Bundle,
    CuttingRecord,
    Department,
    Model,
    Package,
    PackageBatchAllocation,
    PackagingReceipt,
    PackagingRecord,
    PrintingRecord,
    ProductionBatch,
    ProductionOrder,
    SewingAssignment,
    SewingDailyReport,
    SewingFlow,
    SewingRecord,
    SewingReplacementRequest,
    User,
    WorkOrder,
)
from app.tests.conftest import TestSessionLocal


def _base_order(scope_count: int) -> tuple[int, int]:
    marker = uuid4().hex[:8]
    with TestSessionLocal() as db:
        model = Model(code=f"PERF19-{marker}", name=f"Cutting reconciliation {marker}")
        department = Department(name=f"PERF19 {marker}", code=f"P19-{marker}")
        db.add_all([model, department])
        db.flush()
        order = ProductionOrder(
            production_no=f"PERF19-{marker}",
            production_type="branded_stock",
            model_id=model.id,
            planned_quantity=10,
            status="cutting",
        )
        db.add(order)
        db.flush()
        batches = [
            ProductionBatch(
                production_order_id=order.id,
                batch_no=f"P19-{number + 1:04d}",
                batch_index=number + 1,
                planned_quantity=number + 10,
            )
            for number in range(scope_count)
        ]
        db.add_all(batches)
        db.flush()
        work_orders = []
        for batch in batches:
            for operation in ("cutting", "packaging"):
                work_orders.append(WorkOrder(
                    production_order_id=order.id,
                    production_batch_id=batch.id,
                    department_id=department.id,
                    operation=operation,
                    status="waiting",
                    planned_input_qty=0,
                    planned_output_qty=0,
                    actual_input_qty=0,
                    actual_output_qty=0,
                    passed_qty=0,
                    failed_qty=0,
                    rework_qty=0,
                ))
        db.add_all(work_orders)
        db.commit()
        cutting_id = next(row.id for row in work_orders if row.operation == "cutting")
        return int(order.id), int(cutting_id)


def _bundle_adjustment_order(scope_count: int) -> tuple[int, int, int, int]:
    order_id, cutting_id = _base_order(scope_count)
    with TestSessionLocal() as db:
        cutting = db.get(WorkOrder, cutting_id)
        order = db.get(ProductionOrder, order_id)
        bundle = Bundle(
            bundle_no=f"PERF19-EDIT-{uuid4().hex[:8]}",
            barcode=f"PERF19-EDIT-QR-{uuid4().hex[:8]}",
            production_order_id=order_id,
            production_batch_id=cutting.production_batch_id,
            model_id=order.model_id,
            color="blue",
            size="M",
            quantity=10,
            status="created",
        )
        record = CuttingRecord(
            work_order_id=cutting.id,
            production_batch_id=cutting.production_batch_id,
            input_quantity=1,
            input_unit="kg",
            cut_pieces=10,
            passed_pieces=10,
            defective_pieces=0,
            waste_quantity=0,
            waste_unit="kg",
            layer_material_kg=0,
            beika_kg=0,
            material_rolls_used=0,
            bundle_count=1,
            total_bundled_quantity=10,
            approval_status="approved",
        )
        db.add(record)
        db.flush()
        bundle.cutting_record_id = record.id
        db.add(bundle)
        db.commit()
        return order_id, int(cutting.id), int(record.id), int(bundle.id)


@pytest.mark.parametrize("scope_count", [1, 50, 401])
def test_cutting_reconciliation_has_bounded_query_growth(scope_count):
    order_id, cutting_id = _base_order(scope_count)
    with TestSessionLocal() as db:
        cutting = db.get(WorkOrder, cutting_id)
        statements: list[str] = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)
                assert len(statements) <= 40, (
                    f"{scope_count} cutting scopes exceeded the 40-SELECT reconciliation budget"
                )

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            production_routes._reconcile_cutting_workflow_plans(db, cutting)
            db.flush()
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

        rows = db.query(WorkOrder).filter(WorkOrder.production_order_id == order_id).all()

    assert len(rows) == scope_count * 2
    assert len(statements) == 16
    normalized_statements = [" ".join(statement.lower().split()) for statement in statements]
    for table in (
        "bundles",
        "cutting_records",
        "sewing_replacement_requests",
        "printing_records",
        "sewing_records",
        "sewing_assignments",
        "sewing_daily_reports",
        "packaging_records",
        "packaging_receipts",
        "package_batch_allocations",
        "packages",
    ):
        assert any(
            f" from {table} " in statement
            and f"{table}.production_batch_id in" in statement
            for statement in normalized_statements
        ), table
    assert all(int(row.planned_input_qty) >= 10 for row in rows)
    assert all(int(row.planned_input_qty) == int(row.planned_output_qty) for row in rows)


@pytest.mark.parametrize("scope_count", [1, 50, 401])
def test_cutting_batch_quantity_validation_reuses_reconciliation_context(scope_count):
    order_id, cutting_id = _base_order(scope_count)
    with TestSessionLocal() as db:
        cutting = db.get(WorkOrder, cutting_id)
        batch_id = int(cutting.production_batch_id)
        current = db.query(User).order_by(User.id.asc()).first()
        statements: list[str] = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)
                assert len(statements) <= 22, (
                    f"{scope_count} cutting scopes exceeded the 22-SELECT batch-update budget"
                )

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            result = production_routes._update_standard_cutting_batch(
                db,
                current,
                cutting,
                batch_id,
                production_routes.CuttingBatchUpdateIn(planned_quantity=scope_count + 1000),
            )
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

        rows = db.query(WorkOrder).filter(WorkOrder.production_order_id == order_id).all()

    assert int(result["planned_quantity"]) == scope_count + 1000
    assert len(statements) == 20
    assert all(int(row.planned_input_qty) == int(row.planned_output_qty) for row in rows)


def test_cutting_batch_quantity_validation_keeps_floor_and_rolls_back():
    order_id, cutting_id = _base_order(1)
    with TestSessionLocal() as db:
        cutting = db.get(WorkOrder, cutting_id)
        batch_id = int(cutting.production_batch_id)
        order = db.get(ProductionOrder, order_id)
        db.add(Bundle(
            bundle_no=f"P19-VALIDATE-{uuid4().hex[:8]}",
            barcode=f"P19-VALIDATE-QR-{uuid4().hex[:8]}",
            production_order_id=order_id,
            production_batch_id=batch_id,
            model_id=order.model_id,
            color="blue",
            size="M",
            quantity=37,
            status="created",
        ))
        db.commit()

        cutting = db.get(WorkOrder, cutting_id)
        current = db.query(User).order_by(User.id.asc()).first()
        original_plans = {
            int(row.id): (int(row.planned_input_qty), int(row.planned_output_qty))
            for row in db.query(WorkOrder).filter(WorkOrder.production_order_id == order_id)
        }
        with pytest.raises(HTTPException) as exc_info:
            production_routes._update_standard_cutting_batch(
                db,
                current,
                cutting,
                batch_id,
                production_routes.CuttingBatchUpdateIn(planned_quantity=36),
            )
        assert exc_info.value.status_code == 409
        assert "workflow evidence (37)" in str(exc_info.value.detail)
        db.rollback()

        assert int(db.get(ProductionBatch, batch_id).planned_quantity) == 10
        refreshed_plans = {
            int(row.id): (int(row.planned_input_qty), int(row.planned_output_qty))
            for row in db.query(WorkOrder).filter(WorkOrder.production_order_id == order_id)
        }

    assert refreshed_plans == original_plans


@pytest.mark.parametrize("scope_count", [1, 50, 401])
def test_cutting_bundle_adjustment_reuses_one_scoped_evidence_read(scope_count):
    order_id, _cutting_id, record_id, bundle_id = _bundle_adjustment_order(scope_count)
    with TestSessionLocal() as db:
        current = db.query(User).order_by(User.id.asc()).first()
        statements: list[str] = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            result = production_routes.update_cutting_bundle_quantities(
                record_id,
                production_routes.CuttingBundleQuantityUpdateIn(
                    bundles=[{"id": bundle_id, "quantity": 11, "color": "navy"}],
                ),
                db,
                current,
            )
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
        rows = db.query(WorkOrder).filter(WorkOrder.production_order_id == order_id).all()

    assert result["total_bundled_quantity"] == 11
    assert result["bundles"][0]["color"] == "navy"
    assert all(int(row.planned_input_qty) == int(row.planned_output_qty) for row in rows)
    assert len(statements) == 29
    assert sum(" union all " in statement for statement in statements) == 1


def test_cutting_bundle_adjustment_downstream_rejection_rolls_back():
    order_id, cutting_id, record_id, bundle_id = _bundle_adjustment_order(1)
    with TestSessionLocal() as db:
        cutting = db.get(WorkOrder, cutting_id)
        sewing = WorkOrder(
            production_order_id=order_id,
            production_batch_id=cutting.production_batch_id,
            department_id=cutting.department_id,
            operation="sewing",
            status="in_progress",
            planned_input_qty=20,
            planned_output_qty=20,
            actual_input_qty=20,
            actual_output_qty=20,
            passed_qty=20,
            failed_qty=0,
            rework_qty=0,
        )
        db.add(sewing)
        db.flush()
        db.add(SewingRecord(
            work_order_id=sewing.id,
            production_batch_id=cutting.production_batch_id,
            input_qty=20,
            sewn_qty=20,
            passed_qty=20,
            failed_qty=0,
            rejected_qty=0,
            rework_qty=0,
        ))
        db.commit()

        current = db.query(User).order_by(User.id.asc()).first()
        with pytest.raises(HTTPException, match=r"downstream output \(20\)"):
            production_routes.update_cutting_bundle_quantities(
                record_id,
                production_routes.CuttingBundleQuantityUpdateIn(
                    bundles=[{"id": bundle_id, "quantity": 5}],
                ),
                db,
                current,
            )
        db.rollback()

        assert int(db.get(Bundle, bundle_id).quantity) == 10
        record = db.get(CuttingRecord, record_id)
        assert int(record.passed_pieces) == 10
        assert int(record.total_bundled_quantity) == 10


def _mixed_reconciliation_order() -> tuple[int, int]:
    marker = uuid4().hex[:8]
    with TestSessionLocal() as db:
        model = Model(code=f"PERF19-MIX-{marker}", name=f"Mixed reconciliation {marker}")
        department = Department(name=f"PERF19 mixed {marker}", code=f"M19-{marker}")
        flow = SewingFlow(
            factory_code="MIL",
            name=f"PERF19 flow {marker}",
            code=f"P19-{marker}",
            capacity_per_day=100,
            is_active=True,
        )
        db.add_all([model, department, flow])
        db.flush()
        order = ProductionOrder(
            production_no=f"PERF19-MIX-{marker}",
            production_type="branded_stock",
            model_id=model.id,
            planned_quantity=31,
            status="cutting",
        )
        db.add(order)
        db.flush()
        batch_a = ProductionBatch(
            production_order_id=order.id,
            batch_no="A",
            batch_index=1,
            planned_quantity=40,
        )
        batch_b = ProductionBatch(
            production_order_id=order.id,
            batch_no="B",
            batch_index=2,
            planned_quantity=50,
        )
        db.add_all([batch_a, batch_b])
        db.flush()

        def work_order(operation: str, batch_id: int | None, **values) -> WorkOrder:
            return WorkOrder(
                production_order_id=order.id,
                production_batch_id=batch_id,
                department_id=department.id,
                operation=operation,
                status=values.get("status", "waiting"),
                planned_input_qty=1,
                planned_output_qty=1,
                actual_input_qty=values.get("actual_input_qty", 0),
                actual_output_qty=values.get("actual_output_qty", 0),
                passed_qty=values.get("passed_qty", 0),
                failed_qty=values.get("failed_qty", 0),
                rework_qty=0,
                start_time=values.get("start_time"),
                end_time=values.get("end_time"),
            )

        null_cutting = work_order("cutting", None)
        null_packaging = work_order("packaging", None)
        a_cutting = work_order("cutting", batch_a.id)
        a_sewing = work_order("sewing", batch_a.id)
        a_packaging = work_order(
            "packaging",
            batch_a.id,
            status="completed",
            actual_output_qty=3,
            start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end_time=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )
        b_sewing = work_order("sewing", batch_b.id)
        b_packaging = work_order("packaging", batch_b.id, passed_qty=91, failed_qty=2)
        db.add_all([
            null_cutting,
            null_packaging,
            a_cutting,
            a_sewing,
            a_packaging,
            b_sewing,
            b_packaging,
        ])
        db.flush()

        db.add_all([
            Bundle(
                bundle_no=f"P19-N-{marker}", barcode=f"P19-N-QR-{marker}",
                production_order_id=order.id, production_batch_id=None,
                model_id=model.id, color="black", size="M", quantity=37, status="created",
            ),
            Bundle(
                bundle_no=f"P19-A-{marker}", barcode=f"P19-A-QR-{marker}",
                production_order_id=order.id, production_batch_id=batch_a.id,
                model_id=model.id, color="black", size="M", quantity=43, status="created",
            ),
            Bundle(
                bundle_no=f"P19-X-{marker}", barcode=f"P19-X-QR-{marker}",
                production_order_id=order.id, production_batch_id=batch_a.id,
                model_id=model.id, color="black", size="M", quantity=999, status="cancelled",
            ),
            Bundle(
                bundle_no=f"P19-B-{marker}", barcode=f"P19-B-QR-{marker}",
                production_order_id=order.id, production_batch_id=batch_b.id,
                model_id=model.id, color="black", size="M", quantity=53, status="created",
            ),
        ])
        db.add_all([
            CuttingRecord(
                work_order_id=null_cutting.id, production_batch_id=None,
                input_quantity=1, input_unit="kg", cut_pieces=39, passed_pieces=39,
                defective_pieces=0, waste_quantity=0, waste_unit="kg",
                layer_material_kg=0, beika_kg=0, material_rolls_used=0,
                bundle_count=0, total_bundled_quantity=0, approval_status="approved",
            ),
            CuttingRecord(
                work_order_id=a_cutting.id, production_batch_id=batch_a.id,
                input_quantity=1, input_unit="kg", cut_pieces=59, passed_pieces=59,
                defective_pieces=0, waste_quantity=0, waste_unit="kg",
                layer_material_kg=0, beika_kg=0, material_rolls_used=0,
                bundle_count=0, total_bundled_quantity=0, approval_status="approved",
            ),
            # Batch B has no cutting work order and deliberately falls back to
            # the legacy NULL-scope cutting work order.
            CuttingRecord(
                work_order_id=null_cutting.id, production_batch_id=batch_b.id,
                input_quantity=1, input_unit="kg", cut_pieces=67, passed_pieces=67,
                defective_pieces=0, waste_quantity=0, waste_unit="kg",
                layer_material_kg=0, beika_kg=0, material_rolls_used=0,
                bundle_count=0, total_bundled_quantity=0, approval_status="approved",
            ),
        ])
        b_sewing_record = SewingRecord(
            work_order_id=b_sewing.id, production_batch_id=batch_b.id,
            input_qty=71, sewn_qty=70, passed_qty=68, failed_qty=2,
            rejected_qty=1, rework_qty=0,
        )
        db.add_all([
            PrintingRecord(
                work_order_id=a_packaging.id, production_batch_id=batch_a.id,
                input_qty=61, printed_qty=60, passed_qty=58, rejected_qty=2,
            ),
            b_sewing_record,
            PackagingRecord(
                work_order_id=null_packaging.id, production_batch_id=None,
                input_qty=41, packed_qty=39, damaged_qty=2,
                package_count=1, total_packed_quantity=40,
            ),
            PackagingReceipt(
                packaging_department_code="PKG",
                work_order_id=a_packaging.id,
                source_work_order_id=a_cutting.id,
                production_order_id=order.id,
                production_batch_id=batch_a.id,
                quantity=63,
                receive_method="manual",
            ),
            SewingDailyReport(
                report_date=date(2026, 1, 1), sewing_flow_id=flow.id,
                work_order_id=b_sewing.id, production_order_id=order.id,
                production_batch_id=batch_b.id, line_code=flow.code,
                line_name=flow.name, sewn_qty=73, defective_qty=0,
            ),
        ])
        db.flush()
        db.add_all([
            SewingReplacementRequest(
                production_order_id=order.id,
                sewing_work_order_id=b_sewing.id,
                cutting_work_order_id=a_cutting.id,
                production_batch_id=batch_a.id,
                sewing_record_id=b_sewing_record.id,
                requested_qty=7,
                cut_qty=5,
                replaced_qty=0,
                status="waiting_sewing",
            ),
            SewingAssignment(
                work_order_id=a_sewing.id,
                production_batch_id=batch_a.id,
                sewing_flow_id=flow.id,
                quantity=65,
                completed_qty=64,
                status="in_progress",
            ),
        ])
        direct_a = Package(
            package_no=f"P19-PA-{marker}", barcode=f"P19-PA-QR-{marker}",
            production_order_id=order.id, production_batch_id=batch_a.id,
            model_id=model.id, color="black", total_quantity=66, capacity=100, status="packed",
        )
        allocated = Package(
            package_no=f"P19-PX-{marker}", barcode=f"P19-PX-QR-{marker}",
            production_order_id=order.id, production_batch_id=batch_a.id,
            model_id=model.id, color="black", total_quantity=999, capacity=1000, status="packed",
        )
        direct_null = Package(
            package_no=f"P19-PN-{marker}", barcode=f"P19-PN-QR-{marker}",
            production_order_id=order.id, production_batch_id=None,
            model_id=model.id, color="black", total_quantity=47, capacity=100, status="packed",
        )
        db.add_all([direct_a, allocated, direct_null])
        db.flush()
        db.add(PackageBatchAllocation(
            package_id=allocated.id,
            production_batch_id=batch_b.id,
            quantity=79,
        ))
        db.commit()
        return int(order.id), int(a_cutting.id)


def test_cutting_reconciliation_matches_scalar_scope_evidence():
    order_id, cutting_id = _mixed_reconciliation_order()
    with TestSessionLocal() as db:
        cutting = db.get(WorkOrder, cutting_id)
        order = db.get(ProductionOrder, order_id)
        work_orders = db.query(WorkOrder).filter(WorkOrder.production_order_id == order_id).all()
        cutting_by_scope = {
            row.production_batch_id: row
            for row in work_orders
            if row.operation == "cutting"
        }
        fallback_cutting = cutting_by_scope.get(None) or cutting
        expected: dict[int, int] = {}
        for row in work_orders:
            scope_id = int(row.production_batch_id) if row.production_batch_id is not None else None
            scoped_cutting = cutting_by_scope.get(scope_id) or fallback_cutting
            scope_target = max(
                production_routes._planned_quantity_for_scope(db, order, scope_id),
                production_routes._bundle_total_for_scope(db, order_id, scope_id),
                production_routes._cutting_output_for_scope(db, scoped_cutting, scope_id),
                production_routes._downstream_committed_quantity(db, order_id, scope_id),
            )
            own_floor = max(
                int(row.actual_input_qty or 0),
                int(row.actual_output_qty or 0),
                int(row.passed_qty or 0) + int(row.failed_qty or 0),
            )
            expected[int(row.id)] = max(scope_target, own_floor)

        production_routes._reconcile_cutting_workflow_plans(db, cutting)
        db.flush()

        refreshed = db.query(WorkOrder).filter(WorkOrder.production_order_id == order_id).all()
        for row in refreshed:
            assert int(row.planned_input_qty) == expected[int(row.id)]
            assert int(row.planned_output_qty) == expected[int(row.id)]
        reopened = next(
            row for row in refreshed
            if row.operation == "packaging" and row.production_batch_id == cutting.production_batch_id
        )
        assert reopened.status == "in_progress"
        assert reopened.end_time is None
        assert reopened.start_time is not None


def _single_dominant_evidence(kind: str) -> tuple[int, int, int]:
    marker = uuid4().hex[:8]
    with TestSessionLocal() as db:
        model = Model(code=f"PERF19-{kind}-{marker}", name=f"Dominant {kind} {marker}")
        department = Department(name=f"PERF19 {kind} {marker}", code=f"D19-{marker}")
        flow = SewingFlow(
            factory_code="MIL",
            name=f"PERF19 {kind} flow {marker}",
            code=f"F19-{marker}",
            capacity_per_day=200,
            is_active=True,
        )
        db.add_all([model, department, flow])
        db.flush()
        order = ProductionOrder(
            production_no=f"PERF19-{kind}-{marker}",
            production_type="branded_stock",
            model_id=model.id,
            planned_quantity=1,
            status="cutting",
        )
        db.add(order)
        db.flush()
        batch = ProductionBatch(
            production_order_id=order.id,
            batch_no="ONLY",
            batch_index=1,
            planned_quantity=1,
        )
        db.add(batch)
        db.flush()
        work_orders = {
            operation: WorkOrder(
                production_order_id=order.id,
                production_batch_id=batch.id,
                department_id=department.id,
                operation=operation,
                status="waiting",
                planned_input_qty=0,
                planned_output_qty=0,
                actual_input_qty=0,
                actual_output_qty=0,
                passed_qty=0,
                failed_qty=0,
                rework_qty=0,
            )
            for operation in ("cutting", "printing", "sewing", "packaging")
        }
        db.add_all(work_orders.values())
        db.flush()

        expected = 101
        if kind == "bundle":
            db.add(Bundle(
                bundle_no=f"P19-{marker}", barcode=f"P19-QR-{marker}",
                production_order_id=order.id, production_batch_id=batch.id,
                model_id=model.id, color="blue", size="M", quantity=expected, status="created",
            ))
        elif kind in {"cutting", "cutting_replacement"}:
            passed = expected if kind == "cutting" else expected + 9
            db.add(CuttingRecord(
                work_order_id=work_orders["cutting"].id,
                production_batch_id=batch.id,
                input_quantity=1,
                input_unit="kg",
                cut_pieces=passed,
                passed_pieces=passed,
                defective_pieces=0,
                waste_quantity=0,
                waste_unit="kg",
                layer_material_kg=0,
                beika_kg=0,
                material_rolls_used=0,
                bundle_count=0,
                total_bundled_quantity=0,
                approval_status="approved",
            ))
            if kind == "cutting_replacement":
                sewing_record = SewingRecord(
                    work_order_id=work_orders["sewing"].id,
                    production_batch_id=batch.id,
                    input_qty=0,
                    sewn_qty=0,
                    passed_qty=0,
                    failed_qty=0,
                    rejected_qty=0,
                    rework_qty=0,
                )
                db.add(sewing_record)
                db.flush()
                db.add(SewingReplacementRequest(
                    production_order_id=order.id,
                    sewing_work_order_id=work_orders["sewing"].id,
                    cutting_work_order_id=work_orders["cutting"].id,
                    production_batch_id=batch.id,
                    sewing_record_id=sewing_record.id,
                    requested_qty=9,
                    cut_qty=9,
                    replaced_qty=0,
                    status="waiting_sewing",
                ))
        elif kind == "printing":
            db.add(PrintingRecord(
                work_order_id=work_orders["printing"].id,
                production_batch_id=batch.id,
                input_qty=expected,
                printed_qty=expected - 1,
                passed_qty=expected - 2,
                rejected_qty=1,
            ))
        elif kind == "sewing":
            db.add(SewingRecord(
                work_order_id=work_orders["sewing"].id,
                production_batch_id=batch.id,
                input_qty=expected,
                sewn_qty=expected - 1,
                passed_qty=expected - 2,
                failed_qty=1,
                rejected_qty=0,
                rework_qty=0,
            ))
        elif kind == "assignment":
            db.add(SewingAssignment(
                work_order_id=work_orders["sewing"].id,
                production_batch_id=batch.id,
                sewing_flow_id=flow.id,
                quantity=expected,
                completed_qty=expected,
                status="completed",
            ))
        elif kind == "daily":
            db.add(SewingDailyReport(
                report_date=date(2026, 1, 1),
                sewing_flow_id=flow.id,
                work_order_id=work_orders["sewing"].id,
                production_order_id=order.id,
                production_batch_id=batch.id,
                line_code=flow.code,
                line_name=flow.name,
                sewn_qty=expected,
                defective_qty=0,
            ))
        elif kind == "packaging":
            db.add(PackagingRecord(
                work_order_id=work_orders["packaging"].id,
                production_batch_id=batch.id,
                input_qty=expected,
                packed_qty=expected - 1,
                damaged_qty=1,
                package_count=1,
                total_packed_quantity=expected - 1,
            ))
        elif kind == "receipt":
            db.add(PackagingReceipt(
                packaging_department_code="PKG",
                work_order_id=work_orders["packaging"].id,
                source_work_order_id=work_orders["sewing"].id,
                production_order_id=order.id,
                production_batch_id=batch.id,
                quantity=expected,
                receive_method="manual",
            ))
        elif kind in {"package_direct", "package_allocated"}:
            package = Package(
                package_no=f"P19-{kind}-{marker}",
                barcode=f"P19-{kind}-QR-{marker}",
                production_order_id=order.id,
                production_batch_id=batch.id,
                model_id=model.id,
                color="blue",
                total_quantity=expected if kind == "package_direct" else 999,
                capacity=1000,
                status="packed",
            )
            db.add(package)
            db.flush()
            if kind == "package_allocated":
                db.add(PackageBatchAllocation(
                    package_id=package.id,
                    production_batch_id=batch.id,
                    quantity=expected,
                ))
        else:
            raise AssertionError(f"Unhandled evidence kind: {kind}")

        db.commit()
        return int(order.id), int(work_orders["cutting"].id), expected


@pytest.mark.parametrize("kind", [
    "bundle",
    "cutting",
    "cutting_replacement",
    "printing",
    "sewing",
    "assignment",
    "daily",
    "packaging",
    "receipt",
    "package_direct",
    "package_allocated",
])
def test_cutting_reconciliation_keeps_each_scalar_evidence_branch(kind):
    order_id, cutting_id, expected = _single_dominant_evidence(kind)
    with TestSessionLocal() as db:
        cutting = db.get(WorkOrder, cutting_id)
        production_routes._reconcile_cutting_workflow_plans(db, cutting)
        db.flush()
        rows = db.query(WorkOrder).filter(WorkOrder.production_order_id == order_id).all()

    assert rows
    assert {int(row.planned_input_qty) for row in rows} == {expected}
    assert {int(row.planned_output_qty) for row in rows} == {expected}


@pytest.mark.parametrize("kind", ["sewing", "receipt", "package_direct", "package_allocated"])
def test_cutting_scope_evidence_keeps_identity_and_quantity_semantics(kind):
    order_id, cutting_id, expected = _single_dominant_evidence(kind)
    with TestSessionLocal() as db:
        cutting = db.get(WorkOrder, cutting_id)
        evidence = production_routes._cutting_scope_evidence(
            db,
            order_id,
            cutting.production_batch_id,
        )

    assert evidence.downstream_quantity == expected
    assert evidence.has_identity_evidence is True


def test_cutting_reconciliation_keeps_null_scope_separate_from_batches():
    marker = uuid4().hex[:8]
    with TestSessionLocal() as db:
        model = Model(code=f"PERF19-NULL-{marker}", name=f"NULL scope {marker}")
        department = Department(name=f"PERF19 NULL {marker}", code=f"N19-{marker}")
        db.add_all([model, department])
        db.flush()
        order = ProductionOrder(
            production_no=f"PERF19-NULL-{marker}",
            production_type="branded_stock",
            model_id=model.id,
            planned_quantity=1,
            status="cutting",
        )
        db.add(order)
        db.flush()
        batch = ProductionBatch(
            production_order_id=order.id,
            batch_no="OTHER",
            batch_index=1,
            planned_quantity=1,
        )
        db.add(batch)
        db.flush()
        cutting = WorkOrder(
            production_order_id=order.id,
            production_batch_id=None,
            department_id=department.id,
            operation="cutting",
            status="waiting",
            planned_input_qty=0,
            planned_output_qty=0,
            actual_input_qty=0,
            actual_output_qty=0,
            passed_qty=0,
            failed_qty=0,
            rework_qty=0,
        )
        db.add(cutting)
        db.flush()
        db.add_all([
            Bundle(
                bundle_no=f"P19-NULL-{marker}", barcode=f"P19-NULL-QR-{marker}",
                production_order_id=order.id, production_batch_id=None,
                model_id=model.id, color="blue", size="M", quantity=101, status="created",
            ),
            Bundle(
                bundle_no=f"P19-OTHER-{marker}", barcode=f"P19-OTHER-QR-{marker}",
                production_order_id=order.id, production_batch_id=batch.id,
                model_id=model.id, color="blue", size="M", quantity=999, status="created",
            ),
        ])
        db.commit()
        cutting_id = int(cutting.id)

    with TestSessionLocal() as db:
        cutting = db.get(WorkOrder, cutting_id)
        production_routes._reconcile_cutting_workflow_plans(db, cutting)
        db.flush()
        assert int(cutting.planned_input_qty) == 101
        assert int(cutting.planned_output_qty) == 101
