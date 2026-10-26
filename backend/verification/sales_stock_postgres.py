"""Independent real-PG behavior baseline for the unfinished Sales boundary."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from app.core.security import create_access_token
from app.db.base import Base
from app.db.session import get_db
from app.db import session as session_module
from app.main import app
from app.models.audit_service import verify_audit_hash_chain
from app.schemas import (AuditLog, Department, FinishedGoodsStock, IdempotencyRecord,
    LegacyStockReceipt, Model, Notification, Package, PackageItem, Role,
    SalesOrder, SalesOrderItem, StockReservation, Task, User)

database_name = os.environ['REVIEW_SALES_DATABASE']
assert database_name.startswith('review_sales_operation_')
engine = create_engine(os.environ['DATABASE_URL'], pool_size=6, max_overflow=2,
    connect_args={'options': '-c statement_timeout=15000 -c lock_timeout=10000'})
Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture(scope='module', autouse=True)
def owned_database():
    assert engine.dialect.name == 'postgresql'
    with engine.connect() as connection:
        assert connection.scalar(text('SELECT current_database()')) == database_name
    Base.metadata.create_all(engine)
    previous = app.dependency_overrides.get(get_db)

    def db_dependency():
        with Session() as db:
            yield db

    app.dependency_overrides[get_db] = db_dependency
    yield
    if previous is None:
        app.dependency_overrides.pop(get_db, None)
    else:
        app.dependency_overrides[get_db] = previous
    engine.dispose()
    session_module.engine.dispose()


@pytest.fixture
def case(owned_database):
    with engine.begin() as connection:
        assert connection.scalar(text('SELECT current_database()')) == database_name
        names = [engine.dialect.identifier_preparer.format_table(t) for t in Base.metadata.tables.values()]
        connection.exec_driver_sql('TRUNCATE ' + ', '.join(names) + ' RESTART IDENTITY CASCADE')
    with Session() as db:
        admin_role = Role(name='Super Admin', permissions=['*', 'admin.super'])
        viewer_role = Role(name='Review viewer', permissions=['sales.view'])
        fgs = Department(code='FGS', name='Review finished goods')
        pln = Department(code='PLN', name='Review planning')
        model = Model(code='REVIEW-SALES-MODEL', name='Review sales model',
                      status='approved', selling_price=2)
        db.add_all([admin_role, viewer_role, fgs, pln, model])
        db.flush()
        users = {}
        for name, role, department in [('admin', admin_role, None),
                ('viewer', viewer_role, None), ('storage', viewer_role, fgs.id),
                ('planner', viewer_role, pln.id)]:
            user = User(name=name, email=name+'@review.invalid',
                        password_hash='unused-test-fixture', role_id=role.id,
                        factory_code='MIL', department_id=department, is_active=True)
            db.add(user)
            users[name] = user
        db.commit()
        result = {'model': model.id, 'user_id': users['admin'].id}
        for name, user in users.items():
            result[name] = {'Authorization': 'Bearer '+create_access_token(user.id, {'factory_code':'MIL'})}
    from app.core.shared_store import reset_shared_counter_store_for_tests
    reset_shared_counter_store_for_tests()
    return result


def seed_stock(case, *, packaged=False, quantity=20):
    with Session() as db:
        package_id = None
        if packaged:
            receipt = LegacyStockReceipt(source_system='REVIEW', source_warehouse_id='review',
                source_record_id='review-pack', source_checksum='0'*64, source_payload={'synthetic':True})
            db.add(receipt)
            db.flush()
            package = Package(package_no='REVIEW-PACK', barcode='REVIEW-PACK',
                legacy_receipt_id=receipt.id, model_id=case['model'], color='white',
                total_quantity=quantity, capacity=60, status='received_in_storage')
            db.add(package)
            db.flush()
            package_id = package.id
        for size, qty in ([('M', quantity//2), ('L', quantity-quantity//2)] if packaged else [('M',quantity)]):
            if packaged:
                db.add(PackageItem(package_id=package_id, model_id=case['model'], color='white', size=size, quantity=qty))
            db.add(FinishedGoodsStock(package_id=package_id, model_id=case['model'],
                color='white', size=size, quantity=qty, available_qty=qty,
                reserved_qty=0, sold_qty=0, status='available', cost_per_piece=1, selling_price=2))
        db.commit()
    return package_id


def payload(case, *, mode='partial', quantity=12):
    line = {'model_id':case['model'], 'color':'white', 'size':'M',
            'source_type':'from_stock', 'unit_price':2}
    if mode == 'pack-count':
        line.update(color='mixed', size='any', requested_pack_count=1)
    else:
        line['quantity'] = quantity
        if mode == 'whole-pack':
            line['size'] = 'any'
    return {'order_type':'branded_stock_sale', 'items':[line]}


def post(case, body, *, viewer=False):
    client = TestClient(app)
    try:
        return client.post('/api/sales-orders', headers=case['viewer' if viewer else 'admin'], json=body)
    finally:
        client.close()


def participant_counts():
    with Session() as db:
        return {model.__tablename__:db.query(model).count() for model in
            (SalesOrder, SalesOrderItem, StockReservation, AuditLog, Notification, Task, IdempotencyRecord)}


def stock_totals():
    with Session() as db:
        rows = db.query(FinishedGoodsStock).order_by(FinishedGoodsStock.id).all()
        for row in rows:
            assert row.quantity == row.available_qty + row.reserved_qty + row.sold_qty
        return sum(row.available_qty for row in rows), sum(row.reserved_qty for row in rows)


def assert_one_order(case, *, quantity, stock_count):
    with Session() as db:
        order = db.query(SalesOrder).one()
        assert order.order_type == 'branded_stock_sale' and order.status == 'ready'
        assert len(order.items) == 1 and order.items[0].quantity == quantity
        assert float(order.total_amount) == quantity*2
        reservations = db.query(StockReservation).all()
        assert len(reservations) == stock_count
        assert sum(row.quantity for row in reservations) == quantity
        assert {row.sales_order_id for row in reservations} == {order.id}
        assert db.query(AuditLog).count() == 2
        assert {row.action for row in db.query(AuditLog)} == {'create','reserve_stock_auto'}
        assert db.query(Notification).count() == 1
        assert verify_audit_hash_chain(db)['ok'] is True


@pytest.mark.parametrize('mode', ['partial','whole-pack','pack-count'])
def test_real_pg_create_preserves_each_allocation_mode(case, mode):
    packaged = mode != 'partial'
    seed_stock(case, packaged=packaged, quantity=6 if packaged else 20)
    response = post(case, payload(case, mode=mode, quantity=6 if packaged else 12))
    assert response.status_code == 201, response.text
    assert response.json()['status'] == 'ready'
    assert response.json()['items'][0]['source_type'] == 'from_stock'
    assert_one_order(case, quantity=6 if packaged else 12, stock_count=2 if packaged else 1)
    assert stock_totals() == ((0,6) if packaged else (8,12))


@pytest.mark.parametrize('order_type, expected', [('branded_stock',400),('unknown',422)])
def test_known_forbidden_and_unknown_order_types_remain_distinct(case, order_type, expected):
    seed_stock(case)
    body = payload(case)
    body['order_type'] = order_type
    before = participant_counts()
    response = post(case, body)
    assert response.status_code == expected, response.text
    assert participant_counts() == before
    assert stock_totals() == (20,0)


def test_real_http_permission_refusal_leaves_all_participants_unchanged(case):
    seed_stock(case)
    before = participant_counts()
    response = post(case, payload(case), viewer=True)
    assert response.status_code == 403, response.text
    assert participant_counts() == before
    assert stock_totals() == (20,0)


@pytest.mark.parametrize('table', ['stock_reservations','notifications','audit_logs'])
def test_failure_after_actual_insert_rolls_back_stock_and_all_effects_then_retries(case, table):
    seed_stock(case)
    before = participant_counts()
    observed = []

    def fail_after_insert(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().lower().startswith('insert into '+table):
            observed.append(table)
            raise RuntimeError('review-after-actual-insert-'+table)

    event.listen(engine, 'after_cursor_execute', fail_after_insert)
    try:
        with pytest.raises(RuntimeError, match='review-after-actual-insert'):
            post(case, payload(case))
    finally:
        event.remove(engine, 'after_cursor_execute', fail_after_insert)
    assert observed == [table]
    assert participant_counts() == before
    assert stock_totals() == (20,0)
    response = post(case, payload(case))
    assert response.status_code == 201, response.text
    assert_one_order(case, quantity=12, stock_count=1)
    assert stock_totals() == (8,12)


def test_two_concurrent_creates_cannot_sell_the_same_available_pieces(case):
    seed_stock(case)
    start = Barrier(2)

    def attempt():
        start.wait(timeout=10)
        return post(case, payload(case))

    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(attempt) for _ in range(2)]
        responses = [f.result(timeout=35) for f in futures]
    assert sorted(r.status_code for r in responses) == [201,409], [(r.status_code,r.text) for r in responses]
    assert_one_order(case, quantity=12, stock_count=1)
    assert stock_totals() == (8,12)
    # This challenges actual concurrent HTTP creates and all final effects.
    # Numbering may serialize them before stock locking: it is not proof of
    # direct two-session stock-row lock contention.


"""Additional approved-seam tests, appended to the unchanged reviewer PG body.

Uses that body's owned database, fixtures and helpers. No production/QA DB writes.
"""


@pytest.mark.parametrize('mode', ['partial', 'pack-count'])
def test_direct_public_stock_calls_contend_without_sales_numbering_serialization(case, mode):
    from app.libs.enums.packaging import PackageStockKind
    from app.libs.types.stock_reservation import PackDemand, PieceDemand
    from app.models.fulfillment.stock_service import reserve_packs, reserve_pieces
    from fastapi import HTTPException
    seed_stock(case, packaged=mode == 'pack-count', quantity=6)
    with Session() as db:
        orders = [SalesOrder(order_no=f'DIRECT-{n}', order_type='branded_stock_sale', status='draft') for n in range(2)]
        db.add_all(orders)
        db.commit()
        ids = [order.id for order in orders]
    start = Barrier(2)

    def attempt(order_id):
        with Session() as db:
            # Distinct Sales order locks cannot serialize the two operations.
            db.query(SalesOrder).filter(SalesOrder.id == order_id).with_for_update(of=SalesOrder).one()
            start.wait(timeout=10)
            try:
                if mode == 'pack-count':
                    result = reserve_packs(db, sales_order_id=order_id, reserved_by=case['user_id'],
                                           demands=(PackDemand(str(order_id), case['model'], None, 1),))
                    assert result.piece_quantities_by_demand == {str(order_id): 6}
                else:
                    result = reserve_pieces(db, sales_order_id=order_id, reserved_by=case['user_id'],
                                            stock_kind=PackageStockKind.STANDARD,
                                            demands=(PieceDemand(case['model'], None, 'white', 'M', 4),),
                                            fail_on_shortage=True)
                    assert result.shortages == ()
                db.commit()
                return 200
            except HTTPException as exc:
                db.rollback()
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(attempt, order_id) for order_id in ids]
        codes = [future.result(timeout=35) for future in futures]
    assert sorted(codes) == [200, 409], codes
    assert stock_totals() == ((0, 6) if mode == 'pack-count' else (2, 4))
    with Session() as db:
        assert {order.status for order in db.query(SalesOrder)} == {'draft'}
        assert len({row.sales_order_id for row in db.query(StockReservation)}) == 1


@pytest.mark.parametrize('failure_table', ['tasks', 'notifications', 'audit_logs', 'idempotency_records', 'late_authorization'])
def test_shortage_task_and_idempotency_participants_rollback_then_replay(case, failure_table):
    from fastapi import HTTPException
    seed_stock(case, quantity=3)
    with Session() as db:
        order = SalesOrder(order_no='SHORTAGE-REPLAY', order_type='branded_stock_sale', status='draft', created_by=case['user_id'])
        db.add(order)
        db.flush()
        db.add(SalesOrderItem(sales_order_id=order.id, model_id=case['model'], color='white', size='M',
                              quantity=5, unit_price=2, source_type='from_stock'))
        db.commit()
        order_id = order.id
    before = participant_counts()
    observed = []
    target_table = 'idempotency_records' if failure_table == 'late_authorization' else failure_table
    def fail_after_insert(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().lower().startswith('insert into ' + target_table):
            observed.append(failure_table)
            if failure_table == 'late_authorization':
                raise HTTPException(403, 'review late authorization refusal')
            raise RuntimeError('approved-shortage-participant-' + failure_table)
    headers = dict(case['admin'], **{'Idempotency-Key': 'approved-sales-shortage-replay'})
    def reserve():
        with TestClient(app) as client:
            return client.post(f'/api/sales-orders/{order_id}/reserve-stock', headers=headers)
    event.listen(engine, 'after_cursor_execute', fail_after_insert)
    try:
        if failure_table == 'late_authorization':
            denied = reserve()
            assert denied.status_code == 403, denied.text
            assert denied.json()['detail'] == 'review late authorization refusal'
        else:
            with pytest.raises(RuntimeError, match='approved-shortage-participant-'):
                reserve()
    finally:
        event.remove(engine, 'after_cursor_execute', fail_after_insert)
    assert observed == [failure_table]
    assert participant_counts() == before
    assert stock_totals() == (3, 0)
    with Session() as db:
        assert db.get(SalesOrder, order_id).status == 'draft'
    response = reserve()
    assert response.status_code == 200, response.text
    assert response.json()['shortages'] == [{'model_id': case['model'], 'brand_id': None, 'color': 'white', 'size': 'M', 'shortage': 2}]
    assert sum(row['qty'] for row in response.json()['reservations']) == 3
    after = participant_counts()
    assert after['tasks'] == before['tasks'] + 1
    assert after['idempotency_records'] == before['idempotency_records'] + 1
    assert after['audit_logs'] == before['audit_logs'] + 1
    assert after['notifications'] == before['notifications'] + 2
    assert stock_totals() == (0, 3)
    with Session() as db:
        task = db.query(Task).one()
        planner = db.query(User).filter(User.name == 'planner').one()
        assert (task.title, task.status, task.priority, task.assigned_to, task.created_by) == (
            'Stock shortage for SHORTAGE-REPLAY', 'pending', 'high', planner.id, case['user_id'])
        assert task.description == f'Auto-created from reserve-stock. Resolve shortages: M{case["model"]} white/M: 2'
        assert task.due_date is None and task.entity_type is None and task.entity_id is None
        assert db.get(SalesOrder, order_id).status == 'reserved'
        assert verify_audit_hash_chain(db)['ok'] is True
    replay = reserve()
    assert replay.status_code == 200, replay.text
    assert replay.json() == response.json()
    assert participant_counts() == after
    assert stock_totals() == (0, 3)
