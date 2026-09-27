from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app.db.session import SessionLocal
from app.models import (
    AuditLog, BusinessOrderAlias, Item, Model, ProductionOrder, PurchaseOrder,
    PurchaseOrderLine, PurchaseRequest, PurchaseRequestLine, SalesOrder, StockBatch,
    Supplier, User, Warehouse,
)
from app.core.order_reference import BusinessOrderReferenceLookup, canonical_business_order_reference
from app.services.purchasing import create_purchase_request, receive_purchase_order


def _request_lines(line_count: int):
    suffix = uuid4().hex[:8]
    with SessionLocal() as db:
        items = [
            Item(
                sku=f"PERF28-REQUEST-{suffix}-{number}",
                name=f"Request item {number}",
                category="accessory",
                unit="pcs",
            )
            for number in range(line_count)
        ]
        suppliers = [Supplier(name=f"PERF28 request supplier {suffix}-{number}") for number in range(line_count)]
        db.add_all([*items, *suppliers])
        db.flush()
        payload = [
            {
                "item_id": int(item.id),
                "preferred_supplier_id": int(supplier.id),
                "required_quantity": number + 1,
                "requested_quantity": number + 1,
                "unit": "pcs",
                "material_name": f"Material {number}",
                "notes": f"Line {number}",
            }
            for number, (item, supplier) in enumerate(zip(items, suppliers))
        ]
        db.commit()
    return payload


def _measure_request_creation(payload):
    with SessionLocal() as db:
        current = db.query(User).order_by(User.id).first()
        reference_selects = []
        audit_head_selects = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            normalized = " ".join(statement.lower().split())
            if statement.lstrip().upper().startswith("SELECT") and " from audit_logs " in normalized:
                audit_head_selects.append(normalized)
            if statement.lstrip().upper().startswith("SELECT") and (
                " from items " in normalized or " from suppliers " in normalized
            ):
                reference_selects.append(normalized)

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            request = create_purchase_request(
                db,
                data={"status": "pending_approval", "lines": payload},
                current=current,
            )
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
        request_id = int(request.id)
        db.commit()

    with SessionLocal() as db:
        request = db.get(PurchaseRequest, request_id)
        return {
            "reference": len(reference_selects),
            "audit_head": len(audit_head_selects),
            "item_ids": [int(line.item_id) for line in request.lines],
            "supplier_ids": [int(line.preferred_supplier_id) for line in request.lines],
            "requested": [float(line.requested_quantity) for line in request.lines],
            "audits": db.query(AuditLog).filter_by(
                action="create",
                entity_type="PurchaseRequest",
                entity_id=request_id,
            ).count(),
        }


@pytest.mark.parametrize("line_count, expected_reference_reads", [(1, 2), (50, 2), (401, 4)])
def test_purchase_request_creation_batches_line_references_and_preserves_order(
    line_count,
    expected_reference_reads,
):
    payload = _request_lines(line_count)
    measured = _measure_request_creation(payload)

    assert measured["reference"] == expected_reference_reads
    assert measured["audit_head"] == 1
    assert measured["item_ids"] == [row["item_id"] for row in payload]
    assert measured["supplier_ids"] == [row["preferred_supplier_id"] for row in payload]
    assert measured["requested"] == [float(row["requested_quantity"]) for row in payload]
    assert measured["audits"] == 1


def _receipt(db, line_count):
    suffix = uuid4().hex[:8]
    order = PurchaseOrder(po_no=f"PUR-PERF28-{suffix}", status="sent")
    db.add(order)
    db.flush()
    payload = []
    for number in range(line_count):
        item = Item(
            sku=f"PERF28-{suffix}-{number}", name="Query growth item",
            category="accessory", unit="pcs",
        )
        warehouse = Warehouse(name=f"PERF28 warehouse {suffix}-{number}", type="accessory_storage")
        supplier = Supplier(name=f"PERF28 supplier {suffix}-{number}")
        db.add_all([item, warehouse, supplier])
        db.flush()
        line = PurchaseOrderLine(
            purchase_order_id=order.id, item_id=item.id, ordered_quantity=1,
            received_quantity=0, unit="pcs", unit_cost=1,
            warehouse_id=warehouse.id, supplier_id=supplier.id,
        )
        db.add(line)
        db.flush()
        payload.append({
            "purchase_order_line_id": line.id, "received_quantity": 1,
            "batch_no": f"PERF28-LOT-{suffix}-{number}",
            "warehouse_id": warehouse.id, "supplier_id": supplier.id,
            "order_no": f"CUSTOM-{suffix}-{number}",
        })
    order.supplier_id = payload[0]["supplier_id"]
    db.commit()
    return order.id, payload


def _measure(order_id, payload):
    with SessionLocal() as db:
        current = db.query(User).order_by(User.id).first()
        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            receive_purchase_order(db, order_id=order_id, data={"lines": payload}, current=current)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
        db.commit()
    reference_tables = (" from items", " from warehouses", " from suppliers", " from business_order_aliases")
    return {
        "reference": sum(any(table in statement for table in reference_tables) for statement in statements),
        "audit_head": sum(" from audit_logs" in statement for statement in statements),
        "total": len(statements),
    }


def _reference_select_count(references, *, bulk):
    with SessionLocal() as db:
        count = 0

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            nonlocal count
            if statement.lstrip().upper().startswith("SELECT"):
                count += 1

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            lookup = BusinessOrderReferenceLookup(db, references) if bulk else None
            for reference in references:
                canonical_business_order_reference(db, reference, lookup=lookup)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
        return count


def test_business_reference_lookup_replaces_per_reference_queries_with_chunked_reads():
    groups = [[f"SUPPLIER-REFERENCE-{number}" for number in range(size)] for size in (1, 10, 50)]
    assert [_reference_select_count(group, bulk=False) for group in groups] == [1, 10, 50]
    assert [_reference_select_count(group, bulk=True) for group in groups] == [1, 1, 1]
    assert _reference_select_count([f"CHUNKED-{number}" for number in range(401)], bulk=True) == 2


def test_receipt_catalog_order_reference_and_audit_head_queries_are_bounded():
    with SessionLocal() as db:
        one_id, one_payload = _receipt(db, 1)
        fifty_id, fifty_payload = _receipt(db, 50)
        many_id, many_payload = _receipt(db, 401)

    one = _measure(one_id, one_payload)
    fifty = _measure(fifty_id, fifty_payload)
    many = _measure(many_id, many_payload)

    # Three reference maps and generic order aliases use 400-ID chunks. The
    # 401-line case adds exactly one read per map, not one read per line.
    assert (one["reference"], fifty["reference"], many["reference"]) == (4, 4, 8)
    assert (one["audit_head"], fifty["audit_head"], many["audit_head"]) == (1, 1, 1)
    assert many["total"] - one["total"] == 4
    with SessionLocal() as db:
        assert db.query(StockBatch).filter(StockBatch.internal_batch_no.like("PUR-PERF28-%")).count() == 452


def test_purchase_request_batched_reference_failure_preserves_error_order_and_rolls_back():
    payload = _request_lines(2)
    missing_supplier_id = 2_000_000_001
    missing_item_id = 2_000_000_002
    payload[0]["preferred_supplier_id"] = missing_supplier_id
    payload[1]["item_id"] = missing_item_id

    with SessionLocal() as db:
        before = (
            db.query(PurchaseRequest).count(),
            db.query(PurchaseRequestLine).count(),
            db.query(AuditLog).count(),
        )
        current = db.query(User).order_by(User.id).first()
        with pytest.raises(HTTPException) as error:
            create_purchase_request(
                db,
                data={"status": "pending_approval", "lines": payload},
                current=current,
            )
        assert error.value.status_code == 404
        assert error.value.detail == f"Supplier {missing_supplier_id} not found"
        db.rollback()

    with SessionLocal() as db:
        assert (
            db.query(PurchaseRequest).count(),
            db.query(PurchaseRequestLine).count(),
            db.query(AuditLog).count(),
        ) == before


def test_bulk_reference_lookup_preserves_canonical_alias_and_ambiguous_rollback():
    with SessionLocal() as db:
        order_id, payload = _receipt(db, 2)
        sales = SalesOrder(order_no="SO-PERF28-CANON", status="draft", total_amount=0)
        other = PurchaseOrder(po_no="PUR-PERF28-OTHER", status="sent")
        db.add_all([sales, other])
        db.flush()
        db.add(BusinessOrderAlias(
            namespace="SO", entity_id=sales.id, reference="PERF28-ALIAS",
            canonical_reference=sales.order_no,
        ))
        db.commit()
        current = db.query(User).order_by(User.id).first()
        canonical_payload = {**payload[0], "order_no": "PERF28-ALIAS"}
        receive_purchase_order(db, order_id=order_id, data={"lines": [canonical_payload]}, current=current)
        db.commit()
        assert db.query(StockBatch).filter_by(batch_no=canonical_payload["batch_no"]).one().order_no == sales.order_no

        ambiguous = "PERF28-AMBIGUOUS"
        db.add_all([
            BusinessOrderAlias(namespace="SO", entity_id=sales.id, reference=ambiguous, canonical_reference=sales.order_no),
            BusinessOrderAlias(namespace="PUR", entity_id=other.id, reference=ambiguous, canonical_reference=other.po_no),
        ])
        db.commit()
        before = (db.query(StockBatch).count(), db.query(AuditLog).count())
        invalid_payload = {**payload[1], "order_no": ambiguous}
        with pytest.raises(HTTPException) as error:
            receive_purchase_order(db, order_id=order_id, data={"lines": [invalid_payload]}, current=current)
        assert error.value.status_code == 409
        db.rollback()
        assert (db.query(StockBatch).count(), db.query(AuditLog).count()) == before


def test_bulk_lookup_matches_individual_resolution_for_all_reference_shapes():
    with SessionLocal() as db:
        model_id = db.query(Model.id).order_by(Model.id).first()[0]
        sales = SalesOrder(order_no="SO-PERF28-DIRECT", status="draft", total_amount=0)
        production = ProductionOrder(
            production_no="PO-PERF28-DIRECT", production_type="branded_stock",
            source_type="standard", model_id=model_id, planned_quantity=1,
        )
        usluga = ProductionOrder(
            production_no="USL-PERF28-DIRECT", production_type="client_order",
            source_type="usluga", model_id=model_id, planned_quantity=1,
        )
        request = PurchaseRequest(request_no="PR-PERF28-DIRECT", status="draft")
        purchase = PurchaseOrder(po_no="PUR-PERF28-DIRECT", status="sent")
        linked = ProductionOrder(
            production_no="PO-PERF28-LINKED", production_type="client_order",
            source_type="standard", sales_order_id=None, model_id=model_id, planned_quantity=1,
        )
        db.add_all([sales, production, usluga, request, purchase, linked])
        db.flush()
        linked.sales_order_id = sales.id
        aliases = [
            ("SO", sales.id, "OLD-SO-PERF28", sales.order_no),
            ("PO", production.id, "OLD-PO-PERF28", production.production_no),
            ("USL", usluga.id, "OLD-USL-PERF28", usluga.production_no),
            ("PR", request.id, "OLD-PR-PERF28", request.request_no),
            ("PUR", purchase.id, "OLD-PUR-PERF28", purchase.po_no),
            ("PUBLIC_PO", production.id, "OLD-PUBLIC-PERF28", production.production_no),
            ("PUBLIC_PO", linked.id, "OLD-PUBLIC-LINKED-PERF28", linked.production_no),
            ("SO", 2_000_000_000, "MISSING-PERF28", "SO-MISSING"),
            ("SO", sales.id, "AMBIGUOUS-PERF28", sales.order_no),
            ("PUR", purchase.id, "AMBIGUOUS-PERF28", purchase.po_no),
            ("MYSTERY", 1, "UNEXPECTED-PERF28", "UNKNOWN"),
        ]
        db.add_all([
            BusinessOrderAlias(namespace=namespace, entity_id=entity_id, reference=reference,
                               canonical_reference=canonical)
            for namespace, entity_id, reference, canonical in aliases
        ])
        db.commit()
        references = [
            sales.order_no, production.production_no, usluga.production_no,
            request.request_no, purchase.po_no,
            "OLD-SO-PERF28", "OLD-PO-PERF28", "OLD-USL-PERF28",
            "OLD-PR-PERF28", "OLD-PUR-PERF28", "OLD-PUBLIC-PERF28",
            "OLD-PUBLIC-LINKED-PERF28", " OLD-SO-PERF28 ",
            "MISSING-PERF28", "AMBIGUOUS-PERF28", "UNEXPECTED-PERF28",
            "SO-PERF28-MISSING", "supplier handwritten reference",
        ]

        def outcome(reference, lookup=None):
            try:
                return ("value", canonical_business_order_reference(db, reference, lookup=lookup))
            except Exception as exc:  # Compare public error contract as well as values.
                return (type(exc), getattr(exc, "status_code", None), str(exc))

        expected = {reference: outcome(reference) for reference in references}
        lookup = BusinessOrderReferenceLookup(db, references)
        assert {reference: outcome(reference, lookup) for reference in references} == expected
