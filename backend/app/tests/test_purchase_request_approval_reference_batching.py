from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app.models import AuditLog, Item, PurchaseRequest, PurchaseRequestLine, Supplier, User
from app.services import purchasing
from app.tests.conftest import TestSessionLocal


def _pending_request(line_count: int):
    suffix = uuid4().hex[:8].upper()
    with TestSessionLocal() as db:
        current = db.query(User).order_by(User.id).first()
        request = PurchaseRequest(
            request_no=f"PR-PERF28-APPROVE-{suffix}",
            status="pending_approval",
            requested_by=current.id,
        )
        items = [
            Item(
                sku=f"PERF28-APPROVE-{suffix}-{index}",
                name=f"Approval item {index}",
                category="accessory",
                unit="pcs",
            )
            for index in range(line_count)
        ]
        suppliers = [Supplier(name=f"PERF28 approval supplier {suffix}-{index}") for index in range(line_count)]
        db.add_all([request, *items, *suppliers])
        db.flush()
        lines = [
            PurchaseRequestLine(
                purchase_request_id=request.id,
                item_id=item.id,
                required_quantity=1,
                requested_quantity=1,
                unit="pcs",
                preferred_supplier_id=supplier.id,
            )
            for item, supplier in zip(items, suppliers, strict=True)
        ]
        db.add_all(lines)
        db.commit()
        return (
            int(request.id),
            [int(line.id) for line in lines],
            [int(supplier.id) for supplier in suppliers],
        )


@pytest.mark.parametrize("line_count, expected_supplier_selects", [(1, 1), (50, 1), (401, 2)])
def test_purchase_request_approval_batches_supplier_existence_reads(
    monkeypatch,
    line_count,
    expected_supplier_selects,
):
    monkeypatch.setattr(purchasing, "notify_department", lambda *_args, **_kwargs: None)
    request_id, line_ids, supplier_ids = _pending_request(line_count)
    approval_lines = [
        {
            "purchase_request_line_id": line_id,
            "material_name": f"Approved material {index}",
            "photo_url": f"/approved/{index}.png",
            "preferred_supplier_id": supplier_id,
        }
        for index, (line_id, supplier_id) in enumerate(zip(line_ids, supplier_ids, strict=True))
    ]

    supplier_selects = []
    audit_head_selects = []
    with TestSessionLocal() as db:
        current = db.query(User).order_by(User.id).first()

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            normalized = " ".join(statement.lower().split())
            if normalized.startswith("select") and " from suppliers " in normalized:
                supplier_selects.append(normalized)
            if normalized.startswith("select") and " from audit_logs " in normalized:
                audit_head_selects.append(normalized)

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            purchasing.approve_purchase_request(
                db,
                request_id=request_id,
                data={"lines": approval_lines},
                current=current,
            )
            db.commit()
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

        persisted_supplier_ids = [
            int(value)
            for (value,) in db.query(PurchaseRequestLine.preferred_supplier_id)
            .filter(PurchaseRequestLine.purchase_request_id == request_id)
            .order_by(PurchaseRequestLine.id)
            .all()
        ]
        assert db.query(AuditLog).filter_by(
            action="approve", entity_type="PurchaseRequest", entity_id=request_id,
        ).count() == 1

    assert len(supplier_selects) == expected_supplier_selects
    assert all("select suppliers.id " in sql for sql in supplier_selects)
    assert len(audit_head_selects) == 1
    assert persisted_supplier_ids == supplier_ids


def test_purchase_request_approval_batch_lookup_preserves_line_error_precedence(monkeypatch):
    monkeypatch.setattr(purchasing, "notify_department", lambda *_args, **_kwargs: None)
    request_id, line_ids, _supplier_ids = _pending_request(2)
    missing_supplier_id = 2_147_483_647

    with TestSessionLocal() as db:
        current = db.query(User).order_by(User.id).first()
        with pytest.raises(HTTPException) as error:
            purchasing.approve_purchase_request(
                db,
                request_id=request_id,
                current=current,
                data={
                    "lines": [
                        {
                            "purchase_request_line_id": line_ids[0],
                            "material_name": "Valid material",
                            "photo_url": "/valid.png",
                            "preferred_supplier_id": missing_supplier_id,
                        },
                        {
                            "purchase_request_line_id": 2_147_483_646,
                            "material_name": "Invalid request line",
                            "photo_url": "/invalid.png",
                            "preferred_supplier_id": 1,
                        },
                    ]
                },
            )
        assert error.value.status_code == 404
        assert error.value.detail == f"Supplier {missing_supplier_id} not found"
        db.rollback()

        request = db.get(PurchaseRequest, request_id)
        assert request.status == "pending_approval"
