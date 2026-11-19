"""Bounded synthetic PostgreSQL enrollment/simulator checks; retain evidence.

Run only in the dedicated backend test runtime with a dedicated database named
turnstile_verify_*. The caller supplies DATABASE_URL and explicitly opts in with
TURNSTILE_VERIFY_SYNTHETIC=1. Never run against an existing/shared database.
"""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.libs.dto.people.turnstile_input import GateEnrollmentInput
from app.libs.enums.turnstile import GateMode, GateTargetState
from app.models.people import turnstile_access_service as access
from app.models.people.turnstile_simulator_service import SimulatorAdapter, reconnect_simulator_operation, run_simulator_operation
from app.schemas import Employee, IdempotencyRecord, Role, User
from app.schemas.people.attendance import AttendanceDevice
from app.schemas.people.turnstile import GateEmployeeDevice, GateOperation, GatePhotoAsset, GateSimulatorDevice, GateSimulatorPerson, GateTarget


def check(value, label):
    if not value:
        raise AssertionError(label)


def main():
    url = make_url(os.environ["DATABASE_URL"])
    check(os.environ.get("TURNSTILE_VERIFY_SYNTHETIC") == "1", "explicit synthetic opt-in")
    check(url.get_backend_name() == "postgresql" and (url.database or "").startswith("turnstile_verify_"), "dedicated database required")
    check(not settings.strict_security_required, "private development environment required")
    settings.TURNSTILE_PROVISIONING_MODE = GateMode.SIMULATOR
    engine = create_engine(url, connect_args={"connect_timeout": 5}, pool_size=8, max_overflow=0)
    @event.listens_for(engine, "connect")
    def limits(conn, record):
        with conn.cursor() as cursor:
            cursor.execute("SET statement_timeout = '15s'; SET lock_timeout = '5s'")
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    prefix = "tv" + uuid4().hex[:14]
    checks = {}
    with factory() as db:
        role = Role(name=prefix, permissions=["*"])
        actor = User(name=prefix, email=prefix + "@invalid.example", password_hash="synthetic", role=role, factory_code="MIL", extra_permissions=[], is_active=True)
        employees = [Employee(factory_code="MIL", employee_no=prefix + str(i), full_name="Synthetic", status="active", hr_profile_json={}) for i in range(4)]
        db.add_all([actor, *employees]); db.flush()
        devices = [AttendanceDevice(factory_code="MIL", device_key=prefix + str(i), name="Synthetic", sync_enabled=True, read_only=True) for i in range(4)]
        db.add_all(devices); db.flush()
        db.add_all([GateSimulatorDevice(device_id=d.id, factory_code="MIL", online=(i != 3), mode=GateMode.SIMULATOR) for i, d in enumerate(devices)])
        photos = [GatePhotoAsset(employee_id=e.id, factory_code="MIL", created_by=actor.id, stored_name=uuid4().hex + ".jpg", sha256="a" * 64, width=1, height=1, content_type="image/jpeg") for e in employees]
        db.add_all(photos); db.flush()
        actor_id, employee_ids, device_ids, photo_ids = actor.id, [e.id for e in employees], [d.id for d in devices], [p.id for p in photos]
        db.commit()

    def enroll(employee_index, key):
        with factory() as db:
            actor = db.get(User, actor_id)
            payload = GateEnrollmentInput(expected_employee_no=prefix + str(employee_index), device_ids=device_ids, photo_asset_id=photo_ids[employee_index], manual_face_reviewed=True)
            try:
                result = access.enroll_gate_employee(db, actor, employee_ids[employee_index], payload, key)
                return ("ok", result.id)
            except HTTPException as exc:
                return ("http", exc.status_code)

    with ThreadPoolExecutor(max_workers=4) as executor:
        same = list(executor.map(lambda _: enroll(0, prefix + "same"), range(4)))
    check(len({r[1] for r in same}) == 1 and all(r[0] == "ok" for r in same), "same key replay")
    operation_id = same[0][1]
    with factory() as db:
        check(db.scalar(select(func.count()).select_from(GateOperation).where(GateOperation.employee_id == employee_ids[0])) == 1, "one operation")
        check(db.scalar(select(func.count()).select_from(GateTarget).where(GateTarget.operation_id == operation_id)) == 4, "four targets")
    checks["same_key"] = {"requests": 4, "operations": 1, "targets": 4}

    with ThreadPoolExecutor(max_workers=4) as executor:
        distinct = list(executor.map(lambda i: enroll(1, prefix + str(i)), range(4)))
    check(sum(r[0] == "ok" for r in distinct) == 1 and sum(r == ("http", 409) for r in distinct) == 3, "distinct key conflict")
    with factory() as db:
        check(db.scalar(select(func.count()).select_from(GateOperation).where(GateOperation.employee_id == employee_ids[1])) == 1, "conflict orphan operations")
        check(db.scalar(select(func.count()).select_from(GateEmployeeDevice).where(GateEmployeeDevice.employee_id == employee_ids[1])) == 4, "conflict orphan bindings")
    checks["distinct_keys"] = {"accepted": 1, "conflicts": 3}

    # Exercise actual PostgreSQL constraints with rolled-back, scoped mutations.
    with factory() as db:
        target_id = db.scalar(select(GateTarget.id).where(GateTarget.operation_id == operation_id).limit(1))
        def reject(sql, params):
            try:
                with db.begin_nested():
                    db.execute(text(sql), params)
                raise AssertionError("database accepted invalid scope or enum")
            except IntegrityError:
                pass
        reject("UPDATE gate_photo_assets SET factory_code = 'BST' WHERE id = :id", {"id": photo_ids[0]})
        reject("UPDATE gate_targets SET employee_id = :other WHERE id = :id", {"other": employee_ids[1], "id": target_id})
        reject("UPDATE gate_targets SET state = 'invented' WHERE id = :id", {"id": target_id})
        db.rollback()
    checks["database_constraints"] = {"cross_factory_photo": True, "cross_scope_target": True, "invalid_enum": True}

    with factory() as db:
        actor = db.get(User, actor_id)
        original = access.log_action
        def fail_audit(*args, **kwargs):
            raise RuntimeError("synthetic audit failure")
        access.log_action = fail_audit
        try:
            try:
                access.enroll_gate_employee(db, actor, employee_ids[2], GateEnrollmentInput(expected_employee_no=prefix + "2", device_ids=device_ids, photo_asset_id=photo_ids[2], manual_face_reviewed=True), prefix + "audit")
                raise AssertionError("audit failure not raised")
            except RuntimeError:
                pass
        finally:
            access.log_action = original
        check(db.scalar(select(func.count()).select_from(GateOperation).where(GateOperation.employee_id == employee_ids[2])) == 0, "audit operation rollback")
        check(db.scalar(select(func.count()).select_from(GateEmployeeDevice).where(GateEmployeeDevice.employee_id == employee_ids[2])) == 0, "audit binding rollback")
        check(db.scalar(select(func.count()).select_from(GateTarget).where(GateTarget.employee_id == employee_ids[2])) == 0, "audit target rollback")
        check(db.scalar(select(func.count()).select_from(IdempotencyRecord).where(IdempotencyRecord.key == prefix + "audit")) == 0, "audit idempotency rollback")
    checks["audit_rollback"] = True

    with factory() as db:
        actor = db.get(User, actor_id)
        list(actor.role.permissions)
        _ = actor.department
        db.expunge(actor)
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(lambda _: run_simulator_operation(factory, actor, operation_id), range(4)))
    with factory() as db:
        targets = db.scalars(select(GateTarget).where(GateTarget.operation_id == operation_id)).all()
        check(sum(t.state == GateTargetState.SUCCEEDED for t in targets) == 3 and sum(t.state == GateTargetState.WAITING for t in targets) == 1, "offline readback")
        people = db.scalars(select(GateSimulatorPerson).where(GateSimulatorPerson.binding_id.in_([t.binding_id for t in targets]))).all()
        check(len(people) == 3 and all(p.write_count == 1 for p in people), "one simulator write")
    reconnect_simulator_operation(factory, actor, operation_id)
    with factory() as db:
        targets = db.scalars(select(GateTarget).where(GateTarget.operation_id == operation_id)).all()
        people = db.scalars(select(GateSimulatorPerson).where(GateSimulatorPerson.binding_id.in_([t.binding_id for t in targets]))).all()
        check(all(t.state == GateTargetState.SUCCEEDED for t in targets) and len(people) == 4 and all(p.write_count == 1 for p in people), "reconnect readback")
    checks["simulator"] = {"online": 3, "offline": 1, "after_reconnect": 4, "max_writes": 1}

    # A separate operation models acceptance followed by a lost reply.
    lost = enroll(3, prefix + "lost")
    check(lost[0] == "ok", "lost reply enrollment")
    class LostReply(SimulatorAdapter):
        def accept(self, target_id, token):
            super().accept(target_id, token)
            raise RuntimeError("synthetic lost reply")
    run_simulator_operation(factory, actor, lost[1], adapter=LostReply(factory))
    run_simulator_operation(factory, actor, lost[1])
    with factory() as db:
        targets = db.scalars(select(GateTarget).where(GateTarget.operation_id == lost[1])).all()
        people = db.scalars(select(GateSimulatorPerson).where(GateSimulatorPerson.binding_id.in_([t.binding_id for t in targets]))).all()
        check(all(t.state == GateTargetState.SUCCEEDED for t in targets) and len(people) == 4 and all(p.write_count == 1 for p in people), "lost reply reconciliation")
    checks["lost_reply"] = {"targets": 4, "max_writes": 1}
    print(json.dumps({"status": "pass", "checks": checks}, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"status": "fail", "failure": type(exc).__name__, "check": str(exc) if isinstance(exc, AssertionError) else "execution failed"}))
        raise SystemExit(1)
