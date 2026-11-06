"""Deletion against an approved, migrated, disposable PostgreSQL target."""
import pytest
import sqlalchemy as sa

from app.libs.enums.catalog import CatalogScope
from app.models.catalog import models_service as service
from app.schemas import AuditLog, Model, ModelSize, User
from app.tests.test_model_create_commit_postgres import app_for, headers
from app.models import audit_service
from fastapi.testclient import TestClient
from uuid import uuid4

pytest_plugins = ("app.tests.test_modelcolor_create_postgres",)


def _size(sessions, mid, label):
    with sessions.begin() as db:
        row = ModelSize(model_id=mid, size=label, measurement_json={'уз': 'ҳа'})
        db.add(row)
        db.flush()
        return row.id


@pytest.mark.parametrize(('index', 'scope'), [(0, CatalogScope.STANDARD), (1, CatalogScope.USLUGA)])
def test_delete_readback_and_audit(pg_sessions, pg_case, index, scope):
    actor_id = pg_case["actors"]["standard"]
    mids = [pg_case["models"]["standard"], pg_case["models"]["usluga"]]
    sid = _size(pg_sessions, mids[index], 'oʻlcham 🧵')
    with pg_sessions() as db:
        service.delete_size(db.get(User, actor_id), db, mids[index], sid, scope)
    with pg_sessions() as db:
        assert db.get(ModelSize, sid) is None
        assert db.get(Model, mids[index]) is not None
        audit = db.query(AuditLog).filter_by(entity_type='ModelSize', entity_id=sid, action='delete').one()
        assert audit.user_id == actor_id
        assert audit.new_value_json == {'model_id': mids[index], 'size': 'oʻlcham 🧵'}
        assert audit.entry_hash


def test_deferred_commit_failure_rolls_back_and_retry(pg_sessions, pg_case, monkeypatch):
    from sqlalchemy import event
    actor_id = pg_case['actors']['standard']
    mid = pg_case['models']['standard']
    sid = _size(pg_sessions, mid, 'retry 🧵')
    engine = pg_sessions.kw['bind']
    suffix = uuid4().hex[:12]
    trigger, function = f'pr394_guard_{suffix}', f'pr394_abort_{suffix}'
    observed = []
    attempted_ids = []
    original_finalize = audit_service._finalize_postgres_audits
    def observe_finalization(db):
        original_finalize(db)
        audit = db.query(AuditLog).filter_by(entity_type='ModelSize', entity_id=sid, action='delete').one()
        assert audit.id > 0 and audit.entry_hash
        assert audit.user_id == actor_id
        assert audit.new_value_json == {'model_id': mid, 'size': 'retry 🧵'}
        attempted_ids.append(audit.id)
    def capture(context):
        exc = context.original_exception
        if getattr(exc, 'pgcode', None) == '23514':
            observed.append((context.statement, exc.diag.constraint_name))
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(f"""CREATE FUNCTION {function}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
                RAISE EXCEPTION 'fixture commit failure' USING ERRCODE = '23514', CONSTRAINT = '{trigger}'; END; $$""")
            conn.exec_driver_sql(f"""CREATE CONSTRAINT TRIGGER {trigger} AFTER DELETE ON model_sizes
                DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (OLD.id = {int(sid)})
                EXECUTE FUNCTION {function}()""")
        event.listen(engine, 'handle_error', capture)
    except Exception as exc:
        raise RuntimeError(f'HOLD: uncertain setup; inspect {function} and {trigger}') from exc
    try:
        with monkeypatch.context() as patch:
            patch.setattr(audit_service, '_finalize_postgres_audits', observe_finalization)
            with pg_sessions() as db:
                with pytest.raises(sa.exc.IntegrityError):
                    service.delete_size(db.get(User, actor_id), db, mid, sid)
                db.rollback()
        assert observed == [(None, trigger)]
        assert len(attempted_ids) == 1 and attempted_ids[0] > 0
        with pg_sessions() as db:
            assert db.get(AuditLog, attempted_ids[0]) is None
            assert db.get(ModelSize, sid).size == 'retry 🧵'
            assert db.get(Model, mid) is not None
            assert db.query(AuditLog).filter_by(entity_type='ModelSize', entity_id=sid, action='delete').count() == 0
    finally:
        event.remove(engine, 'handle_error', capture)
        with engine.begin() as conn:
            conn.exec_driver_sql(f'DROP TRIGGER {trigger} ON model_sizes')
            conn.exec_driver_sql(f'DROP FUNCTION {function}()')
    with pg_sessions() as db:
        service.delete_size(db.get(User, actor_id), db, mid, sid)
    with pg_sessions() as db:
        assert db.get(ModelSize, sid) is None
        audit = db.query(AuditLog).filter_by(entity_type='ModelSize', entity_id=sid, action='delete').one()
        assert audit.id > 0 and audit.id != attempted_ids[0] and audit.entry_hash
        assert audit.user_id == actor_id
        assert audit.new_value_json == {'model_id': mid, 'size': 'retry 🧵'}


@pytest.mark.parametrize(('scope', 'path', 'actor'), [
    ('standard', '/api/models', 'standard'), ('usluga', '/api/usluga/models', 'eco'),
])
def test_signed_scope_permissions_missing_and_retained_state(pg_sessions, pg_case, scope, path, actor):
    mid = pg_case['models'][scope]
    other_mid = pg_case['models']['usluga' if scope == 'standard' else 'standard']
    sid = _size(pg_sessions, mid, 'oʻlcham 🧵')
    other_sid = _size(pg_sessions, other_mid, 'other')
    url = f'{path}/{mid}/sizes/{sid}'
    with pg_sessions() as retained:
        parent = retained.get(Model, mid)
        row = retained.get(ModelSize, sid)
        assert sid > 0 and row in parent.sizes
        with TestClient(app_for(pg_sessions), raise_server_exceptions=False) as client:
            assert client.delete(url).status_code == 401
            assert client.delete(url, headers=headers(pg_case['actors']['denied'])).status_code == 403
            if scope == 'usluga':
                assert client.delete(url, headers=headers(pg_case['actors']['wrong_factory'])).status_code == 403
            opposite = '/api/usluga/models' if scope == 'standard' else '/api/models'
            opposite_actor = 'eco' if scope == 'standard' else 'standard'
            assert client.delete(f'{opposite}/{mid}/sizes/{sid}', headers=headers(pg_case['actors'][opposite_actor])).status_code == 404
            assert client.delete(f'{path}/{mid}/sizes/{other_sid}', headers=headers(pg_case['actors'][actor])).status_code == 404
            assert client.delete(f'{path}/{other_mid}/sizes/{sid}', headers=headers(pg_case['actors'][actor])).status_code == 404
            with pg_sessions() as db:
                assert db.get(ModelSize, sid) is not None
                assert db.query(AuditLog).filter_by(entity_type='ModelSize', entity_id=sid, action='delete').count() == 0
            response = client.delete(url, headers=headers(pg_case['actors'][actor]))
            assert response.status_code == 204, response.text
            assert client.delete(url, headers=headers(pg_case['actors'][actor])).status_code == 404
        assert row.size == 'oʻlcham 🧵' and row in parent.sizes
        retained.expire_all()
        assert retained.get(ModelSize, sid) is None
        assert all(item.id != sid for item in parent.sizes)
        assert retained.get(Model, mid) is parent
    with pg_sessions() as db:
        assert db.get(ModelSize, other_sid) is not None
        audit = db.query(AuditLog).filter_by(entity_type='ModelSize', entity_id=sid, action='delete').one()
        assert audit.user_id == pg_case['actors'][actor]
        assert audit.new_value_json == {'model_id': mid, 'size': 'oʻlcham 🧵'}
        assert audit.entry_hash and audit.id > 0


def test_signed_audit_finalization_failure_rolls_back_and_retry(pg_sessions, pg_case, monkeypatch):
    mid = pg_case['models']['standard']
    sid = _size(pg_sessions, mid, 'finalize 🧵')
    observed = []
    original = audit_service._finalize_postgres_audits
    def fail_after_finalization(db):
        original(db)
        row = db.query(AuditLog).filter_by(entity_type='ModelSize', entity_id=sid, action='delete').one()
        assert row.id > 0 and row.entry_hash
        assert db.get(ModelSize, sid) is None
        observed.append(row.id)
        raise RuntimeError('injected after audit finalization')
    path = f'/api/models/{mid}/sizes/{sid}'
    with monkeypatch.context() as patch:
        patch.setattr(audit_service, '_finalize_postgres_audits', fail_after_finalization)
        with TestClient(app_for(pg_sessions), raise_server_exceptions=False) as client:
            response = client.delete(path, headers=headers(pg_case['actors']['standard']))
    assert response.status_code == 500 and len(observed) == 1 and observed[0] > 0
    with pg_sessions() as db:
        assert db.get(AuditLog, observed[0]) is None
        assert db.get(ModelSize, sid).size == 'finalize 🧵'
        assert db.get(Model, mid) is not None
        assert db.query(AuditLog).filter_by(entity_type='ModelSize', entity_id=sid, action='delete').count() == 0
        assert audit_service.verify_audit_hash_chain(db)['ok']
    with TestClient(app_for(pg_sessions), raise_server_exceptions=False) as client:
        response = client.delete(path, headers=headers(pg_case['actors']['standard']))
        assert response.status_code == 204, response.text
    with pg_sessions() as db:
        assert db.get(ModelSize, sid) is None
        audit = db.query(AuditLog).filter_by(entity_type='ModelSize', entity_id=sid, action='delete').one()
        assert audit.id > 0 and audit.id != observed[0] and audit.entry_hash
        assert audit.user_id == pg_case['actors']['standard']
        assert audit.new_value_json == {'model_id': mid, 'size': 'finalize 🧵'}
        assert audit_service.verify_audit_hash_chain(db)['ok']


def test_last_size_with_issued_bundle_preserves_bundle(pg_sessions, pg_case):
    from app.schemas import Bundle, ProductionOrder
    mid = pg_case['models']['standard']
    label = 'QR 🧵'
    sid = _size(pg_sessions, mid, label)
    token = uuid4().hex
    with pg_sessions.begin() as db:
        order = ProductionOrder(production_no=f'PO{token}', production_type='branded_stock', model_id=mid)
        db.add(order); db.flush()
        bundle = Bundle(bundle_no=f'B{token}', barcode=f'B{token}', qr_code_url='/fixture/issued-qr',
                        production_order_id=order.id, model_id=mid, color='white', size=label, quantity=1)
        db.add(bundle); db.flush()
        bundle_id = bundle.id
        assert bundle_id > 0
    with TestClient(app_for(pg_sessions), raise_server_exceptions=False) as client:
        response = client.delete(f'/api/models/{mid}/sizes/{sid}', headers=headers(pg_case['actors']['standard']))
        assert response.status_code == 204, response.text
    with pg_sessions() as db:
        assert db.query(ModelSize).filter_by(model_id=mid).count() == 0
        bundle = db.get(Bundle, bundle_id)
        assert (bundle.model_id, bundle.size, bundle.qr_code_url) == (mid, label, '/fixture/issued-qr')
        assert db.query(AuditLog).filter_by(entity_type='ModelSize', entity_id=sid, action='delete').count() == 1


def test_delete_and_same_label_insert_interleave_without_unique_guard(pg_sessions, pg_case, monkeypatch):
    """A real insert can commit while the old row's DELETE remains uncommitted."""
    from concurrent.futures import ThreadPoolExecutor, wait
    from threading import Event, current_thread
    from sqlalchemy import event
    from app.libs.types.catalog import ModelSizeCreateCommand
    from app.schemas import Bundle, ProductionOrder
    from app.schemas.catalog.model_size_persistence import insert_model_size
    from app.tests.pg_approved_instance import _park

    mid = pg_case['models']['standard']
    label = 'bir xil 🧵'
    sid = _size(pg_sessions, mid, label)
    token = uuid4().hex
    with pg_sessions.begin() as db:
        order = ProductionOrder(production_no=f'P{token}', production_type='branded_stock', model_id=mid)
        db.add(order); db.flush()
        bundle = Bundle(bundle_no=f'B{token}', barcode=f'B{token}', qr_code_url='/fixture/issued-qr',
                        production_order_id=order.id, model_id=mid, color='white', size=label, quantity=1)
        db.add(bundle); db.flush()
        bundle_id = bundle.id
    flushed, release = Event(), Event()
    threads = []
    errors = []
    original = service.delete_model_size

    def pause_after_real_flush(db, row):
        original(db, row)
        def after_flush(session, _context):
            if row in session.deleted:
                flushed.set()
                if not release.wait(20):
                    raise TimeoutError('delete flush release timed out')
        event.listen(db, 'after_flush', after_flush, once=True)

    def delete_request():
        threads.append(current_thread())
        with TestClient(app_for(pg_sessions), raise_server_exceptions=False) as client:
            return client.delete(f'/api/models/{mid}/sizes/{sid}', headers=headers(pg_case['actors']['standard'])).status_code

    def insert_replacement():
        threads.append(current_thread())
        with pg_sessions.begin() as db:
            row = insert_model_size(db, ModelSizeCreateCommand(model_id=mid, size=label, measurement_json={'уз': 'ҳа'}))
            assert row.id > 0 and row.id != sid
            return row.id

    monkeypatch.setattr(service, 'delete_model_size', pause_after_real_flush)
    pool = ThreadPoolExecutor(max_workers=2)
    futures = []
    try:
        futures.append(pool.submit(delete_request))
        assert flushed.wait(10), 'delete did not reach the production flush'
        futures.append(pool.submit(insert_replacement))
        replacement_id = futures[1].result(timeout=10)
        # The deletion is still held, so this establishes actual overlap without
        # inferring anything from elapsed time or claiming a PostgreSQL lock wait.
        assert not futures[0].done()
        with pg_sessions() as db:
            assert db.get(ModelSize, sid) is not None
            assert db.get(ModelSize, replacement_id).size == label
    finally:
        release.set()
        try:
            _, pending = wait(futures, timeout=25)
            if pending:
                raise TimeoutError('owned operation completion unknown')
            pool.shutdown(wait=False, cancel_futures=False)
            for thread in threads:
                thread.join(timeout=10)
            if any(thread.is_alive() for thread in threads):
                raise TimeoutError('owned thread termination unknown')
        except BaseException as error:
            errors.append(error)
            # Never unwind into fixture finalization with uncertain workers.
            if any(not future.done() for future in futures) or any(thread.is_alive() for thread in threads):
                _park('PR394_SIZE_INTERLEAVE', (pool, futures, threads, pg_sessions, release), errors)
            raise
    assert futures[0].result() == 204
    with pg_sessions() as db:
        assert db.get(ModelSize, sid) is None
        replacement = db.get(ModelSize, replacement_id)
        assert (replacement.model_id, replacement.size, replacement.measurement_json) == (mid, label, {'уз': 'ҳа'})
        bundle = db.get(Bundle, bundle_id)
        assert (bundle.model_id, bundle.size, bundle.qr_code_url) == (mid, label, '/fixture/issued-qr')
        audit = db.query(AuditLog).filter_by(entity_type='ModelSize', entity_id=sid, action='delete').one()
        assert audit.id > 0 and audit.entry_hash and audit.new_value_json == {'model_id': mid, 'size': label}
