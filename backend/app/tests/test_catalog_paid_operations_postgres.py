"""Real PostgreSQL paid-operation participant checks on an approved disposable database."""
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import text

from app.libs.dto.catalog.model_input import ModelPaidOperationsIn
from app.models import audit_service
from app.models.catalog import models_service
from app.models.paid_operations_service import filter_paid_operations_for_factory
from app.schemas import AuditLog, Model, User
from app.tests.test_model_approval_persistence_postgres import seed
from app.tests.test_modelsize_create_postgres import pg_sessions as pg_sessions
from app.tests.test_paid_operation_factory_scope import _operation


def _payload(factory, operation):
    return ModelPaidOperationsIn(sewing_factory=factory, paid_operations=[_operation(operation, factory)])


def _snapshot(db, ids):
    return [(row.id, row.details_json) for row in db.query(Model).filter(Model.id.in_(ids)).order_by(Model.id)]


def _audit_snapshot(db):
    return [(row.id, row.action, row.entity_id, row.old_value_json, row.new_value_json,
             row.prev_hash, row.entry_hash) for row in db.query(AuditLog).order_by(AuditLog.id)]


def test_paid_family_postgres_lock_serializes_distinct_factory_saves(pg_sessions, monkeypatch):  # noqa: F811
    actor_id, ids, control_id, _ = seed(pg_sessions.kw['bind'])
    original = models_service._approval_family
    locked, release, waiting = threading.Event(), threading.Event(), threading.Event()
    pids = {}
    monkeypatch.setattr(models_service, '_catalog_paid_operation_factory_scope', lambda *args: None)
    monkeypatch.setattr(models_service, '_model_out_payload', lambda row, scope: {'id': row.id})

    def intercept(db, model):
        label = threading.current_thread().name
        pids[label] = db.execute(text('SELECT pg_backend_pid()')).scalar_one()
        if label == 'first':
            family = original(db, model)
            locked.set()
            assert release.wait(10)
            return family
        waiting.set()
        return original(db, model)

    monkeypatch.setattr(models_service, '_approval_family', intercept)

    def save(label, mid, factory):
        threading.current_thread().name = label
        with pg_sessions() as db:
            models_service.update_model_paid_operations(db.get(User, actor_id), db, mid, _payload(factory, label))

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(save, 'first', ids[0], 'milana')
        try:
            assert locked.wait(10)
            second = pool.submit(save, 'second', ids[1], 'besttex')
            assert waiting.wait(10)
            deadline = time.monotonic() + 8
            observed = False
            while time.monotonic() < deadline:
                with pg_sessions() as db:
                    observed = db.execute(text('SELECT :holder = ANY(pg_blocking_pids(:waiter))'),
                                          {'holder': pids['first'], 'waiter': pids['second']}).scalar_one()
                if observed:
                    break
                time.sleep(0.05)
            assert observed, 'second family save was not observed blocked by first'
        finally:
            release.set()
        first.result(timeout=15)
        second.result(timeout=15)
    with pg_sessions() as db:
        for mid in ids:
            details = db.get(Model, mid).details_json
            assert filter_paid_operations_for_factory(details, 'milana')['paid_operations'] == [_operation('first', 'milana')]
            assert filter_paid_operations_for_factory(details, 'besttex')['paid_operations'] == [_operation('second', 'besttex')]
        assert not db.get(Model, control_id).details_json.get('paid_operations')
        audits = db.query(AuditLog).filter(AuditLog.action == 'update_paid_operations', AuditLog.entity_id.in_(ids)).order_by(AuditLog.id).all()
        assert [a.entity_id for a in audits] == ids + ids
        assert [a.new_value_json['factory'] for a in audits] == ['milana'] * len(ids) + ['besttex'] * len(ids)
        assert all(a.entry_hash for a in audits)
        assert audit_service.verify_audit_hash_chain(db)['ok']


def test_paid_family_postgres_second_audit_queue_failure_rolls_back_then_recovers(pg_sessions, monkeypatch):  # noqa: F811
    actor_id, ids, control_id, key = seed(pg_sessions.kw['bind'])
    monkeypatch.setattr(models_service, '_catalog_paid_operation_factory_scope', lambda *args: None)
    monkeypatch.setattr(models_service, '_model_out_payload', lambda row, scope: {'id': row.id})
    with pg_sessions() as db:
        audit_service.log_action(db, db.get(User, actor_id), 'seed', 'test', actor_id, new_value={'key': key})
        db.commit()
    with pg_sessions() as db:
        before_rows, before_audits = _snapshot(db, ids + [control_id]), _audit_snapshot(db)
    original = models_service.log_action
    calls = 0

    def fail(*args, **kwargs):
        nonlocal calls
        original(*args, **kwargs)
        calls += 1
        if calls == 2:
            raise RuntimeError('second audit queued')

    with monkeypatch.context() as patch:
        patch.setattr(models_service, 'log_action', fail)
        with pg_sessions() as db:
            with pytest.raises(RuntimeError, match='second audit queued'):
                models_service.update_model_paid_operations(db.get(User, actor_id), db, ids[0], _payload('milana', 'retry'))
            db.rollback()
    assert calls == 2
    with pg_sessions() as db:
        assert _snapshot(db, ids + [control_id]) == before_rows
        assert _audit_snapshot(db) == before_audits
        assert audit_service.verify_audit_hash_chain(db)['ok']
    with pg_sessions() as db:
        models_service.update_model_paid_operations(db.get(User, actor_id), db, ids[0], _payload('milana', 'retry'))
    with pg_sessions() as db:
        assert all(filter_paid_operations_for_factory(db.get(Model, mid).details_json, 'milana')['paid_operations'] == [_operation('retry', 'milana')] for mid in ids)
        assert db.query(AuditLog).filter(AuditLog.action == 'update_paid_operations', AuditLog.entity_id.in_(ids)).count() == len(ids)
        assert audit_service.verify_audit_hash_chain(db)['ok']
