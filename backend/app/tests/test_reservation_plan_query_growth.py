from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.db.session import SessionLocal
from app.models import (
    Item,
    MaterialReservation,
    Model,
    ModelBOM,
    ProductionOrder,
    ProductionOrderMaterial,
    StockBatch,
    StockMovement,
    Warehouse,
)
from app.services import inventory


def _select_trace(db, call):
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(db.bind, "before_cursor_execute", capture)
    try:
        result = call()
    finally:
        event.remove(db.bind, "before_cursor_execute", capture)
    return result, statements


def _explicit_material_plan(db, count):
    marker = uuid4().hex[:8]
    model = Model(code=f"PERF03-M-{marker}", name="Reservation performance", status="approved")
    db.add(model)
    db.flush()
    warehouse_id = db.query(Warehouse.id).order_by(Warehouse.id).first()[0]
    items = [
        Item(
            sku=f"PERF03-I-{marker}-{number:04d}",
            name=f"Reservation item {number}",
            category="fabric",
            unit="kg",
            track_batch=True,
        )
        for number in range(count)
    ]
    db.add_all(items)
    db.flush()
    batches = [
        StockBatch(
            item_id=item.id,
            batch_no=f"PERF03-B-{marker}-{number:04d}",
            quantity=10,
            unit="kg",
            cost_per_unit=1,
            warehouse_id=warehouse_id,
            qc_status="passed",
        )
        for number, item in enumerate(items)
    ]
    db.add_all(batches)
    db.flush()
    order = ProductionOrder(
        production_no=f"PERF03-PO-{marker}",
        production_type="branded_stock",
        model_id=model.id,
        planned_quantity=1,
    )
    db.add(order)
    db.flush()
    db.add_all([
        ProductionOrderMaterial(
            production_order_id=order.id,
            stock_batch_id=batch.id,
            estimated_quantity=number + 1,
            unit="kg",
            position=number + 1,
        )
        for number, batch in enumerate(batches)
    ])
    db.commit()
    return int(order.id), [int(batch.id) for batch in batches]


@pytest.mark.parametrize(("line_count", "expected_selects"), [(1, 14), (50, 14), (401, 21)])
def test_reservation_plan_reads_are_chunk_bounded(line_count, expected_selects):
    with SessionLocal() as db:
        order_id, batch_ids = _explicit_material_plan(db, line_count)
    with SessionLocal() as db:
        payload, statements = _select_trace(
            db,
            lambda: inventory.reservation_plan_for_production_order(db, order_id),
        )

    assert len(statements) == expected_selects
    order_item_reads = [
        " ".join(statement.lower().split())
        for statement in statements
        if " from production_order_items " in " ".join(statement.lower().split())
    ]
    assert len(order_item_reads) == 1
    assert all(
        column in order_item_reads[0]
        for column in (
            "production_order_items.model_id",
            "production_order_items.planned_quantity",
            "production_order_items.size",
            "production_order_items.color",
        )
    )
    assert "production_order_items.created_at" not in order_item_reads[0]
    assert "production_order_items.updated_at" not in order_item_reads[0]
    assert [row["stock_batch_id"] for row in payload["rows"]] == batch_ids
    assert [row["required_quantity"] for row in payload["rows"]] == [
        float(number) for number in range(1, line_count + 1)
    ]
    assert payload["summary"]["line_count"] == line_count


def _scalar_reservation_plan(db, production_order_id):
    po = db.get(ProductionOrder, production_order_id)
    model_code, model_name = inventory._model_label_fields(db, po.model_id)
    coverage = inventory._reservation_coverage_by_item_unit(db, int(po.id))
    batch_coverage = inventory._reservation_coverage_by_item_unit_batch(db, int(po.id))
    rows = []
    for row in inventory._bom_requirement_rows(db, po, inventory.RESERVABLE_CATEGORIES):
        stock_batch_id = int(row["stock_batch_id"]) if row.get("stock_batch_id") else None
        if stock_batch_id is not None:
            coverage_key = (int(row["item_id"]), str(row["unit"]), stock_batch_id)
            already_reserved = float(batch_coverage.get(coverage_key, 0.0))
        else:
            coverage_key = (int(row["item_id"]), str(row["unit"]))
            already_reserved = float(coverage.get(coverage_key, 0.0))
        required = float(row["required_quantity"] or 0)
        remaining = max(0.0, required - already_reserved)
        if stock_batch_id is not None:
            current = inventory.current_stock_for_batch(db, stock_batch_id)
            available = inventory.available_stock_for_batch(db, stock_batch_id)
            reserved = inventory.reserved_stock_for_batch(db, stock_batch_id)
        else:
            current = inventory.current_stock_for_item(db, int(row["item_id"]))
            available = inventory.available_stock_for_item(db, int(row["item_id"]))
            reserved = inventory.reserved_stock_for_item(db, int(row["item_id"]))
        shortage = max(0.0, remaining - max(0.0, available))
        suggested_batches = inventory._suggest_batches_for_requirement(
            db,
            item_id=int(row["item_id"]),
            unit=str(row["unit"]),
            quantity=remaining,
            stock_batch_id=stock_batch_id,
        )
        status = "ready" if remaining <= inventory.EPSILON else "shortage" if shortage > inventory.EPSILON else "partial"
        rows.append({
            **row,
            "required_quantity": required,
            "already_reserved_quantity": already_reserved,
            "remaining_to_reserve": remaining,
            "current_stock": current,
            "reserved_stock": reserved,
            "available_stock": available,
            "shortage": shortage,
            "suggested_batches": suggested_batches,
            "status": status,
        })

    total_required = sum(float(row["required_quantity"] or 0) for row in rows)
    total_reserved = sum(float(row["already_reserved_quantity"] or 0) for row in rows)
    total_remaining = sum(float(row["remaining_to_reserve"] or 0) for row in rows)
    total_shortage = sum(float(row["shortage"] or 0) for row in rows)
    readiness_status = (
        "no_bom"
        if not rows
        else "ready"
        if total_remaining <= inventory.EPSILON
        else "shortage"
        if total_shortage > inventory.EPSILON
        else "partial"
    )
    return {
        "production_order_id": int(po.id),
        "production_no": po.production_no,
        "order_no": po.order_no,
        "sales_order_id": int(po.sales_order_id) if po.sales_order_id else None,
        "model_id": int(po.model_id),
        "model_code": model_code,
        "model_name": model_name,
        "planned_quantity": int(po.planned_quantity or 0),
        "status": readiness_status,
        "is_complete": total_remaining <= inventory.EPSILON,
        "warning": None if total_remaining <= inventory.EPSILON else "Material reservation is incomplete before cutting.",
        "summary": {
            "required_quantity": total_required,
            "already_reserved_quantity": total_reserved,
            "remaining_to_reserve": total_remaining,
            "shortage": total_shortage,
            "line_count": len(rows),
            "ready_line_count": sum(1 for row in rows if row["status"] == "ready"),
            "shortage_line_count": sum(1 for row in rows if row["status"] == "shortage"),
        },
        "rows": rows,
    }


def _mixed_plan(db):
    marker = uuid4().hex[:8]
    warehouse_id = db.query(Warehouse.id).order_by(Warehouse.id).first()[0]
    model = Model(code=f"PERF03-MIX-{marker}", name="Mixed reservation model", status="approved")
    loose_item = Item(
        sku=f"PERF03-LOOSE-{marker}", name="Loose item", category="accessory", unit="kg", track_batch=True,
    )
    exact_item = Item(
        sku=f"PERF03-EXACT-{marker}", name="Exact item", category="fabric", unit="kg", track_batch=True,
    )
    db.add_all([model, loose_item, exact_item])
    db.flush()
    base_date = datetime(2026, 9, 1, tzinfo=timezone.utc)
    batches = [
        StockBatch(
            item_id=loose_item.id,
            batch_no=f"PERF03-FIFO-A-{marker}",
            quantity=5,
            unit="kg",
            cost_per_unit=1,
            received_date=base_date,
            warehouse_id=warehouse_id,
            qc_status="passed",
        ),
        StockBatch(
            item_id=loose_item.id,
            batch_no=f"PERF03-FIFO-B-{marker}",
            quantity=7,
            unit="kg",
            cost_per_unit=1,
            received_date=base_date + timedelta(days=1),
            warehouse_id=warehouse_id,
            qc_status="hold",
        ),
        StockBatch(
            item_id=loose_item.id,
            batch_no=f"PERF03-WRONG-UNIT-{marker}",
            quantity=4,
            unit="m",
            cost_per_unit=1,
            received_date=base_date - timedelta(days=1),
            warehouse_id=warehouse_id,
            qc_status="failed",
        ),
        StockBatch(
            item_id=loose_item.id,
            batch_no=f"PERF03-EMPTY-{marker}",
            quantity=0,
            unit="kg",
            cost_per_unit=1,
            received_date=base_date - timedelta(days=2),
            warehouse_id=warehouse_id,
            qc_status="rejected",
        ),
        StockBatch(
            item_id=exact_item.id,
            batch_no=f"PERF03-EXACT-B-{marker}",
            quantity=2,
            unit="kg",
            cost_per_unit=1,
            received_date=base_date,
            warehouse_id=warehouse_id,
            qc_status="pending",
        ),
    ]
    db.add_all(batches)
    db.flush()
    db.add_all([
        ModelBOM(
            model_id=model.id,
            item_id=loose_item.id,
            quantity_per_piece=1,
            unit="kg",
            waste_percent=0,
        ),
        ModelBOM(
            model_id=model.id,
            item_id=exact_item.id,
            stock_batch_id=batches[4].id,
            quantity_per_piece=0.5,
            unit="kg",
            waste_percent=0,
        ),
    ])
    target = ProductionOrder(
        production_no=f"PERF03-TARGET-{marker}",
        production_type="branded_stock",
        model_id=model.id,
        planned_quantity=10,
    )
    other = ProductionOrder(
        production_no=f"PERF03-OTHER-{marker}",
        production_type="branded_stock",
        model_id=model.id,
        planned_quantity=1,
    )
    db.add_all([target, other])
    db.flush()
    db.add_all([
        StockMovement(
            movement_type="adjustment",
            item_id=loose_item.id,
            quantity=3,
            unit="kg",
        ),
        StockMovement(
            movement_type="issue",
            item_id=loose_item.id,
            quantity=1,
            unit="kg",
        ),
        MaterialReservation(
            reservation_no=f"PERF03-R-A-{marker}",
            production_order_id=target.id,
            item_id=loose_item.id,
            reserved_quantity=3,
            consumed_quantity=1,
            released_quantity=0,
            unit="kg",
            status="partially_consumed",
            reservation_type="accessory",
            source="planning",
        ),
        MaterialReservation(
            reservation_no=f"PERF03-R-CANCEL-{marker}",
            production_order_id=target.id,
            item_id=loose_item.id,
            reserved_quantity=4,
            consumed_quantity=0,
            released_quantity=0,
            unit="kg",
            status="cancelled",
            reservation_type="accessory",
            source="planning",
        ),
        MaterialReservation(
            reservation_no=f"PERF03-R-RELEASED-{marker}",
            production_order_id=target.id,
            item_id=loose_item.id,
            reserved_quantity=2,
            consumed_quantity=0,
            released_quantity=2,
            unit="kg",
            status="released",
            reservation_type="accessory",
            source="planning",
        ),
        MaterialReservation(
            reservation_no=f"PERF03-R-OTHER-{marker}",
            production_order_id=other.id,
            item_id=loose_item.id,
            stock_batch_id=batches[0].id,
            warehouse_id=warehouse_id,
            reserved_quantity=1,
            consumed_quantity=0,
            released_quantity=0,
            unit="kg",
            status="reserved",
            reservation_type="accessory",
            source="planning",
        ),
        MaterialReservation(
            reservation_no=f"PERF03-R-EXACT-C-{marker}",
            production_order_id=target.id,
            item_id=exact_item.id,
            stock_batch_id=batches[4].id,
            warehouse_id=warehouse_id,
            reserved_quantity=2,
            consumed_quantity=2,
            released_quantity=0,
            unit="kg",
            status="consumed",
            reservation_type="material",
            source="planning",
        ),
        MaterialReservation(
            reservation_no=f"PERF03-R-EXACT-A-{marker}",
            production_order_id=target.id,
            item_id=exact_item.id,
            stock_batch_id=batches[4].id,
            warehouse_id=warehouse_id,
            reserved_quantity=1,
            consumed_quantity=0,
            released_quantity=0,
            unit="kg",
            status="reserved",
            reservation_type="material",
            source="planning",
        ),
    ])
    db.commit()
    return int(target.id)


def test_reservation_plan_matches_scalar_semantics_for_mixed_stock_and_reservations():
    with SessionLocal() as db:
        order_id = _mixed_plan(db)
    with SessionLocal() as db:
        expected = _scalar_reservation_plan(db, order_id)
    with SessionLocal() as db:
        actual = inventory.reservation_plan_for_production_order(db, order_id)

    assert actual == expected
    by_sku = {row["item_sku"]: row for row in actual["rows"]}
    loose = next(row for sku, row in by_sku.items() if "LOOSE" in sku)
    exact = next(row for sku, row in by_sku.items() if "EXACT" in sku)
    assert loose["current_stock"] == 18
    assert loose["reserved_stock"] == 3
    assert [row["suggested_quantity"] for row in loose["suggested_batches"]] == [4, 3]
    assert exact["already_reserved_quantity"] == 3
    assert exact["available_stock"] == 1
    assert exact["shortage"] == 1


def test_exact_batch_requirements_do_not_scan_same_item_fifo_candidates(monkeypatch):
    marker = uuid4().hex[:8]
    with SessionLocal() as db:
        model = Model(code=f"PERF03-EXACT-MANY-{marker}", name="Many exact batches", status="approved")
        item = Item(
            sku=f"PERF03-EXACT-MANY-{marker}",
            name="Many exact batch item",
            category="fabric",
            unit="kg",
            track_batch=True,
        )
        db.add_all([model, item])
        db.flush()
        warehouse_id = db.query(Warehouse.id).order_by(Warehouse.id).first()[0]
        batches = [
            StockBatch(
                item_id=item.id,
                batch_no=f"PERF03-EXACT-MANY-{marker}-{number:04d}",
                quantity=1,
                unit="kg",
                cost_per_unit=1,
                received_date=datetime(2026, 9, 1, tzinfo=timezone.utc) + timedelta(minutes=number),
                warehouse_id=warehouse_id,
                qc_status="passed",
            )
            for number in range(401)
        ]
        db.add_all(batches)
        db.flush()
        order = ProductionOrder(
            production_no=f"PERF03-EXACT-MANY-PO-{marker}",
            production_type="branded_stock",
            model_id=model.id,
            planned_quantity=1,
        )
        db.add(order)
        db.flush()
        db.add_all([
            ProductionOrderMaterial(
                production_order_id=order.id,
                stock_batch_id=batch.id,
                estimated_quantity=1,
                unit="kg",
                position=number + 1,
            )
            for number, batch in enumerate(batches)
        ])
        db.commit()
        order_id = int(order.id)

    original_context = inventory._reservation_plan_stock_context
    candidate_visits = 0

    class CountingCandidates(list):
        def __iter__(self):
            nonlocal candidate_visits
            for candidate in super().__iter__():
                candidate_visits += 1
                yield candidate

    def instrumented_context(db, requirement_rows):
        context = original_context(db, requirement_rows)
        context["candidate_batches_by_item"] = {
            item_id: CountingCandidates(candidates)
            for item_id, candidates in context["candidate_batches_by_item"].items()
        }
        return context

    monkeypatch.setattr(inventory, "_reservation_plan_stock_context", instrumented_context)
    with SessionLocal() as db:
        payload = inventory.reservation_plan_for_production_order(db, order_id)

    assert len(payload["rows"]) == 401
    assert all(len(row["suggested_batches"]) == 1 for row in payload["rows"])
    assert candidate_visits == 0
