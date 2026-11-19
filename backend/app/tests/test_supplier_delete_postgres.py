"""Supplier DELETE on identity-pinned migrated disposable PostgreSQL only."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError
from app.core.security import create_access_token
from app.models import audit_service
from app.models.catalog import partners_service
from app.schemas import (AuditLog, Item, PurchaseOrder, PurchaseOrderLine, PurchaseRequest,
                         PurchaseRequestLine, StockBatch, Supplier, User, Warehouse)
from app.tests.test_customer_create_postgres import chain, customer_pg_sessions  # noqa: F401
from app.tests.test_supplier_update_postgres import real_auth_client, role_actor


def make_supplier(sessions):
    name = 'Supplier delete ' + uuid4().hex
    with sessions.begin() as db:
        row = Supplier(name=name, phone='saved', notes='keep')
        db.add(row); db.flush()
        return row.id, name


def headers(actor_id):
    return {'Authorization': f'Bearer {create_access_token(actor_id)}'}


def state(sessions, sid):
    with sessions() as db:
        row = db.get(Supplier, sid)
        values = None if row is None else (row.name, row.phone, row.notes)
        logs = db.query(AuditLog).filter_by(entity_type='Supplier', entity_id=sid, action='delete').order_by(AuditLog.id).all()
        return values, [(x.user_id, x.old_value_json, x.new_value_json) for x in logs]


def test_pg_supplier_delete_route_success_repeat_and_missing(customer_pg_sessions):
    sessions = customer_pg_sessions
    actor = role_actor(sessions, ['storage.suppliers'])
    sid, name = make_supplier(sessions)
    with real_auth_client(sessions) as client:
        result = client.delete(f'/suppliers/{sid}', headers=headers(actor))
        assert result.status_code == 204 and result.content == b''
        for target in (sid, 2147483647):
            missing = client.delete(f'/suppliers/{target}', headers=headers(actor))
            assert missing.status_code == 404 and missing.json()['detail'] == 'Supplier not found'
    assert state(sessions, sid) == (None, [(actor, None, {'name': name})])
    chain(sessions)


def test_pg_supplier_delete_route_auth_denials(customer_pg_sessions):
    sessions = customer_pg_sessions
    actor = role_actor(sessions, ['sales.view'])
    sid, name = make_supplier(sessions)
    with real_auth_client(sessions) as client:
        assert client.delete(f'/suppliers/{sid}').status_code == 401
        assert client.delete(f'/suppliers/{sid}', headers=headers(actor)).status_code == 403
    assert state(sessions, sid) == ((name, 'saved', 'keep'), [])


def make_guard_refs(sessions, sid, kinds):
    marker = uuid4().hex
    with sessions.begin() as db:
        item = Item(sku='SD-'+marker, name='Owned item', category='accessory', unit='pc')
        db.add(item); db.flush()
        refs = {}
        if 'batch' in kinds:
            warehouse = Warehouse(name='SD-'+marker, type='fabric_storage')
            db.add(warehouse); db.flush()
            row = StockBatch(item_id=item.id, batch_no='SD-'+marker, supplier_id=sid, quantity=1, unit='pc', warehouse_id=warehouse.id)
            db.add(row); db.flush(); refs['batch'] = row.id
        if 'request' in kinds:
            request = PurchaseRequest(request_no='SD-'+marker)
            db.add(request); db.flush()
            row = PurchaseRequestLine(purchase_request_id=request.id, item_id=item.id, requested_quantity=1, unit='pc', preferred_supplier_id=sid)
            db.add(row); db.flush(); refs['request'] = row.id
        if 'order' in kinds:
            row = PurchaseOrder(po_no='SD-'+marker, supplier_id=sid)
            db.add(row); db.flush(); refs['order'] = row.id
        return refs


@pytest.mark.parametrize('kinds,expected', [
    pytest.param(('batch',), ('stock_batches',), id='batch'),
    pytest.param(('request',), ('stock_batches','purchase_request_lines'), id='request'),
    pytest.param(('order',), ('stock_batches','purchase_request_lines','purchase_orders'), id='order'),
    pytest.param(('batch','request','order'), ('stock_batches',), id='all'),
    pytest.param(('request','order'), ('stock_batches','purchase_request_lines'), id='request_and_order'),
])
def test_pg_supplier_guard_order_and_refusal(customer_pg_sessions, kinds, expected):
    sessions = customer_pg_sessions
    actor = role_actor(sessions, ['storage.suppliers'])
    sid, name = make_supplier(sessions)
    refs = make_guard_refs(sessions, sid, kinds)
    observed = []
    engine = sessions.kw['bind']
    def record(conn, cursor, statement, parameters, context, executemany):
        lower = statement.lower()
        if lower.lstrip().startswith('select'):
            for table in ('stock_batches','purchase_request_lines','purchase_orders'):
                if 'from '+table in lower: observed.append(table)
    event.listen(engine, 'before_cursor_execute', record)
    try:
        with real_auth_client(sessions) as client:
            result = client.delete(f'/suppliers/{sid}', headers=headers(actor))
    finally:
        event.remove(engine, 'before_cursor_execute', record)
    assert result.status_code == 409
    assert result.json()['detail'] == 'Supplier is linked to stock or purchasing records and cannot be deleted'
    assert tuple(observed) == expected
    assert state(sessions, sid) == ((name, 'saved', 'keep'), [])
    with sessions() as db:
        for kind, cls, field in [('batch',StockBatch,'supplier_id'),('request',PurchaseRequestLine,'preferred_supplier_id'),('order',PurchaseOrder,'supplier_id')]:
            if kind in refs: assert getattr(db.get(cls, refs[kind]), field) == sid


@pytest.mark.parametrize('point', ['audit_enqueue','audit_finalize','before_commit'])
def test_pg_supplier_delete_failure_rolls_back_then_retry(customer_pg_sessions, monkeypatch, point):
    sessions = customer_pg_sessions
    actor = role_actor(sessions, ['storage.suppliers'])
    sid, name = make_supplier(sessions)
    original = partners_service.log_action
    reached = []
    def fail(*args, **kwargs): raise RuntimeError('injected supplier delete failure')
    def wrapped(db, user, action, entity_type, entity_id, **kwargs):
        entry = original(db, user, action, entity_type, entity_id, **kwargs)
        reached.append(entity_id)
        if point == 'audit_enqueue': fail()
        if point == 'before_commit': event.listen(db, 'before_commit', fail)
        return entry
    with monkeypatch.context() as patch:
        patch.setattr(partners_service, 'log_action', wrapped)
        if point == 'audit_finalize': patch.setattr(audit_service, 'add_audit_log_rows', fail)
        with real_auth_client(sessions) as client:
            assert client.delete(f'/suppliers/{sid}', headers=headers(actor)).status_code == 500
    assert reached == [sid] and state(sessions, sid) == ((name, 'saved', 'keep'), [])
    with real_auth_client(sessions) as client:
        assert client.delete(f'/suppliers/{sid}', headers=headers(actor)).status_code == 204
    assert state(sessions, sid) == (None, [(actor, None, {'name': name})])
    chain(sessions)


def test_pg_supplier_distinct_deletes_keep_audit_chain(customer_pg_sessions):
    sessions = customer_pg_sessions
    actor_id = role_actor(sessions, ['storage.suppliers'])
    pairs = [make_supplier(sessions) for _ in range(4)]
    barrier = Barrier(4)
    def worker(sid):
        with sessions() as db:
            actor = db.get(User, actor_id)
            barrier.wait(timeout=10)
            partners_service.delete_supplier(actor, db, sid)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(worker, sid) for sid, _ in pairs]
        for future in futures: future.result(timeout=30)
    for sid, name in pairs:
        assert state(sessions, sid) == (None, [(actor_id, None, {'name': name})])
    chain(sessions)


def test_pg_unguarded_order_line_fk_blocks_delete_then_retry(customer_pg_sessions, monkeypatch):
    sessions = customer_pg_sessions
    sid, name = make_supplier(sessions)
    marker = uuid4().hex
    with sessions.begin() as db:
        item = Item(sku='SL-'+marker, name='Owned item', category='accessory', unit='pc')
        order = PurchaseOrder(po_no='SL-'+marker, supplier_id=None)
        db.add_all([item,order]); db.flush()
        line = PurchaseOrderLine(purchase_order_id=order.id, item_id=item.id, unit='pc', ordered_quantity=1, supplier_id=sid)
        db.add(line); db.flush(); line_id = line.id
    with sessions() as db:
        rows = db.execute(text("""SELECT c.conname,c.confdeltype,c.condeferrable,c.condeferred
          FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid
          JOIN pg_namespace n ON n.oid=t.relnamespace
          JOIN pg_attribute a ON a.attrelid=t.oid AND a.attnum=ANY(c.conkey)
          WHERE n.nspname=current_schema() AND t.relname='purchase_order_lines'
          AND c.contype='f' AND a.attname='supplier_id' AND c.confrelid='suppliers'::regclass""")).all()
        assert len(rows)==1
        constraint, action, deferrable, deferred = rows[0]
        assert action=='a' and not deferrable and not deferred
    calls=[]; returned=[]; original=partners_service.log_action
    def observe(db, *args, **kwargs):
        calls.append(True); result=original(db, *args, **kwargs); returned.append(True); return result
    with monkeypatch.context() as patch:
        patch.setattr(partners_service, 'log_action', observe)
        with sessions() as db:
            with pytest.raises(IntegrityError) as failure: partners_service.delete_supplier(None, db, sid)
            assert failure.value.orig.pgcode=='23503' and failure.value.orig.diag.constraint_name==constraint
            db.rollback()
    assert calls == [True] and returned == []
    assert state(sessions, sid) == ((name, 'saved', 'keep'), [])
    with sessions.begin() as db:
        line = db.get(PurchaseOrderLine, line_id)
        assert line.supplier_id == sid
        db.delete(line)  # remove only our own blocking test reference
    with sessions() as db: partners_service.delete_supplier(None, db, sid)
    assert state(sessions, sid) == (None, [(None, None, {'name': name})])
    chain(sessions)


def test_pg_supplier_four_foreign_keys_have_migrated_constraints(customer_pg_sessions):
    expected = {('stock_batches','supplier_id'), ('purchase_request_lines','preferred_supplier_id'),
                ('purchase_orders','supplier_id'), ('purchase_order_lines','supplier_id')}
    with customer_pg_sessions() as db:
        rows = db.execute(text("""SELECT t.relname,a.attname,c.confdeltype,c.condeferrable,c.condeferred
          FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid
          JOIN pg_namespace n ON n.oid=t.relnamespace
          JOIN pg_attribute a ON a.attrelid=t.oid AND a.attnum=ANY(c.conkey)
          WHERE n.nspname=current_schema() AND c.contype='f'
          AND c.confrelid='suppliers'::regclass""")).all()
        assert {(r[0],r[1]) for r in rows} == expected
        assert len(rows) == 4 and all(r[2:] == ('a',False,False) for r in rows)


def test_pg_order_commits_after_guards_before_supplier_flush(customer_pg_sessions, monkeypatch):
    sessions = customer_pg_sessions
    sid, name = make_supplier(sessions)
    guards_passed, order_finished = Event(), Event()
    original = partners_service.log_action
    def pause(db, *args, **kwargs):
        guards_passed.set()
        assert order_finished.wait(10), 'order did not finish'
        return original(db, *args, **kwargs)
    def deletion():
        with sessions() as db:
            try:
                partners_service.delete_supplier(None, db, sid)
            except IntegrityError as failure:
                db.rollback()
                return failure.orig.pgcode
            raise AssertionError('delete succeeded with committed supplier reference')
    def insertion():
        assert guards_passed.wait(10), 'delete did not reach post-guard checkpoint'
        try:
            with sessions.begin() as db:
                order = PurchaseOrder(po_no='RACE-'+uuid4().hex, supplier_id=sid)
                db.add(order); db.flush(); oid=order.id
            return oid
        finally:
            order_finished.set()
    monkeypatch.setattr(partners_service, 'log_action', pause)
    with ThreadPoolExecutor(max_workers=2) as pool:
        delete_future=pool.submit(deletion); order_future=pool.submit(insertion)
        oid=order_future.result(timeout=25)
        assert delete_future.result(timeout=25)=='23503'
    assert state(sessions, sid)==((name, 'saved', 'keep'), [])
    with sessions() as db:
        assert db.get(PurchaseOrder, oid).supplier_id==sid
    chain(sessions)
