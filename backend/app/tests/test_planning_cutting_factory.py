"""Routing may move only unrecorded Cutting, with both factory grants.

Fixtures are synthetic. Expected behavior is asserted through HTTP and fresh
sessions; fault injection checks transaction rollback after the routing flush.
"""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.security import create_access_token
from app.libs.dto.planning.production_cutting_factory import ProductionCuttingFactoryIn
from app.libs.enums.production import CuttingDepartmentCode
from app.models.planning import cutting_factory_service as service
from app.schemas import (
    AuditLog, Bundle, CuttingPassport, CuttingRecord, Department, FinishedGoodsStock, Item, MaterialReservation, Model,
    PrintingRecord, ProductionBatch, ProductionOrder, QualityCheck, Role,
    SewingAssignment, SewingFlow, SewingRecord, User, WorkOrder,
)
from app.tests.conftest import TestSessionLocal


def make_order(db, *, source="CUT", both=True, permissions=None, policy=None):
    marker = uuid4().hex[:12]
    depts = {}
    for code in ("CUT", "ECT", "PRT", "MIL", "PKG", "FGS"):
        department = db.query(Department).filter_by(code=code).first()
        if department is None:
            department = Department(code=code, name=code)
            db.add(department); db.flush()
        depts[code] = department
    role = Role(name=f"QA planning {marker}", permissions=permissions if permissions is not None else ["planning.production"])
    actor = User(name="QA planning actor", email=f"{marker}@example.invalid", password_hash="unused",
                 role=role, factory_code="MIL", access_policy=policy,
                 extra_permissions=["factory:ECO:planning.production"] if both else [])
    model = Model(code=f"QA-CUT-{marker}", name="Routing fixture", status="approved")
    db.add_all([actor, model]); db.flush()
    order = ProductionOrder(production_no=f"QA-CUT-{marker}", production_type="branded_stock",
                            model_id=model.id, status="cutting", planned_quantity=120)
    db.add(order); db.flush()
    batch = ProductionBatch(production_order_id=order.id, batch_index=1, batch_no=f"QA-{marker}", planned_quantity=120)
    db.add(batch)
    works = {}
    for operation, code in (("cutting", source), ("printing", "PRT"), ("sewing", "MIL"), ("packaging", "PKG"), ("storage_transfer", "FGS")):
        work = WorkOrder(production_order_id=order.id, department_id=depts[code].id, operation=operation,
                         status="in_progress" if operation == "cutting" else "waiting",
                         start_time=datetime(2026, 11, 4, tzinfo=timezone.utc) if operation == "cutting" else None,
                         planned_input_qty=120, planned_output_qty=120)
        db.add(work); works[operation] = work
    db.commit()
    return order.id, actor.id, {op: work.id for op, work in works.items()}


def headers(actor_id):
    return {"Authorization": f"Bearer {create_access_token(actor_id, extra={'factory_code': 'MIL'})}"}


def route_snapshot(db, order_id):
    db.expire_all()
    return [{column.name: getattr(work, column.name) for column in WorkOrder.__table__.columns}
            for work in db.query(WorkOrder).filter_by(production_order_id=order_id).order_by(WorkOrder.id)]


def test_http_change_and_retry_preserve_complete_plans_and_downstream_history(client):
    with TestSessionLocal() as db:
        oid, uid, works = make_order(db, permissions=["planning.production", "cutting.records", "cutting.bundles"])
        before = route_snapshot(db, oid)
        batches_before = [(row.id, row.planned_quantity, row.batch_no) for row in db.query(ProductionBatch).filter_by(production_order_id=oid)]
    url = f"/api/production-orders/{oid}/cutting-factory"
    auth = headers(uid)
    options = client.get(url, headers=auth)
    assert options.status_code == 200, options.text
    assert options.json()["available_departments"] == ["CUT", "ECT"]
    assert options.json()["cutting_department_code"] == "CUT"
    assert options.json()["can_change"] is True
    for expected in (True, False):
        response = client.patch(url, headers=auth, json={"cutting_department_code": "ECT"})
        assert response.status_code == 200, response.text
        assert response.json()["changed"] is expected
    with TestSessionLocal() as db:
        after = route_snapshot(db, oid)
        for original, current in zip(before, after):
            changed = {key for key in original if original[key] != current[key]}
            assert changed <= ({"department_id", "updated_at"} if current["id"] == works["cutting"] else set())
        assert db.get(WorkOrder, works["cutting"]).department_id == db.query(Department.id).filter_by(code="ECT").scalar()
        assert db.get(ProductionOrder, oid).status == "cutting"
        assert batches_before == [(row.id, row.planned_quantity, row.batch_no) for row in db.query(ProductionBatch).filter_by(production_order_id=oid)]
        audits = db.query(AuditLog).filter_by(entity_id=oid, entity_type="ProductionOrder", action="change_cutting_factory").all()
        assert len(audits) == 1
        assert audits[0].old_value_json == {"cutting_department_code": "CUT"}
        assert audits[0].new_value_json["cutting_department_code"] == "ECT"
    # Cached old-source Cutting/Bundle/Quality clients must now be refused.
    assert client.post("/api/cutting/records", headers=auth, json={"work_order_id": works["cutting"], "cut_pieces": 1, "passed_pieces": 1, "input_quantity": 0}).status_code == 403
    assert client.post("/api/quality/checks", headers=auth, json={"work_order_id": works["cutting"], "checked_qty": 1, "passed_qty": 1, "failed_qty": 0}).status_code == 403
    with TestSessionLocal() as db:
        model_id = db.get(ProductionOrder, oid).model_id
    assert client.post("/api/bundles", headers=auth, json={"production_order_id": oid, "model_id": model_id, "color": "white", "size": "S", "quantity": 1}).status_code == 403
    assert client.get(url, headers=auth).json()["cutting_department_code"] == "ECT"


@pytest.mark.parametrize("source,both,permissions,policy", [
    ("CUT", False, None, None),
    ("ECT", False, None, None),
    ("CUT", True, [], None),
    ("CUT", True, ["*"], {"ECO": {"deny": ["planning.production"]}}),
    ("ECT", True, None, {"ECO": {"deny": ["planning.production"]}}),
])
def test_source_destination_and_session_permissions_are_enforced(client, source, both, permissions, policy):
    with TestSessionLocal() as db:
        oid, uid, works = make_order(db, source=source, both=both, permissions=permissions, policy=policy)
        before = route_snapshot(db, oid)
    response = client.patch(f"/api/production-orders/{oid}/cutting-factory", headers=headers(uid), json={"cutting_department_code": "ECT" if source == "CUT" else "CUT"})
    assert response.status_code == 403, response.text
    with TestSessionLocal() as db:
        assert route_snapshot(db, oid) == before
        assert db.query(AuditLog).filter_by(entity_id=oid, action="change_cutting_factory").count() == 0


@pytest.mark.parametrize("value", [None, "BST", "MIL", "", 12])
def test_action_rejects_unsupported_destinations(value):
    with pytest.raises(ValidationError):
        ProductionCuttingFactoryIn(cutting_department_code=value)


def test_action_enum_normalization_and_extra_field_refusal():
    value = ProductionCuttingFactoryIn(cutting_department_code=" ect ")
    assert value.cutting_department_code is CuttingDepartmentCode.ECO_COTTON
    assert value.model_dump(mode="json") == {"cutting_department_code": "ECT"}
    with pytest.raises(ValidationError):
        ProductionCuttingFactoryIn(cutting_department_code="CUT", planned_quantity=1)


@pytest.mark.parametrize("evidence", [
    "cutting_record", "passport", "bundle", "printing_record", "sewing_record", "quality", "assignment",
    "actual_input", "actual_output", "failed", "passed", "rework", "cutting_end", "cutting_cancelled",
    "cutting_blocked", "cutting_operator", "downstream_started", "downstream_completed",
    "closed", "usluga", "mixed_routing", "finished_stock",
])
def test_recorded_evidence_refuses_and_preserves_routes(client, evidence):
    with TestSessionLocal() as db:
        oid, uid, works = make_order(db)
        cutting = db.get(WorkOrder, works["cutting"])
        if evidence == "cutting_record": db.add(CuttingRecord(work_order_id=cutting.id, cut_pieces=0, input_quantity=0))
        elif evidence == "passport": db.add(CuttingPassport(production_order_id=oid, passport_no=uuid4().hex, date=datetime.now(timezone.utc)))
        elif evidence == "bundle": db.add(Bundle(production_order_id=oid, model_id=db.get(ProductionOrder, oid).model_id, bundle_no=uuid4().hex, barcode=uuid4().hex, color="white", size="S", quantity=1))
        elif evidence == "printing_record": db.add(PrintingRecord(work_order_id=works["printing"], input_qty=0, printed_qty=0, passed_qty=0))
        elif evidence == "sewing_record": db.add(SewingRecord(work_order_id=works["sewing"], input_qty=0, sewn_qty=0, passed_qty=0))
        elif evidence == "quality": db.add(QualityCheck(work_order_id=cutting.id, checked_qty=0, checked_by=uid))
        elif evidence == "assignment":
            flow = SewingFlow(name=f"QA {uuid4().hex}", code=uuid4().hex[:20], factory_code="MIL")
            db.add(flow); db.flush()
            db.add(SewingAssignment(work_order_id=works["sewing"], sewing_flow_id=flow.id, quantity=1, status="in_progress"))
        elif evidence in {"actual_input", "actual_output", "failed", "passed", "rework"}: setattr(cutting, {"actual_input": "actual_input_qty", "actual_output": "actual_output_qty", "failed": "failed_qty", "passed": "passed_qty", "rework": "rework_qty"}[evidence], 1)
        elif evidence == "cutting_end": cutting.end_time = datetime.now(timezone.utc)
        elif evidence == "cutting_cancelled": cutting.status = "cancelled"
        elif evidence == "cutting_blocked": cutting.is_blocked = True
        elif evidence == "cutting_operator": cutting.assigned_to = uid
        elif evidence == "downstream_started": db.get(WorkOrder, works["printing"]).start_time = datetime.now(timezone.utc)
        elif evidence == "downstream_completed": db.get(WorkOrder, works["packaging"]).status = "completed"
        elif evidence == "closed": db.get(ProductionOrder, oid).status = "completed"
        elif evidence == "usluga": db.get(ProductionOrder, oid).source_type = "usluga"
        elif evidence == "mixed_routing": db.add(WorkOrder(production_order_id=oid, operation="cutting", department_id=db.query(Department.id).filter_by(code="ECT").scalar(), status="waiting"))
        elif evidence == "finished_stock": db.add(FinishedGoodsStock(production_order_id=oid, color="white", size="S", quantity=1, available_qty=1))
        db.commit(); before = route_snapshot(db, oid)
    url = f"/api/production-orders/{oid}/cutting-factory"
    response = client.patch(url, headers=headers(uid), json={"cutting_department_code": "ECT"})
    assert response.status_code == 409, response.text
    options = client.get(url, headers=headers(uid))
    assert options.status_code == 409 if evidence == "mixed_routing" else options.json()["can_change"] is False
    with TestSessionLocal() as db:
        assert route_snapshot(db, oid) == before
        assert db.query(AuditLog).filter_by(entity_id=oid, action="change_cutting_factory").count() == 0


def test_readonly_options_and_noop_do_not_write_even_with_evidence(client):
    with TestSessionLocal() as db:
        oid, uid, works = make_order(db)
        db.add(CuttingRecord(work_order_id=works["cutting"], cut_pieces=1, passed_pieces=1)); db.commit()
        before = route_snapshot(db, oid)
    url = f"/api/production-orders/{oid}/cutting-factory"
    assert client.get(url, headers=headers(uid)).json()["can_change"] is False
    response = client.patch(url, headers=headers(uid), json={"cutting_department_code": "CUT"})
    assert response.status_code == 200 and response.json()["changed"] is False
    with TestSessionLocal() as db:
        assert route_snapshot(db, oid) == before
        assert db.query(AuditLog).filter_by(entity_id=oid, action="change_cutting_factory").count() == 0


def test_fault_after_schema_flush_rolls_back_routing_and_audit(monkeypatch):
    with TestSessionLocal() as db:
        oid, uid, works = make_order(db)
        before = route_snapshot(db, oid)
    def fail(*args, **kwargs):
        raise RuntimeError("injected audit failure")
    monkeypatch.setattr(service, "log_action", fail)
    with TestSessionLocal() as db:
        with pytest.raises(RuntimeError, match="injected audit failure"):
            service.change_cutting_factory(db, oid, ProductionCuttingFactoryIn(cutting_department_code="ECT"), db.get(User, uid))
    with TestSessionLocal() as db:
        assert route_snapshot(db, oid) == before
        assert db.query(AuditLog).filter_by(entity_id=oid, action="change_cutting_factory").count() == 0


def test_reverse_direction_preserves_planned_sewing_assignment_and_work_dates(client):
    with TestSessionLocal() as db:
        oid, uid, works = make_order(db, source="ECT")
        flow = SewingFlow(name=f"QA {uuid4().hex}", code=uuid4().hex[:20], factory_code="MIL")
        db.add(flow); db.flush()
        assignment = SewingAssignment(work_order_id=works["sewing"], sewing_flow_id=flow.id, quantity=120,
                                      status="planned", planned_start=datetime(2026, 11, 5, tzinfo=timezone.utc))
        db.add(assignment); db.commit()
        db.expire_all()
        assignment_id = assignment.id
        before = {column.name: getattr(assignment, column.name) for column in SewingAssignment.__table__.columns}
    response = client.patch(f"/api/production-orders/{oid}/cutting-factory", headers=headers(uid), json={"cutting_department_code": "CUT"})
    assert response.status_code == 200, response.text
    with TestSessionLocal() as db:
        assignment = db.get(SewingAssignment, assignment_id)
        assert before == {column.name: getattr(assignment, column.name) for column in SewingAssignment.__table__.columns}


@pytest.mark.parametrize("consumed", [0, 1])
def test_unconsumed_reservations_are_preserved_and_consumed_material_refuses(client, consumed):
    with TestSessionLocal() as db:
        oid, uid, works = make_order(db)
        item = Item(sku=f"QA-{uuid4().hex[:16]}", name="QA fabric", category="fabric", unit="kg")
        db.add(item); db.flush()
        reservation = MaterialReservation(reservation_no=f"QA-{uuid4().hex[:16]}", production_order_id=oid,
            item_id=item.id, reserved_quantity=10, consumed_quantity=consumed, unit="kg",
            source="planning", reservation_type="material", status="partially_consumed" if consumed else "reserved")
        db.add(reservation); db.commit(); db.expire_all()
        reservation_id = reservation.id
        before = {column.name: getattr(reservation, column.name) for column in MaterialReservation.__table__.columns}
    response = client.patch(f"/api/production-orders/{oid}/cutting-factory", headers=headers(uid), json={"cutting_department_code": "ECT"})
    assert response.status_code == (409 if consumed else 200), response.text
    with TestSessionLocal() as db:
        reservation = db.get(MaterialReservation, reservation_id)
        assert before == {column.name: getattr(reservation, column.name) for column in MaterialReservation.__table__.columns}


def test_missing_order_refuses_and_unauthenticated_request_is_denied(client, auth_headers):
    assert client.get("/api/production-orders/999999999/cutting-factory", headers=auth_headers).status_code == 404
    assert client.patch("/api/production-orders/1/cutting-factory", json={"cutting_department_code": "ECT"}).status_code in {401, 403}
