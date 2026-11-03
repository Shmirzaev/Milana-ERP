"""Bounded synthetic EDIT checks on an explicitly approved PostgreSQL instance.

Failure retains the owned target and live resources for inspection; never rerun blindly.
"""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Thread
from time import monotonic, sleep
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db.base import Base
from app.libs.dto.people.turnstile_input import GateEditInput, GateEnrollmentInput
from app.libs.enums.turnstile import GateAction, GateErrorCode, GateMode, GateTargetState
from app.models.people import turnstile_access_service as access, turnstile_simulator_service as sim
from app.schemas import Employee, IdempotencyRecord, Role, User
from app.schemas.core import AuditLog
from app.schemas.people.attendance import AttendanceDevice
from app.schemas.people.turnstile import GateOperation, GatePhotoAsset, GateSimulatorDevice, GateSimulatorPerson, GateTarget
from app.schemas.people import turnstile_persistence as persistence
from app.tests.pg_approved_instance import (load_approved_instance, verify_approved_instance,
    create_target_database, owned_target_name, target_engine, finalize_target, retain_fixture_uncertainty)


def check(condition, label):
    if not condition:
        raise AssertionError(label)


def main():
    check(os.environ.get("TURNSTILE_VERIFY_SYNTHETIC") == "1", "synthetic opt-in required")
    check(not settings.strict_security_required, "private development environment required")
    instance = load_approved_instance()
    verify_approved_instance(instance)
    target = create_target_database(instance)
    engine = None
    factory = None
    checks = {}
    name = owned_target_name(target)
    print(json.dumps({"status": "running", "target": name}), flush=True)
    try:
        engine = target_engine(target, options="-c statement_timeout=15000 -c lock_timeout=5000")
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        settings.TURNSTILE_PROVISIONING_MODE = GateMode.SIMULATOR
        prefix = "edit" + uuid4().hex[:12]
        with factory() as db:
            role = Role(name=prefix, permissions=["*"])
            actor = User(name=prefix, email=prefix + "@invalid.example", password_hash="synthetic", role=role, factory_code="MIL", extra_permissions=[], is_active=True)
            actor2 = User(name=prefix + "b", email=prefix + "b@invalid.example", password_hash="synthetic", role=role, factory_code="MIL", extra_permissions=[], is_active=True)
            employees = [Employee(factory_code="MIL", employee_no=prefix + str(i), full_name="Synthetic", status="active", hr_profile_json={}) for i in range(6)]
            devices = [AttendanceDevice(factory_code="MIL", device_key=prefix + str(i), name="Synthetic", sync_enabled=True, read_only=True) for i in range(4)]
            db.add_all([actor, actor2, *employees, *devices]); db.flush()
            db.add_all([GateSimulatorDevice(device_id=d.id, factory_code="MIL", online=True, mode=GateMode.SIMULATOR) for d in devices])
            photos = [GatePhotoAsset(employee_id=e.id, factory_code="MIL", created_by=actor.id, stored_name=uuid4().hex, sha256=ch * 64, width=1, height=1, content_type="image/jpeg") for e in employees for ch in ("a", "b")]
            db.add_all(photos); db.flush()
            actor_id, actor2_id = actor.id, actor2.id
            employee_ids, device_ids, photo_ids = [e.id for e in employees], [d.id for d in devices], [p.id for p in photos]
            db.commit()
        with factory() as db:
            actor = db.get(User, actor_id); _ = actor.role.permissions; _ = actor.department; db.expunge(actor)
        def enroll(index):
            for subset in range(2):
                with factory() as db:
                    op = access.enroll_gate_employee(db, db.get(User, actor_id), employee_ids[index], GateEnrollmentInput(expected_employee_no=prefix + str(index), device_ids=device_ids[subset*2:subset*2+2], photo_asset_id=photo_ids[index*2+subset], manual_face_reviewed=True), prefix + "en" + str(index) + str(subset))
                result = sim.run_simulator_operation(factory, actor, op.id)
                check(all(t.state == GateTargetState.SUCCEEDED for t in result.targets), "legitimate enrollment")
        for index in range(6):
            enroll(index)
        checks["enrollment"] = "six employees; each has two independently verified photo subsets"
        def refs(index):
            with factory() as db:
                context = access.get_gate_context(db, db.get(User, actor_id), employee_ids[index])
                result = [{"device_id": b.device_id, "expected_revision": b.edit_baseline.revision, "expected_profile_hash": b.edit_baseline.profile_hash} for b in context.bindings if b.edit_baseline]
                check(len(result) == 4, "four trusted baselines")
                return result
        def edit(index, references, key, new_name="Edited"):
            with factory() as db:
                payload = GateEditInput(expected_employee_no=prefix + str(index), reviewed_name=new_name, targets=references)
                try:
                    result = access.edit_gate_employee(db, db.get(User, actor_id), employee_ids[index], payload, key)
                    return ("ok", result.id)
                except HTTPException as exc:
                    return ("http", exc.status_code)
        def rows(op_id):
            with factory() as db:
                targets = db.scalars(select(GateTarget).where(GateTarget.operation_id == op_id).order_by(GateTarget.device_id)).all()
                people = [db.scalar(select(GateSimulatorPerson).where(GateSimulatorPerson.binding_id == t.binding_id)) for t in targets]
                return [(t.id, t.binding_id, t.state, p.full_name, p.external_person_id, p.photo_sha256, p.write_count) for t, p in zip(targets, people)]
        r = refs(0)
        with ThreadPoolExecutor(max_workers=4) as pool:
            same = list(pool.map(lambda _: edit(0, r, prefix + "same"), range(4)))
        check(all(x[0] == "ok" for x in same) and len({x[1] for x in same}) == 1, "same key stable receipt")
        op0 = same[0][1]
        r1 = refs(1)
        with ThreadPoolExecutor(max_workers=4) as pool:
            distinct = list(pool.map(lambda i: edit(1, r1, prefix + "distinct" + str(i)), range(4)))
        check(sum(x[0] == "ok" for x in distinct) == 1 and sum(x == ("http", 409) for x in distinct) == 3, "distinct key conflict")
        with factory() as db:
            check(db.scalar(select(func.count()).select_from(GateOperation).where(GateOperation.employee_id == employee_ids[1], GateOperation.action == GateAction.EDIT)) == 1, "one edit operation")
            check(db.scalar(select(func.count()).select_from(IdempotencyRecord).where(IdempotencyRecord.key.like(prefix + "distinct%"))) == 1, "no idempotency orphans")
            check(db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "turnstile.edit")) == 2, "no audit orphans")
        checks["idempotency"] = {"same_key": 4, "distinct_accept": 1, "distinct_conflict": 3}
        with factory() as db:
            device = db.scalar(select(GateSimulatorDevice).where(GateSimulatorDevice.device_id == device_ids[3])); device.online = False; db.commit()
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: sim.run_simulator_operation(factory, actor, op0), range(4)))
        before = rows(op0)
        check(sum(x[2] == GateTargetState.WAITING for x in before) == 1 and sum(x[2] == GateTargetState.SUCCEEDED for x in before) == 3, "offline partial")
        sim.reconnect_simulator_operation(factory, actor, op0)
        after = rows(op0)
        check(all(x[2] == GateTargetState.SUCCEEDED and x[3] == "Edited" and x[4] == prefix + "0" and x[6] == 2 for x in after), "processed exactly once")
        check([x[5] for x in after] == ["a" * 64, "a" * 64, "b" * 64, "b" * 64], "heterogeneous photos preserved")
        checks["processors_offline_mixed_photos"] = True
        # The adapter interposes the competing writer strictly between the first read and acceptance.
        op2 = edit(2, refs(2), prefix + "drift")[1]
        class Drift(sim.SimulatorAdapter):
            def accept(self, target_id, token):
                with factory() as db:
                    t = db.get(GateTarget, target_id)
                    person = db.scalar(select(GateSimulatorPerson).where(GateSimulatorPerson.binding_id == t.binding_id))
                    person.full_name = "Other writer"; person.accepted_payload_hash = "f" * 64; db.commit()
                return super().accept(target_id, token)
        tid = rows(op2)[0][0]
        sim._process(factory, tid, Drift(factory))
        changed = rows(op2)[0]
        check(changed[2] == GateTargetState.CONFLICT and changed[3] == "Other writer" and changed[6] == 1, "drift conflicts without overwrite")
        checks["between_read_and_accept"] = True
        # Real blocking CAS: observer confirms lock wait before the external commit.
        op3 = edit(3, refs(3), prefix + "cas")[1]
        row = rows(op3)[0]; binding_id = row[1]
        with factory() as db:
            t = db.get(GateTarget, row[0])
            baseline = {"revision": t.baseline_revision, "payload_hash": t.baseline_payload_hash, "full_name": t.baseline_full_name, "external_person_id": t.baseline_external_person_id, "photo_sha256": t.baseline_photo_sha256}
        started = Event(); outcome = []; appname = prefix + "cas"
        with factory() as external:
            person = external.scalar(select(GateSimulatorPerson).where(GateSimulatorPerson.binding_id == binding_id).with_for_update())
            person.full_name = "Concurrent writer"; person.accepted_payload_hash = "c" * 64; external.flush()
            def do_cas():
                try:
                    with factory() as db:
                        db.execute(text("SELECT set_config('application_name', :name, false)"), {"name": appname})
                        started.set()
                        outcome.append(persistence.compare_and_update_simulator_name(db, binding_id=binding_id, baseline=baseline, accepted_revision=99, accepted_payload_hash="d" * 64, full_name="Must not win"))
                        db.commit()
                except BaseException as exc:
                    outcome.append(exc)
            worker = Thread(target=do_cas); worker.start()
            check(started.wait(5), "CAS worker started")
            deadline = monotonic() + 4
            blocked = False
            while monotonic() < deadline:
                with factory() as observer:
                    blocked = bool(observer.scalar(text("SELECT EXISTS (SELECT 1 FROM pg_stat_activity WHERE application_name = :name AND wait_event_type = 'Lock')"), {"name": appname}))
                if blocked: break
                sleep(.05)
            if not blocked:
                external.rollback(); worker.join(10); raise AssertionError("CAS lock wait observed")
            external.commit(); worker.join(10)
            check(not worker.is_alive() and outcome == [False], "CAS rejected concurrent change")
        with factory() as db:
            person = db.scalar(select(GateSimulatorPerson).where(GateSimulatorPerson.binding_id == binding_id))
            check(person.full_name == "Concurrent writer" and person.accepted_payload_hash == "c" * 64 and person.write_count == 1, "CAS preserved competing write")
        checks["blocking_cas"] = True
        op4 = edit(4, refs(4), prefix + "lost")[1]
        class Lost(sim.SimulatorAdapter):
            def accept(self, target_id, token):
                super().accept(target_id, token); raise TimeoutError("lost synthetic reply")
        t4 = rows(op4)[0][0]
        sim._process(factory, t4, Lost(factory))
        check(rows(op4)[0][2] == GateTargetState.UNCERTAIN and rows(op4)[0][6] == 2, "lost reply uncertain")
        sim._process(factory, t4, sim.SimulatorAdapter(factory))
        check(rows(op4)[0][2] == GateTargetState.SUCCEEDED and rows(op4)[0][6] == 2, "read-only reconcile")
        op5 = edit(5, refs(5), prefix + "uncertain")[1]
        t5 = rows(op5)[0][0]
        with factory() as db:
            target_row = db.get(GateTarget, t5)
            persistence.transition_target(db, target_row, state=GateTargetState.UNCERTAIN, attempts=1, error_code=GateErrorCode.LEASE_EXPIRED, lease_token=None, lease_expires_at=None, observed_evidence=None); db.commit()
        sim._process(factory, t5, sim.SimulatorAdapter(factory))
        check(rows(op5)[0][2] == GateTargetState.UNCERTAIN and rows(op5)[0][6] == 1, "uncertain baseline never resent")
        checks["unknown_recovery"] = True
        # Stale lease token cannot dispatch or finish after expiration.
        from datetime import timedelta
        t6 = rows(op5)[1][0]
        claim = sim._claim(factory, t6); check(claim is not None, "lease claimed")
        token = claim[0]
        with factory() as db:
            target_row = db.get(GateTarget, t6); target_row.lease_expires_at = sim._now() - timedelta(seconds=1); db.commit()
        try:
            sim.SimulatorAdapter(factory).accept(t6, token)
            raise AssertionError("expired lease accepted")
        except RuntimeError:
            pass
        check(not sim._finish(factory, t6, token, GateTargetState.SUCCEEDED), "expired callback fenced")
        check(rows(op5)[1][6] == 1, "expired lease no write")
        checks["lease_fencing"] = True
        with factory() as db:
            models = (GateOperation, GateTarget, IdempotencyRecord, AuditLog)
            before_counts = tuple(db.scalar(select(func.count()).select_from(m)) for m in models)
            check(access.get_gate_request(db, db.get(User, actor2_id), employee_ids[0], GateAction.EDIT, prefix + "same") is None, "actor receipt isolation")
            check(access.get_gate_request(db, db.get(User, actor_id), employee_ids[0], GateAction.EDIT, prefix + "same").id == op0, "receipt owner")
            check(access.get_gate_request(db, db.get(User, actor_id), employee_ids[1], GateAction.EDIT, prefix + "same") is None, "employee receipt isolation")
            check(tuple(db.scalar(select(func.count()).select_from(m)) for m in models) == before_counts and not db.new and not db.dirty and not db.deleted, "receipt no side effects")
        checks["receipt_isolation"] = True
        # Failed audit on an otherwise valid remaining target of operation 4.
        with factory() as db:
            context = access.get_gate_context(db, db.get(User, actor_id), employee_ids[4])
            ref = [{"device_id": b.device_id, "expected_revision": b.edit_baseline.revision, "expected_profile_hash": b.edit_baseline.profile_hash} for b in context.bindings if b.edit_baseline]
            check(len(ref) == 1, "audit fixture baseline")
            counts = tuple(db.scalar(select(func.count()).select_from(m)) for m in models)
            original = access.log_action
            def fail(*args, **kwargs): raise RuntimeError("injected audit failure")
            access.log_action = fail
            try:
                try:
                    access.edit_gate_employee(db, db.get(User, actor_id), employee_ids[4], GateEditInput(expected_employee_no=prefix + "4", reviewed_name="Audit", targets=ref), prefix + "audit")
                    raise AssertionError("audit failure not raised")
                except RuntimeError as exc:
                    check(str(exc) == "injected audit failure", "injected audit error")
            finally:
                access.log_action = original
            check(tuple(db.scalar(select(func.count()).select_from(m)) for m in models) == counts, "audit rollback")
        checks["audit_rollback"] = True
        with factory() as db:
            enroll_id = db.scalar(select(GateOperation.id).where(GateOperation.employee_id == employee_ids[0], GateOperation.action == GateAction.ENROLL).limit(1))
            def reject(sql, params):
                try:
                    with db.begin_nested(): db.execute(text(sql), params)
                except IntegrityError:
                    return
                raise AssertionError("constraint accepted invalid data")
            reject("UPDATE gate_operations SET photo_asset_id=NULL WHERE id=:id", {"id": enroll_id})
            reject("UPDATE gate_operations SET photo_asset_id=:photo WHERE id=:id", {"id": op0, "photo": photo_ids[0]})
            reject("UPDATE gate_targets SET baseline_revision=NULL WHERE id=:id", {"id": rows(op0)[0][0]})
            reject("UPDATE gate_targets SET state='invented' WHERE id=:id", {"id": rows(op0)[0][0]})
            reject("UPDATE gate_targets SET employee_id=:other WHERE id=:id", {"other": employee_ids[1], "id": rows(op0)[0][0]})
            db.rollback()
        checks["constraints"] = True
        finalize_target(target, engine)
        print(json.dumps({"status": "pass", "target": name, "checks": checks}, sort_keys=True), flush=True)
    except BaseException as exc:
        print(json.dumps({"status": "hold", "target": name, "checks": checks, "failure": type(exc).__name__, "detail": str(exc) if isinstance(exc, AssertionError) else "execution failed"}, sort_keys=True), flush=True)
        retain_fixture_uncertainty(target, engine, factory, exc)


if __name__ == "__main__":
    main()
