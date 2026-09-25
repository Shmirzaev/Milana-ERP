from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models import AuditLog, Item, PurchaseOrder, PurchaseRequest, PurchaseRequestLine, User
from app.services.purchasing import approve_purchase_request, convert_purchase_request_to_order
from app.tests.conftest import TestSessionLocal


def _legacy_request(status: str) -> tuple[int, int]:
    marker = uuid4().hex[:10].upper()
    with TestSessionLocal() as db:
        actor = db.query(User).order_by(User.id).first()
        item = Item(
            sku=f"LEGACY-REQUEST-{marker}", name="Legacy request material",
            category="accessory", unit="pcs",
        )
        request = PurchaseRequest(
            request_no=f"LEGACY-REQUEST-{marker}", status=status,
            requested_by=actor.id,
        )
        db.add_all([item, request])
        db.flush()
        db.add_all([
            PurchaseRequestLine(
                purchase_request_id=request.id, item_id=item.id,
                required_quantity=1, requested_quantity=1, unit="pcs",
                material_name="Original material",
            )
            for _ in range(1001)
        ])
        db.commit()
        return int(request.id), int(actor.id)


@pytest.mark.parametrize(
    ("status", "action"),
    [("pending_approval", "approve"), ("approved", "convert")],
)
def test_legacy_request_over_line_limit_fails_before_any_write(status, action):
    request_id, actor_id = _legacy_request(status)
    with TestSessionLocal() as db:
        before = (
            db.query(PurchaseOrder).filter_by(purchase_request_id=request_id).count(),
            db.query(AuditLog).count(),
        )
        actor = db.get(User, actor_id)
        with pytest.raises(HTTPException) as error:
            if action == "approve":
                approve_purchase_request(
                    db, request_id=request_id,
                    data={"lines": [{"purchase_request_line_id": 1}]}, current=actor,
                )
            else:
                convert_purchase_request_to_order(
                    db, request_id=request_id,
                    data={
                        "expected_date": datetime(2026, 10, 1, tzinfo=timezone.utc),
                        "lines": [{"purchase_request_line_id": 1, "ordered_quantity": 1}],
                    },
                    current=actor,
                )
        assert error.value.status_code == 409
        assert "reconcile" in error.value.detail
        assert not db.new
        assert not db.dirty
        db.rollback()

    with TestSessionLocal() as db:
        request = db.get(PurchaseRequest, request_id)
        assert request.status == status
        assert request.approved_at is None
        assert db.query(PurchaseRequestLine).filter_by(purchase_request_id=request_id).count() == 1001
        assert db.query(PurchaseRequestLine).filter_by(purchase_request_id=request_id).filter(
            PurchaseRequestLine.material_name != "Original material"
        ).count() == 0
        assert (
            db.query(PurchaseOrder).filter_by(purchase_request_id=request_id).count(),
            db.query(AuditLog).count(),
        ) == before


@pytest.mark.parametrize("action", ["approve", "convert"])
def test_legacy_request_guard_preserves_missing_request_precedence(action):
    with TestSessionLocal() as db:
        actor = db.query(User).order_by(User.id).first()
        with pytest.raises(HTTPException) as error:
            if action == "approve":
                approve_purchase_request(db, request_id=2_147_483_647, data={}, current=actor)
            else:
                convert_purchase_request_to_order(db, request_id=2_147_483_647, data={}, current=actor)
        assert error.value.status_code == 404


def test_legacy_conversion_preserves_required_date_error():
    request_id, actor_id = _legacy_request("approved")
    with TestSessionLocal() as db:
        with pytest.raises(HTTPException) as error:
            convert_purchase_request_to_order(
                db, request_id=request_id, data={"lines": []}, current=db.get(User, actor_id),
            )
        assert error.value.status_code == 400
        assert error.value.detail == "Expected date is required"
