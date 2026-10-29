"""Synthetic PostgreSQL replay/contention and exact master reassignment commit."""
from concurrent.futures import ThreadPoolExecutor
import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest

from app.libs.dto.packaging.manual_package_input import ManualPackageCreateIn
from app.models.idempotency_service import bind_idempotency_identity
from app.models.packaging.manual_packages_service import create_manual_packages
from app.schemas import AuditLog, Employee, FinishedGoodsStock, Model, ModelSize, Package, PackagePrintRun, User
from app.tests.test_payroll_split_correction_races import split_postgres_sessions  # noqa: F401


def _seed(sessions):
    with sessions() as db:
        user = User(name="Manual pack QA", email=f"packs-{uuid4().hex}@example.com",
                    password_hash="synthetic", factory_code="MIL", extra_permissions=["packaging.packages"])
        model = Model(code=f"QA-PACK-{uuid4().hex}", name="Manual pack QA", status="approved", catalog_scope="standard", category="T-shirt")
        model.sizes = [ModelSize(size="M")]
        db.add_all([user, model]); db.commit()
        return user.id, ManualPackageCreateIn(request_key=uuid4(), model_id=model.id, color="White",
                                              weight_kg=1.5, count=2, pack_quantities=[8, 3])


def _create(sessions, actor_id, payload):
    with sessions() as db:
        actor = db.get(User, actor_id)
        bind_idempotency_identity(db, actor)
        return create_manual_packages(db, actor, payload).model_dump(mode="json")


def test_same_request_concurrent_and_twenty_replays(split_postgres_sessions):
    sessions = split_postgres_sessions
    actor, payload = _seed(sessions)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: _create(sessions, actor, payload), range(4)))
    assert all(row == results[0] for row in results)
    for _ in range(20):
        assert _create(sessions, actor, payload) == results[0]
    with sessions() as db:
        assert db.query(Package).count() == 2
        assert db.query(PackagePrintRun).count() == 1
        assert sum(row.quantity for row in db.query(FinishedGoodsStock)) == 11
        assert db.query(AuditLog).filter_by(action="manual_packaging").count() == 1


def test_six_distinct_parallel_requests_conserve_quantities(split_postgres_sessions):
    sessions = split_postgres_sessions
    actor, payload = _seed(sessions)
    requests = [payload.model_copy(update={"request_key": uuid4()}) for _ in range(6)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda request: _create(sessions, actor, request), requests))
    assert len({row['print_run']['id'] for row in results}) == 6
    with sessions() as db:
        assert db.query(Package).count() == 12
        assert db.query(PackagePrintRun).count() == 6
        assert sum(row.quantity for row in db.query(FinishedGoodsStock)) == 66
        assert all(p.status == 'packed' and p.received_at is None for p in db.query(Package))


def _master_module():
    path = Path(__file__).resolve().parents[3] / 'ops/reassign_dilafruz_masters_20261028.py'
    spec = importlib.util.spec_from_file_location('master_operation', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def test_exact_master_reassignment_rehearsal_commit_and_guard(split_postgres_sessions):
    sessions = split_postgres_sessions
    operation = _master_module()
    with sessions() as db:
        for eid, number in [(129, '503'), (313, '321'), (1581, 'QA1'), (1587, 'QA2')]:
            db.add(Employee(id=eid, employee_no=number, full_name='Akbarova Dilafruz' if eid in (129, 313) else f'Synthetic employee {eid}', factory_code='MIL'))
        db.flush()
        for eid in (1581, 1587):
            db.get(Employee, eid).manager_employee_id = 129
        db.commit()
    with sessions() as db:
        evidence = operation.reassign(db)
        assert evidence['applied'] is False
    with sessions() as db:
        assert db.get(Employee, 1581).manager_employee_id == 129
        assert db.query(AuditLog).count() == 0
    with sessions() as db:
        evidence = operation.reassign(db, apply=True)
        assert evidence['changed_employee_ids'] == [1581, 1587]
    with sessions() as db:
        assert db.get(Employee, 1581).manager_employee_id == db.get(Employee, 1587).manager_employee_id == 313
        assert db.get(Employee, 129).employee_no == '503'
        assert db.get(Employee, 313).employee_no == '321'
        audits = db.query(AuditLog).order_by(AuditLog.id).all()
        assert len(audits) == 2 and all(a.entry_hash for a in audits)
        assert audits[1].prev_hash == audits[0].entry_hash
    with sessions() as db:
        with pytest.raises(AssertionError, match='Direct reports changed'):
            operation.reassign(db, apply=True)
