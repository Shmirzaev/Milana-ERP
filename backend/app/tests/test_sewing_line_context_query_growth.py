from datetime import date
from uuid import uuid4

from sqlalchemy import event

from app.api.routes.sewing_daily_reports import (
    _line_context, _line_context_capacity_maps, _report_capacity,
)
from app.db.session import SessionLocal
from app.models import (
    Bundle, Department, Model, ProductionBatch, ProductionOrder, SewingAssignment,
    SewingDailyReport, SewingFlow, WorkOrder,
)


def _create_line_context(db, assignment_count):
    suffix = uuid4().hex[:8].upper()
    department_id = db.query(Department.id).order_by(Department.id).first()[0]
    model_id = db.query(Model.id).order_by(Model.id).first()[0]
    flow = SewingFlow(
        factory_code="MIL", code=f"PERF42-{suffix}", name=f"PERF42 {suffix}",
        capacity_per_day=1000, is_active=True,
    )
    db.add(flow)
    db.flush()
    expected = {}
    for number in range(assignment_count):
        production = ProductionOrder(
            production_no=f"PERF42-PO-{suffix}-{number}", production_type="branded_stock",
            model_id=model_id, status="sewing", planned_quantity=100,
        )
        db.add(production)
        db.flush()
        batch = ProductionBatch(
            production_order_id=production.id, batch_no=f"PERF42-B-{number}",
            batch_index=1, planned_quantity=80,
        )
        db.add(batch)
        db.flush()
        work_order = WorkOrder(
            production_order_id=production.id, production_batch_id=batch.id,
            department_id=department_id, operation="sewing", status="waiting",
            planned_input_qty=100, planned_output_qty=100,
        )
        db.add(work_order)
        db.flush()
        assignment_qty = 30 if number % 2 == 0 else 100
        assignment = SewingAssignment(
            work_order_id=work_order.id, production_batch_id=batch.id,
            sewing_flow_id=flow.id, quantity=assignment_qty, completed_qty=0,
            status="planned",
        )
        db.add(assignment)
        db.flush()
        db.add(Bundle(
            bundle_no=f"PERF42-BUNDLE-{suffix}-{number}",
            barcode=f"PERF42-BARCODE-{suffix}-{number}", production_order_id=production.id,
            production_batch_id=batch.id, model_id=model_id, color="navy", size="M",
            quantity=70, status="received_sewing",
        ))
        db.add_all([
            SewingDailyReport(
                report_date=date(2026, 9, 1), sewing_flow_id=flow.id,
                work_order_id=work_order.id, sewing_assignment_id=assignment.id,
                production_order_id=production.id, production_batch_id=batch.id,
                line_code=flow.code, line_name=flow.name, sewn_qty=10,
                top_qty=10, bottom_qty=4, defective_qty=0,
            ),
            SewingDailyReport(
                report_date=date(2026, 9, 2), sewing_flow_id=flow.id,
                work_order_id=work_order.id, production_order_id=production.id,
                production_batch_id=batch.id, line_code=flow.code, line_name=flow.name,
                sewn_qty=7, top_qty=5, bottom_qty=7, defective_qty=0,
            ),
        ])
        expected[assignment.id] = (20, 26) if assignment_qty == 30 else (55, 59)
    db.commit()
    return flow.id, expected


def _measured_context(flow_id):
    with SessionLocal() as db:
        flow = db.get(SewingFlow, flow_id)
        counts = {"bundles": 0, "reports": 0}

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            normalized = " ".join(statement.lower().split())
            if " from bundles" in normalized:
                counts["bundles"] += 1
            if " from sewing_daily_reports" in normalized:
                counts["reports"] += 1

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            context = _line_context(db, flow)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
    return context, counts


def test_line_context_bulk_capacity_queries_and_semantics():
    with SessionLocal() as db:
        one_flow, one_expected = _create_line_context(db, 1)
        many_flow, many_expected = _create_line_context(db, 12)

    one, one_counts = _measured_context(one_flow)
    many, many_counts = _measured_context(many_flow)

    assert one_counts == many_counts == {"bundles": 1, "reports": 1}
    for context, expected in ((one, one_expected), (many, many_expected)):
        actual = {
            row.sewing_assignment_id: (
                row.report_remaining_top_qty, row.report_remaining_bottom_qty,
            )
            for row in context.active_work_orders
        }
        assert actual == expected


def test_bulk_capacity_matches_reference_for_direct_no_batch_legacy_history():
    with SessionLocal() as db:
        suffix = uuid4().hex[:8].upper()
        department_id = db.query(Department.id).order_by(Department.id).first()[0]
        model_id = db.query(Model.id).order_by(Model.id).first()[0]
        flow = SewingFlow(
            factory_code="MIL", code=f"PERF42-DIRECT-{suffix}",
            name=f"PERF42 direct {suffix}", capacity_per_day=100, is_active=True,
        )
        production = ProductionOrder(
            production_no=f"PERF42-DIRECT-PO-{suffix}", production_type="branded_stock",
            model_id=model_id, status="sewing", planned_quantity=50,
        )
        db.add_all([flow, production])
        db.flush()
        work_order = WorkOrder(
            production_order_id=production.id, department_id=department_id,
            sewing_flow_id=flow.id, operation="sewing", status="waiting",
            planned_input_qty=50, planned_output_qty=50,
        )
        db.add(work_order)
        db.flush()
        db.add(SewingDailyReport(
            report_date=date(2026, 9, 1), sewing_flow_id=flow.id,
            work_order_id=work_order.id, production_order_id=production.id,
            line_code=flow.code, line_name=flow.name, sewn_qty=0,
            top_qty=-5, bottom_qty=-7, defective_qty=0,
        ))
        db.commit()

        reference = _report_capacity(db, work_order)
        capacities, batches = _line_context_capacity_maps(db, [(work_order, None)])
        assert reference == (50, 50)
        assert capacities[(work_order.id, None)] == reference
        assert batches == {}

        context = _line_context(db, flow)
        assert len(context.active_work_orders) == 1
        assert (
            context.active_work_orders[0].report_remaining_top_qty,
            context.active_work_orders[0].report_remaining_bottom_qty,
        ) == reference
