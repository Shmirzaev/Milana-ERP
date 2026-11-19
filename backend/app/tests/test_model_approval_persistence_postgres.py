"""Candidate only: real PostgreSQL family approval atomicity; UNRUN.

Requires QA398_POSTGRES_URL pointing to an owned disposable loopback DB.
Uses the exact candidate's existing generated-column fixture; no shared data.
"""
import threading
from concurrent.futures import ThreadPoolExecutor
import os
from uuid import uuid4

import pytest
from sqlalchemy import text, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.models import audit_service
from app.models.catalog import models_service
from app.schemas import AuditLog, Model, ModelBOM, User
from app.db.base import Base
from app.tests.test_catalog_family_operations_query_growth import _group_key_sql


@pytest.fixture
def approval_pg():
    raw = os.environ.get('QA398_POSTGRES_URL')
    expected_db = os.environ.get('QA398_DATABASE')
    expected_system = os.environ.get('QA398_SYSTEM_IDENTIFIER')
    if not raw and not expected_db and not expected_system:
        pytest.skip('Owned PostgreSQL target is not configured')
    if not raw or not expected_db or not expected_system:
        pytest.fail('Partial PostgreSQL configuration: URL, database and system identifier are all required')
    url = make_url(raw)
    if url.get_backend_name() != 'postgresql' or url.host not in {'127.0.0.1', 'localhost', '::1'} or url.query or url.database != expected_db:
        pytest.fail('Expected the pinned dedicated loopback database without overrides')
    admin = create_engine(url, pool_size=1, max_overflow=0)
    def verify(conn):
        identity = conn.execute(text('SELECT current_database(), system_identifier::text FROM pg_control_system()')).one()
        assert tuple(identity) == (expected_db, expected_system), 'database identity changed'
    schema = 'qa398_approval_' + uuid4().hex
    engine = None
    try:
        with admin.begin() as conn:
            verify(conn)
            conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        engine = create_engine(url, connect_args={'options': f'-csearch_path={schema} -cstatement_timeout=30000'}, pool_size=4, max_overflow=0)
        with engine.connect() as conn:
            verify(conn)
        tables = set(); pending = [Model.__table__, ModelBOM.__table__, User.__table__, AuditLog.__table__]
        while pending:
            table = pending.pop()
            if table in tables: continue
            tables.add(table); pending.extend(fk.column.table for fk in table.foreign_keys)
        Base.metadata.create_all(engine, tables=list(tables))
        with engine.begin() as conn:
            conn.exec_driver_sql("ALTER TABLE models ADD COLUMN is_legacy_import boolean GENERATED ALWAYS AS ((coalesce(details_json ->> 'legacy_import', 'false')) = 'true') STORED")
            conn.exec_driver_sql(f"ALTER TABLE models ADD COLUMN model_group_key text GENERATED ALWAYS AS ({_group_key_sql()}) STORED")
            conn.exec_driver_sql('CREATE INDEX ix_models_model_group_key_id ON models (is_legacy_import, model_group_key, id DESC)')
        yield engine
    finally:
        if engine is not None: engine.dispose()
        with admin.begin() as conn:
            verify(conn)  # Never drop on an unexpected database.
            conn.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
            verify(conn)
        admin.dispose()


def seed(engine):
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    key = 'QA398-' + uuid4().hex[:10]
    with Session.begin() as db:
        actor = User(email=key + '@example.com', password_hash='x', name=key)
        db.add(actor); db.flush()
        rows = [Model(code=key + suffix, name=key, status='draft', catalog_scope='standard',
                      details_json={'general': {'model_no': key, 'variant_no': suffix}})
                for suffix in ('', 'V1', 'V2')]
        control = Model(code=key+'-OTHER', name=key, status='draft', catalog_scope='standard', details_json={'general': {'model_no': key+'-OTHER'}})
        db.add_all(rows + [control]); db.flush()
        return actor.id, [row.id for row in rows], control.id, key


def test_postgres_approval_locks_family_and_commits_one_ordered_audit_set(approval_pg, monkeypatch):
    Session = sessionmaker(bind=approval_pg, expire_on_commit=False)
    actor_id, ids, control_id, key = seed(approval_pg)
    original = models_service._approval_family
    locked = threading.Event(); release = threading.Event(); second_started = threading.Event()
    pids = {}
    monkeypatch.setattr(models_service, '_model_out_payload', lambda row, scope: {'id': row.id})
    monkeypatch.setattr(models_service, '_catalog_paid_operation_factory_scope', lambda *args: None)

    def intercept(db, model):
        pid = db.execute(text('SELECT pg_backend_pid()')).scalar_one()
        if threading.current_thread().name.startswith('first'):
            pids['first'] = pid
            family = original(db, model)  # actual transaction advisory lock is held
            locked.set()
            assert release.wait(10), 'second session was not observed waiting'
            return family
        pids['second'] = pid
        second_started.set()
        return original(db, model)
    monkeypatch.setattr(models_service, '_approval_family', intercept)

    def run(mid, prefix):
        threading.current_thread().name = prefix
        with Session() as db:
            models_service.approve_model(db.get(User, actor_id), db, mid)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(run, ids[0], 'first')
        try:
            assert locked.wait(10)
            second = pool.submit(run, ids[1], 'second')
            assert second_started.wait(10)
            # Explicit bounded observation: actual second backend must wait on an advisory lock.
            import time
            deadline = time.monotonic() + 8
            waiting = False
            while time.monotonic() < deadline:
                with approval_pg.connect() as conn:
                    waiting = bool(conn.execute(text("""SELECT EXISTS (
                        SELECT 1 FROM pg_locks waiter JOIN pg_locks holder
                          ON holder.locktype=waiter.locktype AND holder.database=waiter.database
                         AND holder.classid=waiter.classid AND holder.objid=waiter.objid
                         AND holder.objsubid=waiter.objsubid
                        WHERE waiter.pid=:second AND NOT waiter.granted AND waiter.locktype='advisory'
                          AND holder.pid=:first AND holder.granted
                          AND :first = ANY(pg_blocking_pids(:second))
                          AND waiter.classid=CASE WHEN hashtext(:lock_key) < 0 THEN 4294967295 ELSE 0 END::oid
                          AND waiter.objid=(hashtext(:lock_key)::bigint & 4294967295)::oid
                          AND waiter.objsubid=1)"""), {'first': pids['first'], 'second': pids['second'], 'lock_key': 'model-approval:standard:model:' + key.lower()}).scalar_one())
                if waiting: break
                time.sleep(0.05)
            assert waiting, 'second approval never observed waiting on advisory lock'
        finally:
            release.set()
        first.result(timeout=15); second.result(timeout=15)
    with Session() as db:
        rows = [db.get(Model, mid) for mid in ids]
        assert all(row.status == 'approved' and row.approved_by == actor_id and row.approved_at is not None for row in rows)
        control = db.get(Model, control_id)
        assert (control.status, control.approved_by, control.approved_at) == ('draft', None, None)
        assert len({row.approved_at for row in rows}) == 1
        audits = db.query(AuditLog).filter(AuditLog.entity_type == 'Model', AuditLog.entity_id.in_(ids), AuditLog.action == 'approve').order_by(AuditLog.id).all()
        assert [row.entity_id for row in audits] == ids
        assert all(row.new_value_json == {'approval_scope': 'model_family', 'requested_model_id': ids[0]} for row in audits)
        assert audit_service.verify_audit_hash_chain(db)['ok']


def test_postgres_audit_finalized_then_failure_rolls_back_family_and_chain(approval_pg, monkeypatch):
    Session = sessionmaker(bind=approval_pg, expire_on_commit=False)
    actor_id, ids, control_id, key = seed(approval_pg)
    with Session() as db:
        audit_service.log_action(db, db.get(User, actor_id), 'seed', 'QA398', actor_id, new_value={'marker': key})
        db.commit()
    def snapshot(db):
        return [(r.id, r.user_id, r.action, r.entity_type, r.entity_id, r.old_value_json, r.new_value_json, r.prev_hash, r.entry_hash, r.created_at)
                for r in db.query(AuditLog).order_by(AuditLog.id).all()]
    with Session() as db:
        before_chain = snapshot(db)
        before_family = [(r.id, r.status, r.approved_by, r.approved_at) for r in db.query(Model).filter(Model.id.in_(ids + [control_id])).order_by(Model.id)]
        assert before_chain and before_chain[-1][8] is not None
        assert audit_service.verify_audit_hash_chain(db)['ok']
    original = audit_service._finalize_postgres_audits
    def fail_after_finalize(db):
        original(db)
        assert db.query(AuditLog).filter(AuditLog.entity_id.in_(ids), AuditLog.action == 'approve').count() == len(ids)
        raise RuntimeError('injected after real audit finalization')
    monkeypatch.setattr(audit_service, '_finalize_postgres_audits', fail_after_finalize)
    with Session() as db:
        with pytest.raises(RuntimeError, match='injected after real audit finalization'):
            models_service.approve_model(db.get(User, actor_id), db, ids[0])
        db.rollback()
    with Session() as db:
        after_family = [(r.id, r.status, r.approved_by, r.approved_at) for r in db.query(Model).filter(Model.id.in_(ids + [control_id])).order_by(Model.id)]
        assert after_family == before_family
        assert snapshot(db) == before_chain
        assert db.query(AuditLog).filter(AuditLog.entity_id.in_(ids), AuditLog.action == 'approve').count() == 0
        result = audit_service.verify_audit_hash_chain(db)
        assert result['ok'] and result['checked'] == len(before_chain)
