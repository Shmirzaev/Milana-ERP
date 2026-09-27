from concurrent.futures import ThreadPoolExecutor
import os
from queue import Queue
from threading import Event, current_thread
from time import monotonic, sleep
from uuid import uuid4

from fastapi import HTTPException
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.api.routes import package_workflows as routes
from app.core.security import create_access_token
from app.db.base import Base
from app.db.session import SessionLocal
from app.models import (
    FinishedGoodsStock,
    IdempotencyRecord,
    ManualPackageReceipt,
    Package,
    PackagePrintRun,
    Role,
    User,
)
from app.schemas.package_workflows import ManualPackageReceiptIn
from app.services import package_workflows as service
from app.tests.test_package_workflows import manual_body, packaging_order, warehouse  # noqa: F401


BASE = "/api/packages/manual-receipt"


@pytest.fixture(scope="module")
def reconciliation_postgres_sessions():
    raw_url = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw_url:
        pytest.skip("Set STABILIZATION_POSTGRES_URL for real PostgreSQL reconciliation races")
    url = make_url(raw_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"} or url.query:
        pytest.fail("Reconciliation race tests require a loopback PostgreSQL URL without connection overrides")
    schema = f"manual_receipt_reconcile_{uuid4().hex}"
    engine = create_engine(
        url,
        connect_args={"options": f"-csearch_path={schema} -clock_timeout=15000 -cstatement_timeout=20000"},
        pool_size=4,
        max_overflow=0,
        isolation_level="READ COMMITTED",
    )
    assert engine.dialect.name == "postgresql"
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        Base.metadata.create_all(engine)
        sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        with sessions() as db:
            user = User(
                name="Synthetic receipt reconciler",
                email=f"receipt-reconcile-{uuid4().hex}@example.test",
                password_hash="not-used",
                factory_code="MIL",
                extra_permissions=["storage.packages"],
            )
            db.add(user)
            db.commit()
            user_id = user.id
        yield sessions, engine, user_id
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


def _race_payload():
    return ManualPackageReceiptIn(
        request_key=uuid4(),
        model_id=1,
        color="Synthetic",
        weight_kg=1,
        count=1,
        pack_quantities=[1],
        reason="Synthetic reconciliation race",
    )


def _minimal_receipt_result(db, user, token):
    run = PackagePrintRun(
        run_no=f"PRN-{token}",
        code=f"PACKRUN:{token}",
        packaging_department_code="PKG",
        package_ids=[],
        created_by=user.id,
        deleted_package_ids=[],
    )
    db.add(run)
    db.flush()
    return {"receipt_no": f"WMR-{token}", "print_run": {"id": run.id}}


def _direct_original(sessions, user_id, payload, action):
    with sessions() as db:
        user = db.get(User, user_id)
        try:
            return routes._write(db, user, "manual-receipt", payload, lambda: action(db, user))
        except Exception as exc:
            db.rollback()
            return exc


def _direct_reconcile(sessions, user_id, payload, ready=None):
    with sessions() as db:
        user = db.get(User, user_id)
        if ready is not None:
            ready.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
        try:
            return routes.reconcile_manual_receipt(payload, db, current=user)
        except Exception as exc:
            db.rollback()
            return exc


def _business_counts() -> tuple[int, int, int]:
    with SessionLocal() as db:
        return (
            db.query(ManualPackageReceipt).count(),
            db.query(Package).count(),
            db.query(FinishedGoodsStock).count(),
        )


def test_cancel_unconfirmed_manual_receipt_blocks_delayed_original(client, warehouse):
    body = manual_body()
    before = _business_counts()

    cancelled = client.post(f"{BASE}/reconcile", headers=warehouse, json=body)

    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json() == {"status": "cancelled"}
    repeated = client.post(f"{BASE}/reconcile", headers=warehouse, json=body)
    assert repeated.status_code == 200, repeated.text
    assert repeated.json() == {"status": "cancelled"}
    delayed = client.post(BASE, headers=warehouse, json=body)
    assert delayed.status_code == 409, delayed.text
    assert _business_counts() == before
    with SessionLocal() as db:
        tombstone = db.query(IdempotencyRecord).filter(
            IdempotencyRecord.key == body["request_key"],
        ).one()
        assert tombstone.status_code == 409


def test_reconcile_completed_manual_receipt_returns_exact_result(client, warehouse):
    body = manual_body()
    created = client.post(BASE, headers=warehouse, json=body)
    assert created.status_code == 201, created.text

    reconciled = client.post(f"{BASE}/reconcile", headers=warehouse, json=body)

    assert reconciled.status_code == 200, reconciled.text
    assert reconciled.json() == {"status": "completed", "result": created.json()}
    assert _business_counts()[0] == 1

    conflict = client.post(
        f"{BASE}/reconcile",
        headers=warehouse,
        json={**body, "color": "Changed"},
    )
    assert conflict.status_code == 409, conflict.text


def test_reconcile_inactive_completed_receipt_resolves_without_stale_result(client, warehouse):
    body = manual_body()
    created = client.post(BASE, headers=warehouse, json=body)
    assert created.status_code == 201, created.text
    with SessionLocal() as db:
        run = db.get(PackagePrintRun, created.json()["print_run"]["id"])
        run.deleted_at = run.created_at
        db.commit()

    reconciled = client.post(f"{BASE}/reconcile", headers=warehouse, json=body)

    assert reconciled.status_code == 200, reconciled.text
    assert reconciled.json() == {"status": "completed_unavailable"}
    retry = client.post(BASE, headers=warehouse, json=body)
    assert retry.status_code == 410, retry.text


def test_reconcile_rejects_changed_payload_for_reserved_key(client, warehouse):
    body = manual_body()
    assert client.post(f"{BASE}/reconcile", headers=warehouse, json=body).status_code == 200

    conflict = client.post(
        f"{BASE}/reconcile",
        headers=warehouse,
        json={**body, "color": "Changed"},
    )

    assert conflict.status_code == 409, conflict.text


def test_manual_receipt_reconciliation_is_authorized_and_user_scoped(client, warehouse, auth_headers):
    body = manual_body(request_key=str(uuid4()))
    before = _business_counts()
    assert client.post(f"{BASE}/reconcile", json=body).status_code == 401
    planning_login = client.post(
        "/api/auth/token",
        data={"username": "planning@example.com", "password": "demo12345"},
    )
    planning = {"Authorization": f"Bearer {planning_login.json()['access_token']}"}
    planning_resolution = client.post(f"{BASE}/reconcile", headers=planning, json=body)
    assert planning_resolution.status_code == 200, planning_resolution.text
    assert planning_resolution.json() == {"status": "cancelled"}
    assert _business_counts() == before
    with SessionLocal() as db:
        assert db.query(IdempotencyRecord).filter(IdempotencyRecord.key == body["request_key"]).count() == 1
    assert client.post(f"{BASE}/reconcile", headers=warehouse, json=body).status_code == 200

    other_user = client.post(BASE, headers=auth_headers, json=body)

    assert other_user.status_code == 201, other_user.text


def test_reconcile_completed_manual_receipt_after_permission_revocation_exposes_no_result(client):
    with SessionLocal() as db:
        role = Role(name=f"UI03 warehouse {uuid4().hex}", permissions=["storage.packages"])
        db.add(role)
        db.flush()
        user = User(
            name="UI03 warehouse operator",
            email=f"ui03-warehouse-{uuid4().hex}@example.invalid",
            password_hash="unused",
            role_id=role.id,
            factory_code="MIL",
            extra_permissions=[],
            is_active=True,
        )
        db.add(user)
        db.commit()
        user_id = int(user.id)
        role_id = int(role.id)
    headers = {"Authorization": f"Bearer {create_access_token(user_id)}"}
    body = manual_body()
    created = client.post(BASE, headers=headers, json=body)
    assert created.status_code == 201, created.text
    before = _business_counts()

    with SessionLocal() as db:
        db.get(Role, role_id).permissions = []
        db.commit()

    denied_retry = client.post(BASE, headers=headers, json=body)
    assert denied_retry.status_code == 403, denied_retry.text
    reconciled = client.post(f"{BASE}/reconcile", headers=headers, json=body)
    assert reconciled.status_code == 200, reconciled.text
    assert reconciled.json() == {"status": "completed_unavailable"}
    assert _business_counts() == before


def test_generic_package_reconciliation_covers_completed_deleted_and_cancelled_results(
    client,
    auth_headers,
    packaging_order,
):
    body = {"request_key": str(uuid4()), "packages": [packaging_order]}
    created = client.post(
        "/api/packages/print-runs/create-packages",
        headers=auth_headers,
        json=body,
    )
    assert created.status_code == 201, created.text
    completed = client.post(
        "/api/packages/print-runs/create-packages/reconcile",
        headers=auth_headers,
        json=body,
    )
    assert completed.status_code == 200, completed.text
    assert completed.json() == {"status": "completed", "result": created.json()}

    with SessionLocal() as db:
        run = db.get(PackagePrintRun, created.json()["id"])
        run.deleted_at = run.created_at
        db.commit()
    unavailable = client.post(
        "/api/packages/print-runs/create-packages/reconcile",
        headers=auth_headers,
        json=body,
    )
    assert unavailable.status_code == 200, unavailable.text
    assert unavailable.json() == {"status": "completed_unavailable"}
    assert client.post(
        "/api/packages/print-runs/create-packages",
        headers=auth_headers,
        json=body,
    ).status_code == 410

    cancelled_body = {"request_key": str(uuid4()), "package_ids": [2_147_483_647]}
    cancelled = client.post(
        "/api/packages/print-runs/reconcile",
        headers=auth_headers,
        json=cancelled_body,
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json() == {"status": "cancelled"}
    delayed = client.post(
        "/api/packages/print-runs",
        headers=auth_headers,
        json=cancelled_body,
    )
    assert delayed.status_code == 409, delayed.text


def test_postgres_original_commit_wins_reconciliation_race(reconciliation_postgres_sessions):
    sessions, _engine, user_id = reconciliation_postgres_sessions
    payload = _race_payload()
    token = uuid4().hex
    original_locked = Event()
    release_original = Event()
    reconcile_ready = Queue()

    def delayed_action(db, user):
        original_locked.set()
        assert release_original.wait(10), "Original receipt was not released"
        return _minimal_receipt_result(db, user, token)

    with ThreadPoolExecutor(max_workers=2) as workers:
        original = workers.submit(_direct_original, sessions, user_id, payload, delayed_action)
        assert original_locked.wait(10), "Original receipt did not acquire its advisory lock"
        reconciled = workers.submit(_direct_reconcile, sessions, user_id, payload, reconcile_ready)
        reconcile_pid = reconcile_ready.get(timeout=10)
        try:
            with sessions() as inspector:
                deadline = monotonic() + 10
                while monotonic() < deadline:
                    blockers = inspector.execute(
                        text("SELECT pg_blocking_pids(:pid)"),
                        {"pid": reconcile_pid},
                    ).scalar_one()
                    if blockers:
                        break
                    sleep(0.02)
                else:
                    pytest.fail("Reconciliation must wait for the in-flight original receipt")
        finally:
            release_original.set()
        created = original.result(timeout=10)
        recovered = reconciled.result(timeout=10)

    assert not isinstance(created, Exception), created
    assert recovered == {"status": "completed", "result": created}
    with sessions() as db:
        assert db.query(PackagePrintRun).filter_by(run_no=f"PRN-{token}").count() == 1
        assert db.query(IdempotencyRecord).filter_by(
            scope=f"packages.manual-receipt.{user_id}",
            key=str(payload.request_key),
        ).count() == 1


def test_postgres_cancel_wins_before_delayed_original(reconciliation_postgres_sessions, monkeypatch):
    sessions, _engine, user_id = reconciliation_postgres_sessions
    payload = _race_payload()
    original_waiting = Event()
    release_original = Event()
    action_called = Event()
    real_lock = service.lock_request

    def pause_original(db, lock_user_id, operation, key):
        if current_thread().name.startswith("delayed-original"):
            original_waiting.set()
            assert release_original.wait(10), "Delayed original receipt was not released"
        return real_lock(db, lock_user_id, operation, key)

    def forbidden_action(_db, _user):
        action_called.set()
        raise AssertionError("A cancelled request must not perform receipt writes")

    monkeypatch.setattr(service, "lock_request", pause_original)
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="delayed-original") as worker:
        original = worker.submit(_direct_original, sessions, user_id, payload, forbidden_action)
        assert original_waiting.wait(10), "Original receipt did not reach the pre-lock pause"
        try:
            cancelled = _direct_reconcile(sessions, user_id, payload)
        finally:
            release_original.set()
        delayed = original.result(timeout=10)

    assert cancelled == {"status": "cancelled"}
    assert isinstance(delayed, HTTPException)
    assert delayed.status_code == 409
    assert not action_called.is_set()
    with sessions() as db:
        record = db.query(IdempotencyRecord).filter_by(
            scope=f"packages.manual-receipt.{user_id}",
            key=str(payload.request_key),
        ).one()
        assert record.status_code == 409
        assert service.is_cancelled_request(record.response_json)
