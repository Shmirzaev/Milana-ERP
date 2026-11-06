"""Item deletion against the approved, migrated PostgreSQL test target."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import object_session

from app.models import audit_service
from app.models.inventory import stock_service
from app.schemas import (
    AuditLog, ForecastRecommendation, Item, ManualAccessoryIssue,
    MaterialReservation, Model, ProductionOrder, Role, User, WasteRecord,
)
from app.tests.test_customer_create_postgres import customer_pg_sessions  # noqa: F401


def make_case(sessions, linked=False):
    marker = uuid4().hex
    with sessions.begin() as db:
        role = Role(name=f'delete-{marker}', permissions=['storage.items', 'inventory.force_override'])
        db.add(role)
        db.flush()
        actor = User(name='Delete actor', email=f'{marker}@example.invalid',
                     password_hash='unused', role_id=role.id, is_active=True)
        item = Item(sku=f'DEL-{marker}', name=f'Delete {marker}', category='fabric', unit='kg', is_active=True)
        db.add_all([actor, item])
        db.flush()
        waste_id = None
        if linked:
            waste = WasteRecord(item_id=item.id, waste_type='test', quantity=1, unit='kg')
            db.add(waste)
            db.flush()
            waste_id = waste.id
        return actor.id, item.id, waste_id


def audit_rows(db, item_id):
    return db.query(AuditLog).filter_by(entity_type='Item', entity_id=item_id).all()


@pytest.mark.parametrize('linked', [False, True])
def test_pg_delete_and_archive_share_session_and_preserve_audit(customer_pg_sessions, monkeypatch, linked):
    sessions = customer_pg_sessions
    actor_id, item_id, waste_id = make_case(sessions, linked)
    helper_name = 'archive_item' if linked else 'delete_item'
    helper = getattr(stock_service.item_persistence, helper_name)
    log_action = stock_service.log_action
    observed = []

    def observe_helper(db, item):
        assert object_session(item) is db
        observed.append(db)
        return helper(db, item)

    def observe_audit(db, *args, **kwargs):
        assert observed == [db]
        return log_action(db, *args, **kwargs)

    monkeypatch.setattr(stock_service.item_persistence, helper_name, observe_helper)
    monkeypatch.setattr(stock_service, 'log_action', observe_audit)
    with sessions() as db:
        assert stock_service.delete_item(db, item_id, db.get(User, actor_id), force=linked) is linked
    with sessions() as db:
        item = db.get(Item, item_id)
        if linked:
            assert item.is_active is False
            waste = db.get(WasteRecord, waste_id)
            assert (waste.item_id, waste.waste_type, waste.quantity, waste.unit) == (item_id, 'test', 1, 'kg')
        else:
            assert item is None
        audits = audit_rows(db, item_id)
        assert len(audits) == 1
        assert audits[0].action == ('force_archive' if linked else 'delete')
        assert audits[0].user_id == actor_id and audits[0].entry_hash
        if linked:
            assert audits[0].new_value_json == {'is_active': False, 'linked_records_preserved': True}


@pytest.mark.parametrize('linked', [False, True])
def test_pg_actual_audit_finalization_failure_rolls_back(customer_pg_sessions, monkeypatch, linked):
    sessions = customer_pg_sessions
    actor_id, item_id, waste_id = make_case(sessions, linked)
    finalize = audit_service._finalize_postgres_audits
    observed = []

    def fail_after_finalize(db):
        finalize(db)
        db.flush()
        rows = audit_rows(db, item_id)
        assert len(rows) == 1 and rows[0].entry_hash
        observed.append(True)
        raise RuntimeError('injected after actual audit finalization')

    monkeypatch.setattr(audit_service, '_finalize_postgres_audits', fail_after_finalize)
    with sessions() as db:
        with pytest.raises(RuntimeError, match='injected after actual audit finalization'):
            stock_service.delete_item(db, item_id, db.get(User, actor_id), force=linked)
        db.rollback()
    assert observed == [True]
    with sessions() as db:
        assert db.get(Item, item_id).is_active is True
        if linked:
            assert db.get(WasteRecord, waste_id).item_id == item_id
        assert audit_rows(db, item_id) == []


def add_direct_reference(sessions, item_id, kind):
    marker = uuid4().hex
    with sessions.begin() as db:
        if kind == 'forecast':
            row = ForecastRecommendation(item_id=item_id, recommendation_type='purchase', suggested_quantity=1)
        else:
            model = Model(code=f'M-{marker}', name='Model')
            db.add(model)
            db.flush()
            order = ProductionOrder(production_no=f'PO-{marker}', production_type='branded_stock', model_id=model.id)
            db.add(order)
            db.flush()
            if kind == 'reservation':
                row = MaterialReservation(reservation_no=f'R-{marker}', production_order_id=order.id,
                                          item_id=item_id, reserved_quantity=1, unit='kg')
            else:
                row = ManualAccessoryIssue(production_order_id=order.id, item_id=item_id,
                                           item_name='Item', quantity=1, unit='kg')
        db.add(row)
        db.flush()
        return type(row), row.id


@pytest.mark.parametrize('kind', ['reservation', 'manual_issue', 'forecast'])
@pytest.mark.parametrize('force', [False, True])
def test_pg_unchecked_direct_reference_rejects_delete_atomically(customer_pg_sessions, kind, force):
    sessions = customer_pg_sessions
    actor_id, item_id, _ = make_case(sessions)
    row_type, row_id = add_direct_reference(sessions, item_id, kind)
    with sessions() as db:
        with pytest.raises(IntegrityError):
            stock_service.delete_item(db, item_id, db.get(User, actor_id), force=force)
        db.rollback()
    with sessions() as db:
        assert db.get(Item, item_id).is_active is True
        assert db.get(row_type, row_id).item_id == item_id
        assert audit_rows(db, item_id) == []


def test_pg_reference_insert_after_link_check_rolls_back_delete(customer_pg_sessions, monkeypatch):
    sessions = customer_pg_sessions
    actor_id, item_id, _ = make_case(sessions)
    checked, resume = Event(), Event()
    log_action = stock_service.log_action

    def pause_after_link_check(db, *args, **kwargs):
        checked.set()
        if not resume.wait(10):
            raise TimeoutError('reference insertion did not finish')
        return log_action(db, *args, **kwargs)

    def delete():
        with sessions() as db:
            try:
                stock_service.delete_item(db, item_id, db.get(User, actor_id))
            except IntegrityError:
                db.rollback()
                return 'fk_rejected'
            return 'deleted'

    monkeypatch.setattr(stock_service, 'log_action', pause_after_link_check)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(delete)
        try:
            assert checked.wait(10), 'delete did not reach post-check point'
            with sessions.begin() as db:
                waste = WasteRecord(item_id=item_id, waste_type='race', quantity=1, unit='kg')
                db.add(waste)
                db.flush()
                waste_id = waste.id
        finally:
            resume.set()
        assert future.result(timeout=15) == 'fk_rejected'
    with sessions() as db:
        assert db.get(Item, item_id).is_active is True
        assert db.get(WasteRecord, waste_id).item_id == item_id
        assert audit_rows(db, item_id) == []
