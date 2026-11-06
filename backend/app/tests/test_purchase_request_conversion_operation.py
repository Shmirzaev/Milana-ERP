"""Conversion extraction: typed boundary, schema-owned writes, atomic refusals.

Uses the suite's isolated SessionLocal database. No application participant is
replaced in success/rollback cases; spies delegate to the real implementation.
"""
import sys
from datetime import datetime, timedelta, timezone
from typing import get_type_hints
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import and_, event, inspect, or_
from sqlalchemy.orm import Session, object_session

from app.db.session import SessionLocal
from app.libs.dto.purchasing.purchase_request_input import PurchaseRequestOrderIn
from app.libs.dto.purchasing.purchase_order_output import PurchaseOrderCreationOut, PurchaseOrderOut
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
    assert isinstance(order, PurchaseOrderCreationOut)
    assert order.status is PurchaseOrderStatus.SENT
    persisted = state(conversion_case)
    assert order.status == "sent"
    assert persisted["status"] == "converted"
    assert len(persisted["orders"]) == 1
    po_no, status, supplier_id, expected_date, notes, lines = persisted["orders"][0]
    assert status == "sent"
    # SQLite returns a naive datetime; PostgreSQL preserves an aware instant.
    actual_instant = expected_date.replace(tzinfo=timezone.utc) if expected_date.tzinfo is None else expected_date.astimezone(timezone.utc)
    assert actual_instant == EXPECTED_DATE
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


def test_operation_result_contract_and_legacy_status():
    from app.api.routes.purchasing import router, create_order, convert_request_to_order
    from app.main import app
    assert get_type_hints(PurchaseOrderCreationOut)["status"] is PurchaseOrderStatus
    assert get_type_hints(PurchaseOrderOut)["status"] is str
    assert get_type_hints(public.convert_purchase_request_to_order)["return"] is PurchaseOrderCreationOut
    assert get_type_hints(orders_public.create_purchase_order)["return"] is PurchaseOrderCreationOut
    schema = PurchaseOrderCreationOut.model_json_schema()
    assert schema["properties"]["status"]["$ref"].endswith("/PurchaseOrderStatus")
    assert "enum" not in PurchaseOrderOut.model_json_schema()["properties"]["status"]
    routes = {(route.path, method): route for route in router.routes for method in route.methods}
    assert routes[("/purchasing/orders", "POST")].response_model is PurchaseOrderCreationOut
    assert routes[("/purchasing/requests/{request_id}/convert-to-order", "POST")].response_model is PurchaseOrderCreationOut
    assert routes[("/purchasing/orders/{order_id}/receive", "POST")].response_model is PurchaseOrderOut
    assert get_type_hints(create_order)["return"] is PurchaseOrderCreationOut
    assert get_type_hints(convert_request_to_order)["return"] is PurchaseOrderCreationOut
    openapi = app.openapi()
    for path in ("/api/purchasing/orders", "/api/purchasing/requests/{request_id}/convert-to-order"):
        response = openapi["paths"][path]["post"]["responses"]["201"]["content"]["application/json"]["schema"]
        assert response == {"$ref": "#/components/schemas/PurchaseOrderCreationOut"}
    schemas = openapi["components"]["schemas"]
    assert schemas["PurchaseOrderCreationOut"]["properties"]["status"] == {"$ref": "#/components/schemas/PurchaseOrderStatus"}
    assert set(schemas["PurchaseOrderStatus"]["enum"]) == {status.value for status in PurchaseOrderStatus}


def test_create_result_and_legacy_unknown_status(conversion_case):
    from app.libs.dto.purchasing.purchase_order_input import PurchaseOrderIn
    from pydantic import ValidationError

    with SessionLocal() as db:
        request = db.get(PurchaseRequest, conversion_case["id"])
        item_id = request.lines[0].item_id
        result = orders_public.create_purchase_order(
            db, payload=PurchaseOrderIn.model_validate({
                "status": "sent", "lines": [{"item_id": item_id, "ordered_quantity": 5}]
            }), current=db.get(User, conversion_case["actor"])
        )
    assert result.status is PurchaseOrderStatus.DRAFT
    assert result.model_dump(mode="json")["status"] == "draft"
    raw = result.model_dump(mode="json")
    raw["status"] = "historical_custom"
    assert PurchaseOrderOut.model_validate(raw).status == "historical_custom"
    with pytest.raises(ValidationError):
        PurchaseOrderCreationOut.model_validate(raw)


@pytest.mark.parametrize("operation", ["create", "convert"])
def test_result_json_matches_fresh_order_including_offset_date(conversion_case, operation):
    from app.libs.dto.purchasing.purchase_order_input import PurchaseOrderIn
    offset_date = datetime(2026, 11, 1, 16, 30, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    with SessionLocal() as db:
        actor = db.get(User, conversion_case["actor"])
        if operation == "create":
            request = db.get(PurchaseRequest, conversion_case["id"])
            command = PurchaseOrderIn.model_validate({
                "expected_date": offset_date,
                "lines": [{"item_id": request.lines[0].item_id, "ordered_quantity": 5}],
            })
            result = orders_public.create_purchase_order(db, payload=command, current=actor)
        else:
            command = PurchaseRequestOrderIn.model_validate({
                "expected_date": offset_date, "lines": conversion_case["lines"],
            })
            result = public.convert_purchase_request_to_order(
                db, request_id=conversion_case["id"], payload=command, current=actor)
    with SessionLocal() as db:
        fresh = PurchaseOrderOut.model_validate(db.get(PurchaseOrder, result.id))
        assert result.model_dump(mode="json") == fresh.model_dump(mode="json")


def test_refresh_and_validation_precede_the_single_commit(conversion_case, monkeypatch):
    calls = []
    original_refresh = Session.refresh
    original_validate = PurchaseOrderCreationOut.model_validate

    def refresh(db, instance, *args, **kwargs):
        if isinstance(instance, PurchaseOrder):
            assert object_session(instance) is db
            calls.append(("refresh", id(db)))
        return original_refresh(db, instance, *args, **kwargs)

    def validate(instance, *args, **kwargs):
        calls.append(("validate", id(object_session(instance))))
        return original_validate(instance, *args, **kwargs)

    def before_commit(db):
        calls.append(("commit", id(db)))

    with monkeypatch.context() as patch:
        patch.setattr(Session, "refresh", refresh)
        patch.setattr(PurchaseOrderCreationOut, "model_validate", validate)
        event.listen(Session, "before_commit", before_commit)
        try:
            convert(conversion_case)
        finally:
            event.remove(Session, "before_commit", before_commit)
    assert [action for action, _ in calls] == ["refresh", "validate", "commit"]
    assert len({session for _, session in calls}) == 1


def test_duplicate_conversion_line_is_refused_without_effects(conversion_case):
    case = conversion_case
    before = _participant_counts()
    with SessionLocal() as db:
        lines = [case["lines"][0], case["lines"][0]]
        with pytest.raises(HTTPException) as error:
            core.convert_purchase_request_to_order(
                db, request_id=case["id"], data={"expected_date": EXPECTED_DATE, "lines": lines},
                current=db.get(User, case["actor"]),
            )
        assert error.value.status_code == 400
        assert error.value.detail == "Order lines must match the approved purchase request"
        db.rollback()
    assert _participant_counts() == before
    assert state(case)["status"] == "approved"


def _participant_counts():
    with SessionLocal() as db:
        return tuple(db.query(cls).count() for cls in (PurchaseOrder, PurchaseOrderLine, AuditLog, Notification))


@pytest.mark.parametrize("fault", ["access", "audit", "before_commit", "result"])
def test_late_failure_rolls_back_all_participants_and_retry(conversion_case, monkeypatch, fault):
    case = conversion_case
    if fault == "access":
        with SessionLocal() as db:
            actor = db.get(User, case["actor"])
            actor.extra_permissions = ["purchasing.order", "inventory.materials_only"]
            request = db.get(PurchaseRequest, case["id"])
            request.lines[0].item.category = "accessory"
            db.commit()
    baseline = _participant_counts()
    captured = {}

    def capture(db):
        db.flush()
        order = db.query(PurchaseOrder).filter_by(purchase_request_id=case["id"]).one()
        captured.update(id=order.id, title="Purchase order ready for receiving: " + order.po_no)
        assert db.get(PurchaseRequest, case["id"]).status == "converted"
        assert db.query(PurchaseOrderLine).filter_by(purchase_order_id=order.id).count() == 2
        assert db.query(AuditLog).filter_by(entity_type="PurchaseOrder", entity_id=order.id).count() == 1
        assert db.query(AuditLog).filter_by(entity_type="PurchaseRequest", entity_id=case["id"]).count() == 1
        assert db.query(Notification).filter_by(title=captured["title"]).count() >= 1

    original_access = core.require_purchase_item_access
    original_log = core.log_action
    with monkeypatch.context() as patch:
        if fault == "access":
            def fail_access(db, current, lines):
                capture(db)
                return original_access(db, current, lines)
            patch.setattr(core, "require_purchase_item_access", fail_access)
        elif fault == "audit":
            def fail_audit(db, *args, **kwargs):
                original_log(db, *args, **kwargs)
                if len(args) >= 3 and args[1:3] == ("convert_to_order", "PurchaseRequest"):
                    capture(db)
                    raise RuntimeError("late audit fault")
            patch.setattr(core, "log_action", fail_audit)
        elif fault == "before_commit":
            def fail_commit(db):
                capture(db)
                raise RuntimeError("before commit fault")
            event.listen(Session, "before_commit", fail_commit)
        else:
            def fail_result(*args, **kwargs):
                raise ValueError("result validation fault")
            # Capture after real writes and before the result is built.
            def capture_access(db, current, lines):
                original_access(db, current, lines)
                capture(db)
            patch.setattr(core, "require_purchase_item_access", capture_access)
            patch.setattr(PurchaseOrderCreationOut, "model_validate", fail_result)
        try:
            with pytest.raises((HTTPException, RuntimeError, ValueError)) as error:
                convert(case)
            if fault == "access":
                assert error.value.status_code == 403
        finally:
            if fault == "before_commit":
                event.remove(Session, "before_commit", fail_commit)

    assert captured
    assert _participant_counts() == baseline
    with SessionLocal() as db:
        assert db.get(PurchaseRequest, case["id"]).status == "approved"
        assert db.get(PurchaseOrder, captured["id"]) is None
        assert db.query(PurchaseOrderLine).filter_by(purchase_order_id=captured["id"]).count() == 0
        assert db.query(AuditLog).filter_by(entity_type="PurchaseOrder", entity_id=captured["id"]).count() == 0
        assert db.query(AuditLog).filter_by(entity_type="PurchaseRequest", entity_id=case["id"]).count() == 0
        assert db.query(Notification).filter_by(title=captured["title"]).count() == 0
        if fault == "access":
            db.get(User, case["actor"]).extra_permissions = ["purchasing.order"]
            db.commit()
    result = convert(case)
    assert result.status is PurchaseOrderStatus.SENT
    assert len(state(case)["orders"]) == 1
    with pytest.raises(HTTPException) as error:
        convert(case)
    assert error.value.status_code == 409
