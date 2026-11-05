"""Synthetic rejection cases: refuse history, preserve plans, notify once, no bypass."""
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.models.production import cutting_rejection_service as service
from app.schemas import (
    AuditLog, Bundle, CuttingPassport, CuttingRecord, Item, MaterialReservation,
    Notification, ProductionBatch, ProductionOrder, SewingRecord, User, WorkOrder,
)
from app.tests.conftest import TestSessionLocal
from app.tests.test_planning_cutting_factory import headers, make_order, route_snapshot


def reject(client, wid, uid, payload=None):
    return client.post(f"/api/work-orders/{wid}/reject-cutting", headers=headers(uid),
                       json=payload if payload is not None else {"reason": "Fabric needs review"})


def test_reject_preserves_plans_and_persists_reason_audit_notification_once(client):
    with TestSessionLocal() as db:
        oid, uid, works = make_order(db)
        planner = db.query(User).filter_by(email="planning@example.com").one()
        planner_id = planner.id
        db.get(ProductionOrder, oid).created_by = planner_id
        db.commit()
        before = route_snapshot(db, oid)
        batches = [(row.id, row.planned_quantity) for row in db.query(ProductionBatch).filter_by(production_order_id=oid)]
    for _ in range(2):
        response = reject(client, works["cutting"], uid, {"reason": "  Fabric needs review  "})
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "rejected"
        assert response.json()["is_blocked"] is True
        assert response.json()["block_reason"] == "Fabric needs review"
        assert response.json()["end_time"] is not None
    assert reject(client, works["cutting"], uid, {"reason": "Different reason"}).status_code == 409
    with TestSessionLocal() as db:
        after = route_snapshot(db, oid)
        for old, new in zip(before, after):
            if old["id"] != works["cutting"]:
                assert old == new
            else:
                assert {key for key in old if old[key] != new[key]} == {"status", "is_blocked", "block_reason", "end_time", "updated_at"}
        assert db.get(ProductionOrder, oid).status == "cutting"
        assert batches == [(row.id, row.planned_quantity) for row in db.query(ProductionBatch).filter_by(production_order_id=oid)]
        audit = db.query(AuditLog).filter_by(entity_id=works["cutting"], action="reject_cutting").one()
        assert audit.new_value_json["reason"] == "Fabric needs review"
        notification = db.query(Notification).filter_by(user_id=planner_id, link=f"/production-orders/{oid}").one()
        assert notification.message == "Fabric needs review"


@pytest.mark.parametrize("payload", [{}, {"reason": ""}, {"reason": " \n "}, {"reason": None},
                                      {"reason": 12}, {"reason": "x" * 2001}, {"reason": "valid", "status": "completed"}])
def test_reason_validation_is_atomic(client, payload):
    with TestSessionLocal() as db:
        oid, uid, works = make_order(db)
        before = route_snapshot(db, oid)
    response = reject(client, works["cutting"], uid, payload)
    assert response.status_code == 422, response.text
    with TestSessionLocal() as db:
        assert route_snapshot(db, oid) == before
        assert db.query(AuditLog).filter_by(entity_id=works["cutting"], action="reject_cutting").count() == 0


@pytest.mark.parametrize("case,expected", [("no_permission", 403), ("wrong_factory", 403),
                                         ("wrong_stage", 400), ("missing", 404), ("legacy_usluga", 403)])
def test_rejection_enforces_stage_permission_and_factory(client, case, expected):
    with TestSessionLocal() as db:
        oid, uid, works = make_order(db, permissions=["printing.records"] if case == "no_permission" else None,
                                     source="ECT" if case == "wrong_factory" else "CUT")
        if case == "legacy_usluga":
            db.get(ProductionOrder, oid).source_type = "usluga"
            db.commit()
        before = route_snapshot(db, oid)
    wid = works["printing"] if case == "wrong_stage" else 999999999 if case == "missing" else works["cutting"]
    assert reject(client, wid, uid).status_code == expected
    with TestSessionLocal() as db:
        assert route_snapshot(db, oid) == before


@pytest.mark.parametrize("evidence", ["cutting", "passport", "bundle", "sewing", "downstream_start",
                                      "actual_output", "cancelled", "completed", "closed_order", "consumed", "passport_actual"])
def test_reject_refuses_recorded_history_without_changing_it(client, evidence):
    with TestSessionLocal() as db:
        oid, uid, works = make_order(db)
        work = db.get(WorkOrder, works["cutting"])
        if evidence == "cutting":
            db.add(CuttingRecord(work_order_id=work.id, cut_pieces=0, input_quantity=0))
        elif evidence == "passport":
            db.add(CuttingPassport(production_order_id=oid, passport_no=uuid4().hex, date=datetime.now(timezone.utc)))
        elif evidence == "bundle":
            db.add(Bundle(production_order_id=oid, model_id=db.get(ProductionOrder, oid).model_id,
                          bundle_no=uuid4().hex, barcode=uuid4().hex, color="white", size="S", quantity=1))
        elif evidence == "sewing":
            db.add(SewingRecord(work_order_id=works["sewing"], input_qty=1, sewn_qty=1, passed_qty=1))
        elif evidence == "downstream_start": db.get(WorkOrder, works["printing"]).start_time = datetime.now(timezone.utc)
        elif evidence == "actual_output": work.actual_output_qty = 1
        elif evidence in {"cancelled", "completed"}: work.status = evidence
        elif evidence == "closed_order": db.get(ProductionOrder, oid).status = "finished_storage"
        elif evidence == "passport_actual": db.query(ProductionBatch).filter_by(production_order_id=oid).one().passport_actual_quantity = 1
        elif evidence == "consumed":
            item = Item(sku=uuid4().hex, name="QA rejection fabric", category="fabric", unit="kg")
            db.add(item); db.flush()
            db.add(MaterialReservation(reservation_no=uuid4().hex, production_order_id=oid, item_id=item.id,
                                      reserved_quantity=10, consumed_quantity=1, unit="kg", source="planning",
                                      reservation_type="material", status="partially_consumed"))
        db.commit()
        before = route_snapshot(db, oid)
    response = reject(client, work.id, uid)
    assert response.status_code == 409, response.text
    with TestSessionLocal() as db:
        assert route_snapshot(db, oid) == before
        assert db.query(AuditLog).filter_by(entity_id=work.id, action="reject_cutting").count() == 0


@pytest.mark.parametrize("command", ["start", "complete", "unblock", "update", "extra-batch", "split-batches",
                                     "cutting", "passport", "bundle", "batch-update", "quality", "block"])
def test_rejected_cutting_cannot_resume_through_existing_mutations(client, command):
    with TestSessionLocal() as db:
        oid, uid, works = make_order(db, permissions=["planning.production", "cutting.records", "cutting.bundles"])
        model_id = db.get(ProductionOrder, oid).model_id
        batch_id = db.query(ProductionBatch.id).filter_by(production_order_id=oid).scalar()
    wid = works["cutting"]
    assert reject(client, wid, uid).status_code == 200
    auth = headers(uid)
    if command == "update": response = client.patch(f"/api/work-orders/{wid}", headers=auth, json={"actual_output_qty": 1})
    elif command == "extra-batch": response = client.post(f"/api/work-orders/{wid}/extra-batch", headers=auth, json={"planned_quantity": 10})
    elif command == "split-batches": response = client.post(f"/api/work-orders/{wid}/split-batches", headers=auth, json={"batches": [{"planned_quantity": 120}]})
    elif command == "cutting": response = client.post("/api/cutting/records", headers=auth, json={"work_order_id": wid, "cut_pieces": 1, "passed_pieces": 1, "input_quantity": 0})
    elif command == "passport": response = client.post("/api/cutting-passports", headers=auth, json={"production_order_id": oid, "date": "2026-11-05T00:00:00Z", "pieces": 120})
    elif command == "bundle": response = client.post("/api/bundles", headers=auth, json={"production_order_id": oid, "model_id": model_id, "color": "white", "size": "S", "quantity": 1})
    elif command == "batch-update": response = client.patch(f"/api/work-orders/{wid}/batches/{batch_id}", headers=auth, json={"name": "changed"})
    elif command == "quality": response = client.post("/api/quality/checks", headers=auth, json={"work_order_id": wid, "checked_qty": 1, "passed_qty": 1, "failed_qty": 0})
    elif command == "block": response = client.post(f"/api/work-orders/{wid}/block", headers=auth, json={"reason": "overwrite"})
    else: response = client.post(f"/api/work-orders/{wid}/{command}", headers=auth)
    assert response.status_code == 409, response.text
    with TestSessionLocal() as db:
        work = db.get(WorkOrder, wid)
        assert (work.status, work.is_blocked, work.block_reason, work.actual_output_qty) == ("rejected", True, "Fabric needs review", 0)
        assert db.query(CuttingRecord).filter_by(work_order_id=wid).count() == 0
        assert db.query(Bundle).filter_by(production_order_id=oid).count() == 0
        assert db.query(CuttingPassport).filter_by(production_order_id=oid).count() == 0


def test_audit_failure_rolls_back_rejection(client, monkeypatch):
    with TestSessionLocal() as db:
        oid, uid, works = make_order(db)
        before = route_snapshot(db, oid)
    def fail(*args, **kwargs): raise RuntimeError("injected audit failure")
    monkeypatch.setattr(service, "log_action", fail)
    with pytest.raises(RuntimeError, match="injected audit failure"):
        reject(client, works["cutting"], uid)
    with TestSessionLocal() as db:
        assert route_snapshot(db, oid) == before
        assert db.query(AuditLog).filter_by(entity_id=works["cutting"], action="reject_cutting").count() == 0


def test_rejection_requires_authentication(client):
    response = client.post("/api/work-orders/1/reject-cutting", json={"reason": "No fabric"})
    assert response.status_code in {401, 403}
