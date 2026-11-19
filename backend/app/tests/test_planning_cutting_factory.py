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
    AuditLog, Bundle, CuttingPassport, CuttingRecord, Department, Employee, FinishedGoodsStock,
    Item, LegacyStockReceipt, MaterialReservation, Model, Package, PackageBatchAllocation, PayrollQrLabel, PayrollRecord,
    PrintingRecord, ProductionBatch, ProductionOrder, QualityCheck, Role,
    SewingAssignment, SewingDailyReport, SewingFlow, SewingRecord, User, WasteRecord, WorkOrder,
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
    "closed", "usluga", "mixed_routing", "finished_stock", "work_order_waste",
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
        elif evidence == "work_order_waste": db.add(WasteRecord(work_order_id=cutting.id, waste_type="cutting", quantity=1, unit="kg"))
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


@pytest.mark.parametrize("kind,link", [
    ("payroll_record", "work"), ("payroll_record", "batch"),
    ("payroll_label", "work"), ("payroll_label", "batch"),
    ("daily_report", "work"), ("daily_report", "batch"), ("daily_report", "assignment"),
    ("package", "batch"), ("package_allocation", "batch"), ("passport_actual", "batch"),
])
def test_recorded_ledgers_with_optional_order_reference_still_freeze_routing(client, kind, link):
    with TestSessionLocal() as db:
        oid, uid, works = make_order(db)
        batch = db.query(ProductionBatch).filter_by(production_order_id=oid).one()
        refs = {"work_order_id": works["sewing"]} if link == "work" else {"production_batch_id": batch.id}
        if kind == "payroll_record":
            worker = Employee(full_name="QA payroll witness", factory_code="MIL")
            db.add(worker); db.flush()
            evidence = PayrollRecord(**refs, production_order_id=None, employee_id=worker.id, dedupe_key=uuid4().hex,
                                     scanned_at=datetime.now(timezone.utc), quantity=1, rate_per_piece=1, total_amount=1)
        elif kind == "payroll_label":
            evidence = PayrollQrLabel(**refs, production_order_id=None, label_uid=uuid4().hex, quantity=1)
        elif kind == "daily_report":
            marker = uuid4().hex[:16]
            flow = SewingFlow(code=marker, name=f"QA {marker}", factory_code="MIL")
            db.add(flow); db.flush()
            if link == "assignment":
                assignment = SewingAssignment(work_order_id=works["sewing"], sewing_flow_id=flow.id, quantity=120, status="planned")
                db.add(assignment); db.flush()
                refs = {"sewing_assignment_id": assignment.id}
            evidence = SewingDailyReport(**refs, production_order_id=None, report_date=datetime(2026, 11, 4).date(),
                                         sewing_flow_id=flow.id, line_code=marker, line_name=flow.name, sewn_qty=1)
        elif kind in {"package", "package_allocation"}:
            marker = uuid4().hex
            receipt = LegacyStockReceipt(source_system="QA", source_warehouse_id="QA", source_record_id=marker,
                                         source_checksum=marker, source_payload={})
            db.add(receipt); db.flush()
            package = Package(production_order_id=None, legacy_receipt_id=receipt.id,
                production_batch_id=batch.id if kind == "package" else None, package_no=marker, barcode=marker,
                color="white", total_quantity=1, capacity=60)
            db.add(package); db.flush()
            evidence = package if kind == "package" else PackageBatchAllocation(package_id=package.id, production_batch_id=batch.id, quantity=1)
        else:
            batch.passport_actual_quantity = 12
            evidence = batch
        db.add(evidence); db.commit(); db.expire_all()
        before = {column.name: getattr(evidence, column.name) for column in evidence.__table__.columns}
        evidence_id, evidence_type = evidence.id, type(evidence)
        routes_before = route_snapshot(db, oid)
    url = f"/api/production-orders/{oid}/cutting-factory"
    options = client.get(url, headers=headers(uid))
    assert options.status_code == 200 and options.json()["can_change"] is False, options.text
    refused = client.patch(url, headers=headers(uid), json={"cutting_department_code": "ECT"})
    assert refused.status_code == 409 and refused.json()["detail"] == "CUTTING_FACTORY_HISTORY_LOCKED", refused.text
    with TestSessionLocal() as db:
        evidence = db.get(evidence_type, evidence_id)
        assert before == {column.name: getattr(evidence, column.name) for column in evidence.__table__.columns}
        assert route_snapshot(db, oid) == routes_before
        assert db.query(AuditLog).filter_by(entity_id=oid, action="change_cutting_factory").count() == 0


def test_moved_to_ect_matches_created_at_ect_cutting_and_sewing_handoff(client, auth_headers):
    """Exercise real public creation, ECT Cutting and intended MIL receipt."""
    with TestSessionLocal() as db:
        marker = uuid4().hex[:12]
        model = Model(code=f"QA-HANDOFF-{marker}", name="No-material handoff fixture", status="approved")
        cutting_role = Role(name=f"QA ECT cutting {marker}", permissions=["cutting.records", "cutting.bundles"])
        sewing_role = Role(name=f"QA MIL sewing {marker}", permissions=["sewing.bundles", "sewing.flows"])
        eco_actor = User(name="QA ECT operator", email=f"ect-{marker}@example.invalid", password_hash="unused", factory_code="ECO", role=cutting_role)
        sewing_actor = User(name="QA MIL receiver", email=f"sew-{marker}@example.invalid", password_hash="unused", factory_code="MIL", role=sewing_role)
        db.add_all([model, eco_actor, sewing_actor]); db.commit()
        model_id, eco_id, sewing_id = model.id, eco_actor.id, sewing_actor.id
    eco_headers = {"Authorization": f"Bearer {create_access_token(eco_id, extra={'factory_code': 'ECO'})}"}
    sewing_headers = headers(sewing_id)
    outcomes = []
    for initial_cutting in ("CUT", "ECT"):
        created = client.post("/api/planning/create-branded-production", headers=auth_headers, json={
            "production_type": "branded_stock", "model_id": model_id, "planned_quantity": 12,
            "cutting_department_code": initial_cutting, "sewing_factory_code": "MIL",
            "items": [{"model_id": model_id, "color": "white", "size": "S", "planned_quantity": 12}],
        })
        assert created.status_code == 201, created.text
        oid = created.json()["id"]
        with TestSessionLocal() as db:
            works = {work.operation: work.id for work in db.query(WorkOrder).filter_by(production_order_id=oid)}
            planned = {operation: (db.get(WorkOrder, works[operation]).department_id, db.get(WorkOrder, works[operation]).planned_output_qty)
                       for operation in ("sewing", "packaging")}
        if initial_cutting == "CUT":
            moved = client.patch(f"/api/production-orders/{oid}/cutting-factory", headers=auth_headers, json={"cutting_department_code": "ECT"})
            assert moved.status_code == 200 and moved.json()["changed"] is True, moved.text
        ect_floor = client.get("/api/inbox?dept=ECT", headers=eco_headers)
        assert ect_floor.status_code == 200, ect_floor.text
        assert any(row["production_order_id"] == oid for key in ("pending_work_orders", "in_progress_work_orders", "active_work_orders") for row in ect_floor.json()[key])
        cut_floor = client.get("/api/inbox?dept=CUT", headers=auth_headers)
        assert cut_floor.status_code == 200, cut_floor.text
        assert not any(row["production_order_id"] == oid for key in ("pending_work_orders", "in_progress_work_orders", "active_work_orders") for row in cut_floor.json()[key])
        payload = {"work_order_id": works["cutting"], "input_quantity": 0, "cut_pieces": 12, "passed_pieces": 12,
                   "bundles": [{"color": "white", "size": "S", "quantity": 12, "count": 1, "next": "sewing", "sewing_factory": "milana"}]}
        assert client.post("/api/cutting/records", headers=auth_headers, json=payload).status_code == 403
        cut = client.post("/api/cutting/records", headers=eco_headers, json=payload)
        assert cut.status_code == 201, cut.text
        bundle = cut.json()["bundles"][0]
        assert bundle["sewing_factory_code"] == "MIL"
        incoming = client.get("/api/inbox?dept=MIL", headers=sewing_headers)
        assert incoming.status_code == 200, incoming.text
        assert any(row["id"] == bundle["id"] for row in incoming.json()["incoming_bundles"])
        # ECT Cutting is not permission to receive the preserved MIL destination.
        assert client.post(f"/api/bundles/{bundle['id']}/receive-sewing", headers=eco_headers).status_code == 403
        received = client.post(f"/api/bundles/{bundle['id']}/receive-sewing", headers=sewing_headers)
        assert received.status_code == 200, received.text
        assert received.json()["status"] == "received_sewing"
        active = client.get("/api/inbox?dept=MIL", headers=sewing_headers)
        assert active.status_code == 200, active.text
        assert any(row["production_order_id"] == oid for key in ("pending_work_orders", "in_progress_work_orders", "active_work_orders") for row in active.json()[key])
        with TestSessionLocal() as db:
            cutting = db.get(WorkOrder, works["cutting"])
            sewing = db.get(WorkOrder, works["sewing"])
            live_bundle = db.get(Bundle, bundle["id"])
            assert db.query(Department.code).filter_by(id=cutting.department_id).scalar() == "ECT"
            assert planned == {operation: (db.get(WorkOrder, works[operation]).department_id, db.get(WorkOrder, works[operation]).planned_output_qty)
                               for operation in ("sewing", "packaging")}
            assert db.query(CuttingRecord).filter_by(work_order_id=cutting.id).one().passed_pieces == 12
            outcomes.append((cutting.passed_qty, sewing.actual_input_qty, live_bundle.status,
                             live_bundle.sewing_factory_code, live_bundle.quantity,
                             db.query(Department.code).filter_by(id=live_bundle.current_department_id).scalar()))
    assert outcomes == [(12, 12, "received_sewing", "MIL", 12, "MIL")] * 2
