"""Approval extraction: actual typed boundary, schema calls and atomic failures.

Uses the suite's isolated SessionLocal database. No application participant is
replaced in success/rollback cases; spies delegate to the real implementation.
"""
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from typing import get_type_hints
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import object_session

from app.db.session import SessionLocal
from app.libs.dto.purchasing.purchase_request_input import PurchaseRequestApprovalIn
from app.libs.enums.purchasing import PurchaseRequestStatus
from app.libs.types.purchasing import (
    PurchaseRequestApprovalCommand, PurchaseRequestApprovalLineCommand,
    PurchaseRequestApprovalTransition,
)
from app.models import audit_service, purchasing_service as core
from app.models.purchasing import requests_service as public
from app.schemas import AuditLog, Department, Item, Notification, PurchaseRequest, PurchaseRequestLine, Supplier, User
from app.schemas.purchasing import purchase_request_persistence as persistence


@pytest.fixture
def approval_case():
    with SessionLocal() as db:
        token = uuid4().hex
        dept = db.query(Department).filter_by(code="PLN").first()
        if dept is None:
            dept = Department(code="PLN", name="Planning")
            db.add(dept); db.flush()
        actor = User(name="Approval extraction actor", email=token+"@approval.invalid",
                     password_hash="unused", department_id=dept.id, extra_permissions=["purchasing.approve"])
        recipient = User(name="Approval extraction recipient", email=token+"r@approval.invalid",
                         password_hash="unused", department_id=dept.id, is_active=True)
        db.add_all([actor, recipient]); db.flush()
        request = PurchaseRequest(request_no="APPROVAL-"+token, status="pending_approval", requested_by=actor.id)
        db.add(request); db.flush()
        lines = []
        for index in range(2):
            item = Item(sku=token+str(index), name="Fabric", category="fabric", unit="m")
            supplier = Supplier(name=token+str(index))
            db.add_all([item, supplier]); db.flush()
            line = PurchaseRequestLine(purchase_request_id=request.id, item_id=item.id, unit="m",
                requested_quantity=10, material_name="before", photo_url="/before.jpg")
            db.add(line); db.flush()
            lines.append(dict(purchase_request_line_id=line.id, material_name=f"  Approved {index}  ",
                              photo_url=f"  /after-{index}.jpg  ", preferred_supplier_id=supplier.id))
        db.commit()
        return dict(id=request.id, number=request.request_no, actor=actor.id, recipient=recipient.id,
                    payload={"lines":lines})


def persisted(case):
    with SessionLocal() as db:
        request = db.get(PurchaseRequest, case["id"])
        return dict(status=request.status, actor=request.approved_by, at=request.approved_at,
            updated=request.updated_at,
            lines=[(line.id, line.material_name, line.photo_url, line.preferred_supplier_id, line.updated_at)
                   for line in sorted(request.lines, key=lambda row: row.id)],
            audits=[(a.id,a.action,a.old_value_json,a.new_value_json,a.entry_hash) for a in
                    db.query(AuditLog).filter_by(entity_type="PurchaseRequest",entity_id=request.id).order_by(AuditLog.id)],
            notifications=[(n.id,n.user_id) for n in db.query(Notification).filter_by(
                title="Purchase request approved: "+case["number"]).order_by(Notification.id)])


def approve(case):
    with SessionLocal() as db:
        return public.approve_purchase_request(db, request_id=case["id"],
            payload=PurchaseRequestApprovalIn.model_validate(case["payload"]), current=db.get(User,case["actor"]))


def assert_approved(case):
    state=persisted(case)
    assert state["status"] == "approved" and state["actor"] == case["actor"] and state["at"] is not None
    assert [row[:4] for row in state["lines"]] == [
        (line["purchase_request_line_id"],f"Approved {i}",f"/after-{i}.jpg",line["preferred_supplier_id"])
        for i,line in enumerate(case["payload"]["lines"])]
    assert len(state["audits"]) == 1
    assert state["audits"][0][1:4] == ("approve", {"status":"pending_approval"},
        {"status":"approved","request_no":case["number"]})
    assert case["recipient"] in [recipient for _,recipient in state["notifications"]]
    assert case["actor"] not in [recipient for _,recipient in state["notifications"]]


def test_approval_contracts_are_used_and_canonical():
    assert get_type_hints(core.approve_purchase_request)["data"] is PurchaseRequestApprovalCommand
    assert get_type_hints(public._purchase_request_approval_command)["return"] is PurchaseRequestApprovalCommand
    assert get_type_hints(PurchaseRequestApprovalLineCommand) == {
        "purchase_request_line_id":int,"material_name":str,"preferred_supplier_id":int,"photo_url":str}
    transition=PurchaseRequestApprovalTransition(PurchaseRequestStatus.DRAFT,PurchaseRequestStatus.APPROVED,
                                                1,datetime.now(timezone.utc))
    assert transition.previous_status is PurchaseRequestStatus.DRAFT
    assert transition.status is PurchaseRequestStatus.APPROVED
    for field in ("previous_status","status"):
        assert get_type_hints(PurchaseRequestApprovalTransition)[field] is PurchaseRequestStatus
    assert get_type_hints(persistence.apply_purchase_request_approval)["status"] is PurchaseRequestStatus
    assert core.REQUEST_APPROVABLE_STATUSES == {"draft","pending_approval"}
    assert all(isinstance(status,PurchaseRequestStatus) for status in core.REQUEST_APPROVABLE_STATUSES)
    with pytest.raises(FrozenInstanceError):
        transition.status = PurchaseRequestStatus.REJECTED


def test_actual_public_command_and_all_writers_share_session(approval_case,monkeypatch):
    calls=[]
    original_core=core.approve_purchase_request
    def boundary(db, *, request_id, data, current):
        assert data == approval_case["payload"]  # Neither trim nor drop fields at DTO boundary.
        calls.append(("command",db))
        return original_core(db,request_id=request_id,data=data,current=current)
    monkeypatch.setattr(core,"approve_purchase_request",boundary)
    def line_writer(db,line,**fields):
        assert object_session(line) is db and line.material_name == "before"
        calls.append(("line",db))
        return persistence.apply_purchase_request_line_approval(db,line,**fields)
    def header_writer(db,request,**fields):
        assert object_session(request) is db and request.status == "pending_approval"
        assert fields["status"] is PurchaseRequestStatus.APPROVED
        calls.append(("header",db))
        return persistence.apply_purchase_request_approval(db,request,**fields)
    monkeypatch.setattr(core,"apply_purchase_request_line_approval",line_writer)
    monkeypatch.setattr(core,"apply_purchase_request_approval",header_writer)
    for name in ("log_action","notify_department","require_purchase_item_access"):
        original=getattr(core,name)
        def spy(db,*args,_name=name,_original=original,**kwargs):
            calls.append((_name,db))
            return _original(db,*args,**kwargs)
        monkeypatch.setattr(core,name,spy)
    approve(approval_case)
    assert [name for name,_ in calls] == ["command","line","line","header","log_action",
                                         "notify_department","require_purchase_item_access"]
    assert all(session is calls[0][1] for _,session in calls)
    assert_approved(approval_case)


@pytest.mark.parametrize("participant",["log_action","notify_department"])
def test_real_participant_failure_rolls_back_then_retry_succeeds(approval_case,monkeypatch,participant):
    before=persisted(approval_case)
    original=getattr(core,participant)
    proof={}
    def fail_after_real_write(db,*args,**kwargs):
        original(db,*args,**kwargs)
        db.flush()
        if db.get_bind().dialect.name == "postgresql":
            audit_service._finalize_postgres_audits(db)
        request=db.get(PurchaseRequest,approval_case["id"])
        assert request.status == "approved" and request.lines[0].material_name.startswith("Approved")
        assert db.query(AuditLog).filter_by(entity_type="PurchaseRequest",entity_id=request.id).count()==1
        if participant == "notify_department":
            assert db.query(Notification).filter_by(title="Purchase request approved: "+request.request_no).count()>0
        proof["flushed"]=True
        raise RuntimeError("injected after real participant persistence")
    with monkeypatch.context() as patch:
        patch.setattr(core,participant,fail_after_real_write)
        with pytest.raises(RuntimeError,match="injected after real"):
            approve(approval_case)
    assert proof["flushed"] and persisted(approval_case)==before
    approve(approval_case)
    assert_approved(approval_case)


def test_unknown_stored_status_is_409_before_enum_parsing(approval_case):
    with SessionLocal() as db:
        db.get(PurchaseRequest,approval_case["id"]).status="legacy_unknown"
        db.commit()
    before=persisted(approval_case)
    with pytest.raises(HTTPException) as error:
        approve(approval_case)
    assert error.value.status_code==409
    assert error.value.detail=="Cannot approve purchase request in status 'legacy_unknown'"
    assert persisted(approval_case)==before


def test_direct_approved_retry_accepts_empty_command_without_schema_writes(approval_case,monkeypatch):
    approve(approval_case); before=persisted(approval_case)
    def unexpected(*args,**kwargs):
        pytest.fail("Approved retry must not repeat schema approval writes")
    monkeypatch.setattr(core,"apply_purchase_request_line_approval",unexpected)
    monkeypatch.setattr(core,"apply_purchase_request_approval",unexpected)
    with SessionLocal() as db:
        request=core.approve_purchase_request(db,request_id=approval_case["id"],data={},
                                             current=db.get(User,approval_case["actor"]))
        assert request.id==approval_case["id"] and request.status=="approved"
        db.rollback()
    assert persisted(approval_case)==before
