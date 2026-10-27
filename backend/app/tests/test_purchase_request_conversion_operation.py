"""Conversion extraction: typed boundary, schema-owned writes, atomic refusals.

Uses the suite's isolated SessionLocal database. No application participant is
replaced in success/rollback cases; spies delegate to the real implementation.
"""
import sys
from datetime import datetime, timezone
from typing import get_type_hints
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import and_, event, inspect, or_
from sqlalchemy.orm import Session, object_session

from app.db.session import SessionLocal
from app.libs.dto.purchasing.purchase_request_input import PurchaseRequestOrderIn
from app.libs.enums.purchasing import PurchaseOrderStatus, PurchaseRequestStatus
from app.libs.types.purchasing import (
    PurchaseOrderCreateCommand,
    PurchaseRequestConversionCommand,
)
from app.models import purchasing_service as core
from app.models.purchasing import orders_service as orders_public
from app.models.purchasing import requests_service as public
from app.schemas import (
    AuditLog,
    Department,
    Item,
    Notification,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseRequest,
    PurchaseRequestLine,
    Supplier,
    User,
)
from app.schemas.purchasing import purchase_order_persistence as persistence

EXPECTED_DATE = datetime(2026, 11, 1, tzinfo=timezone.utc)


@pytest.fixture
def conversion_case():
    with SessionLocal() as db:
        token = uuid4().hex
        for code, name in (("PLN", "Planning"), ("STR", "Store")):
            if db.query(Department).filter_by(code=code).first() is None:
                db.add(Department(code=code, name=name))
        db.flush()
        store = db.query(Department).filter_by(code="STR").one()
        actor = User(name="Conversion actor", email=token + "@conversion.invalid",
                     password_hash="unused", department_id=store.id,
                     extra_permissions=["purchasing.order"])
        receiver = User(name="Conversion receiver", email=token + "r@conversion.invalid",
                        password_hash="unused", department_id=store.id, is_active=True)
        db.add_all([actor, receiver])
        db.flush()
        request = PurchaseRequest(request_no="CONV-" + token, status="approved", requested_by=actor.id)
        db.add(request)
        db.flush()
        lines = []
        for index in range(2):
            item = Item(sku=token + str(index), name="Fabric", category="fabric", unit="m")
            supplier = Supplier(name=token + str(index))
            db.add_all([item, supplier])
            db.flush()
            line = PurchaseRequestLine(purchase_request_id=request.id, item_id=item.id, unit="m",
                                       requested_quantity=10, material_name="Approved " + str(index),
                                       photo_url="/after-" + str(index) + ".jpg",
                                       preferred_supplier_id=supplier.id)
            db.add(line)
            db.flush()
            lines.append(dict(purchase_request_line_id=line.id, ordered_quantity=10 + index))
        db.commit()
        return dict(id=request.id, number=request.request_no, actor=actor.id,
                    receiver=receiver.id, lines=lines)


def payload(case):
    return PurchaseRequestOrderIn.model_validate(
        {"expected_date": EXPECTED_DATE, "lines": case["lines"]}
    )


def convert(case):
    with SessionLocal() as db:
        return public.convert_purchase_request_to_order(
            db, request_id=case["id"], payload=payload(case), current=db.get(User, case["actor"])
        )


def state(case):
    with SessionLocal() as db:
        request = db.get(PurchaseRequest, case["id"])
        orders = db.query(PurchaseOrder).filter_by(purchase_request_id=case["id"]).all()
        titles = [f"Purchase order ready for receiving: {order.po_no}" for order in orders]
        notifications = []
        if titles:
            notifications = [(n.title, n.user_id) for n in db.query(Notification).filter(
                Notification.title.in_(titles)).order_by(Notification.id)]
        order_ids = [order.id for order in orders]
        audits = [row for row in db.query(AuditLog).filter(
            or_(
                and_(AuditLog.entity_type == "PurchaseRequest", AuditLog.entity_id == case["id"]),
                and_(AuditLog.entity_type == "PurchaseOrder", AuditLog.entity_id.in_(order_ids)),
            )
        ).order_by(AuditLog.id)]
        return dict(
            status=request.status,
            orders=[(o.po_no, o.status, o.supplier_id, o.expected_date, o.notes,
                     [(l.item_id, l.ordered_quantity, l.unit_cost, l.supplier_id,
                       l.material_name, l.photo_url) for l in o.lines]) for o in orders],
            audits=[(a.action, a.entity_type, a.old_value_json, a.new_value_json) for a in audits],
            notifications=notifications,
        )


def test_conversion_contracts_are_used_and_canonical():
    assert get_type_hints(core.convert_purchase_request_to_order)["data"] is PurchaseRequestConversionCommand
    assert get_type_hints(core.create_purchase_order)["data"] is PurchaseOrderCreateCommand
    assert get_type_hints(public._purchase_request_conversion_command)["return"] is PurchaseRequestConversionCommand
    assert get_type_hints(orders_public._purchase_order_command)["return"] is PurchaseOrderCreateCommand
    assert get_type_hints(persistence.add_purchase_order_row)["status"] is PurchaseOrderStatus
    assert get_type_hints(persistence.apply_purchase_request_conversion)["status"] is PurchaseRequestStatus
    assert {status.value for status in core.ORDER_CREATE_STATUSES} == {"draft", "sent"}
    assert all(isinstance(status, PurchaseOrderStatus) for status in core.ORDER_CREATE_STATUSES)
    assert {status.value for status in PurchaseOrderStatus} == {
        "draft", "sent", "approved", "partially_received", "received"}


def test_conversion_creates_sent_order_and_marks_the_request_converted(conversion_case):
    order = convert(conversion_case)
    persisted = state(conversion_case)
    assert order.status == "sent"
    assert persisted["status"] == "converted"
    assert len(persisted["orders"]) == 1
    po_no, status, supplier_id, expected_date, notes, lines = persisted["orders"][0]
    assert status == "sent" and expected_date == EXPECTED_DATE.replace(tzinfo=None)
    assert notes == "Converted from " + conversion_case["number"]
    assert [line[1] for line in lines] == [10, 11]
    assert all(line[2] == 0 for line in lines)
    assert [line[4] for line in lines] == ["Approved 0", "Approved 1"]
    assert [line[5] for line in lines] == ["/after-0.jpg", "/after-1.jpg"]
    actions = [(action, entity) for action, entity, _old, _new in persisted["audits"]]
    assert ("create", "PurchaseOrder") in actions
    assert ("convert_to_order", "PurchaseRequest") in actions
    convert_audit = [row for row in persisted["audits"] if row[0] == "convert_to_order"][0]
    assert convert_audit[2] == {"status": "approved"}
    assert convert_audit[3] == {"status": "converted", "request_no": conversion_case["number"],
                                 "po_no": po_no}


def test_conversion_notifies_the_store_without_the_actor(conversion_case):
    convert(conversion_case)
    persisted = state(conversion_case)
    notifications = persisted["notifications"]
    expected_title = "Purchase order ready for receiving: " + persisted["orders"][0][0]
    assert notifications, "the store department must be notified"
    assert {title for title, _user in notifications} == {expected_title}
    assert conversion_case["receiver"] in [user for _title, user in notifications]
    assert conversion_case["actor"] not in [user for _title, user in notifications]


@pytest.mark.parametrize("case_name,expected_status,expected_detail", [
    ("not_approved", 409, "Only approved purchase requests can be converted (current: 'pending_approval')"),
    ("line_count", 400, "Order quantity is required for every request line"),
    ("unknown_line", 400, "Order lines must match the approved purchase request"),
    ("zero_quantity", 400, "Ordered quantity must be greater than zero"),
    ("no_expected_date", 400, "Expected date is required"),
])
def test_conversion_refusals_leave_no_partial_effects(conversion_case, case_name, expected_status, expected_detail):
    with SessionLocal() as db:
        request = db.get(PurchaseRequest, conversion_case["id"])
        if case_name == "not_approved":
            request.status = "pending_approval"
            db.commit()
        lines = list(conversion_case["lines"])
        expected_date = EXPECTED_DATE
        if case_name == "line_count":
            lines = lines[:1]
        elif case_name == "unknown_line":
            lines = [dict(lines[0], purchase_request_line_id=999999), lines[1]]
        elif case_name == "zero_quantity":
            lines = [dict(lines[0], ordered_quantity=0), lines[1]]
        elif case_name == "no_expected_date":
            expected_date = None
        command = {"expected_date": expected_date, "lines": lines}
        with pytest.raises(HTTPException) as error:
            core.convert_purchase_request_to_order(
                db, request_id=conversion_case["id"], data=command,
                current=db.get(User, conversion_case["actor"]),
            )
        assert error.value.status_code == expected_status
        assert error.value.detail == expected_detail
        db.rollback()
    persisted = state(conversion_case)
    assert persisted["orders"] == []
    assert persisted["status"] == ("pending_approval" if case_name == "not_approved" else "approved")
    assert persisted["audits"] == []


def test_conversion_rollback_then_retry_succeeds(conversion_case, monkeypatch):
    original = core.notify_department

    def fail_after_real_write(db, *args, **kwargs):
        original(db, *args, **kwargs)
        db.flush()
        raise RuntimeError("injected after the real order notification")

    with monkeypatch.context() as patch:
        patch.setattr(core, "notify_department", fail_after_real_write)
        with pytest.raises(RuntimeError, match="injected after"):
            convert(conversion_case)
    persisted = state(conversion_case)
    assert persisted["orders"] == [] and persisted["status"] == "approved"
    convert(conversion_case)
    assert len(state(conversion_case)["orders"]) == 1
    assert state(conversion_case)["status"] == "converted"


def test_conversion_mapped_writes_are_schema_owned_and_one_commit(conversion_case):
    writes, commits, mutation_sessions = [], [], []
    participants = (PurchaseOrder, PurchaseOrderLine, PurchaseRequest, AuditLog, Notification)

    def assignment(target, value, previous, initiator):
        session = object_session(target)
        if session is not None:
            mutation_sessions.append(id(session))
        frame = sys._getframe(1)
        while frame:
            module = frame.f_globals.get("__name__", "")
            if module.startswith("app."):
                writes.append((type(target).__name__, initiator.key, module, frame.f_code.co_name))
                break
            frame = frame.f_back

    def commit(session):
        commits.append(id(session))

    attributes = [getattr(cls, column.key)
                  for cls in participants for column in inspect(cls).column_attrs]
    for attribute in attributes:
        event.listen(attribute, "set", assignment)
    event.listen(Session, "before_commit", commit)
    try:
        convert(conversion_case)
    finally:
        for attribute in attributes:
            event.remove(attribute, "set", assignment)
        event.remove(Session, "before_commit", commit)

    expected = {
        ("PurchaseOrder", "status"), ("PurchaseOrder", "po_no"),
        ("PurchaseOrderLine", "ordered_quantity"), ("PurchaseOrderLine", "unit_cost"),
        ("PurchaseRequest", "status"),
    }
    assert expected <= {(table, field) for table, field, _module, _fn in writes}, writes
    violations = [row for row in writes if not row[2].startswith("app.schemas.")]
    assert not violations, f"Mapped writes outside owning schemas: {violations}"
    assert len(commits) == 1
    assert mutation_sessions and set(mutation_sessions) == set(commits)


@pytest.mark.parametrize("raw_status", ["approved", "received", "weird"])
def test_order_status_outside_the_creation_subset_is_refused(raw_status):
    with pytest.raises(HTTPException) as error:
        core._order_create_status(raw_status)
    assert error.value.status_code == 400
    assert error.value.detail == "Purchase order status must be draft or sent"


def test_order_creation_default_status_is_draft(conversion_case):
    from app.libs.dto.purchasing.purchase_order_input import PurchaseOrderIn

    command = orders_public._purchase_order_command(
        PurchaseOrderIn.model_validate({"lines": [{"item_id": 1, "ordered_quantity": 5}]})
    )
    assert command["status"] is PurchaseOrderStatus.DRAFT
    assert core._order_create_status(None) is PurchaseOrderStatus.DRAFT
    assert core._order_create_status("") is PurchaseOrderStatus.DRAFT
    assert core._order_create_status(PurchaseOrderStatus.SENT) is PurchaseOrderStatus.SENT
