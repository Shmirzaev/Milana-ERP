"""Signed model deletion on an explicitly approved migrated PostgreSQL fixture."""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.models import audit_service
from app.schemas import AuditLog, Model, ModelImage
from app.schemas.catalog.catalog import Brand, Collection, CollectionModel
from app.schemas.planning.forecasting import ForecastRecommendation
from app.tests.test_model_create_commit_postgres import app_for, headers

pytest_plugins = ('app.tests.test_modelcolor_create_postgres',)


def seed(sessions, scope='standard', forecast=False):
    token = uuid4().hex
    with sessions.begin() as db:
        model = Model(code=f'DEL{token}', name='Delete fixture', catalog_scope=scope,
                      factory_code='ECO' if scope == 'usluga' else None)
        brand = Brand(name=f'Delete {token}')
        db.add_all([model, brand]); db.flush()
        collection = Collection(brand_id=brand.id, name='Delete fixture')
        db.add(collection); db.flush()
        link = CollectionModel(collection_id=collection.id, model_id=model.id)
        db.add_all([link, ModelImage(model_id=model.id, file_url='/fixture')])
        if forecast:
            db.add(ForecastRecommendation(model_id=model.id, recommendation_type='test', suggested_quantity=1))
        db.flush()
        return model.id, link.id, collection.id


def state(sessions, mid):
    with sessions() as db:
        return (db.get(Model, mid) is not None,
                db.query(CollectionModel).filter_by(model_id=mid).count(),
                db.query(ModelImage).filter_by(model_id=mid).count(),
                db.query(AuditLog).filter_by(entity_type='Model', entity_id=mid, action='delete').count())


@pytest.mark.parametrize(('scope', 'path', 'actor'), [
    ('standard', '/api/models', 'standard'), ('usluga', '/api/usluga/models', 'eco'),
])
def test_pg_signed_delete_scope_and_retained_readback(pg_sessions, pg_case, scope, path, actor):
    mid, link_id, collection_id = seed(pg_sessions, scope)
    with pg_sessions() as retained:
        parent = retained.get(Model, mid)
        link = retained.get(CollectionModel, link_id)
        collection = retained.get(Collection, collection_id)
        assert parent and link and collection
        with TestClient(app_for(pg_sessions), raise_server_exceptions=False) as client:
            assert client.delete(f'{path}/{mid}').status_code == 401
            assert client.delete(f'{path}/{mid}', headers=headers(pg_case['actors']['denied'])).status_code == 403
            if scope == 'usluga':
                assert client.delete(f'{path}/{mid}', headers=headers(pg_case['actors']['wrong_factory'])).status_code == 403
                assert client.delete(f'/api/models/{mid}', headers=headers(pg_case['actors']['standard'])).status_code == 404
            else:
                assert client.delete(f'/api/usluga/models/{mid}', headers=headers(pg_case['actors']['eco'])).status_code == 404
            assert state(pg_sessions, mid) == (True, 1, 1, 0)
            response = client.delete(f'{path}/{mid}', headers=headers(pg_case['actors'][actor]))
            assert response.status_code == 204, response.text
        # A separately loaded instance remains stale until expiration; the bulk delete
        # uses synchronize_session=False, and the collection parent remains intact.
        assert link.model_id == mid and parent.id == mid and collection.id == collection_id
        retained.expire_all()
        assert retained.get(Model, mid) is None
        assert retained.get(CollectionModel, link_id) is None
        assert retained.get(Collection, collection_id) is not None
    assert state(pg_sessions, mid) == (False, 0, 0, 1)


def test_pg_signed_delete_unguarded_forecast_fk_rollback(pg_sessions, pg_case):
    mid, _, _ = seed(pg_sessions, forecast=True)
    with TestClient(app_for(pg_sessions), raise_server_exceptions=False) as client:
        response = client.delete(f'/api/models/{mid}', headers=headers(pg_case['actors']['standard']))
        assert response.status_code == 500
    assert state(pg_sessions, mid) == (True, 1, 1, 0)
    with pg_sessions() as db:
        assert db.query(ForecastRecommendation).filter_by(model_id=mid).count() == 1


@pytest.mark.parametrize('fault', ['audit', 'commit'])
def test_pg_signed_delete_finalization_and_deferred_commit_rollback_retry(pg_sessions, pg_case, monkeypatch, fault):
    mid, _, _ = seed(pg_sessions)
    engine = pg_sessions.kw['bind']
    suffix = uuid4().hex[:12]
    trigger, function = f'pr401_guard_{suffix}', f'pr401_abort_{suffix}'
    observed = []
    original = audit_service._finalize_postgres_audits
    def fail_after_finalization(db):
        original(db)
        assert db.query(AuditLog).filter_by(entity_type='Model', entity_id=mid, action='delete').count() == 1
        observed.append('finalized')
        raise RuntimeError('injected after audit finalization')
    def capture(context):
        exc = context.original_exception
        if getattr(exc, 'pgcode', None) == '23514':
            observed.append((context.statement, exc.diag.constraint_name))
    if fault == 'commit':
        try:
            with engine.begin() as conn:
                conn.exec_driver_sql(f"""CREATE FUNCTION {function}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
                    RAISE EXCEPTION 'fixture commit failure' USING ERRCODE = '23514', CONSTRAINT = '{trigger}'; END; $$""")
                conn.exec_driver_sql(f"""CREATE CONSTRAINT TRIGGER {trigger} AFTER DELETE ON models
                    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (OLD.id = {int(mid)})
                    EXECUTE FUNCTION {function}()""")
            event.listen(engine, 'handle_error', capture)
        except Exception as exc:
            raise RuntimeError(f'HOLD: uncertain fixture setup; inspect {function} and {trigger} before cleanup or retry') from exc
    try:
        with monkeypatch.context() as patch:
            if fault == 'audit':
                patch.setattr(audit_service, '_finalize_postgres_audits', fail_after_finalization)
            with TestClient(app_for(pg_sessions), raise_server_exceptions=False) as client:
                response = client.delete(f'/api/models/{mid}', headers=headers(pg_case['actors']['standard']))
        assert response.status_code == 500
        assert observed == (['finalized'] if fault == 'audit' else [(None, trigger)])
        assert state(pg_sessions, mid) == (True, 1, 1, 0)
    finally:
        if fault == 'commit':
            event.remove(engine, 'handle_error', capture)
            with engine.begin() as conn:
                conn.exec_driver_sql(f'DROP TRIGGER {trigger} ON models')
                conn.exec_driver_sql(f'DROP FUNCTION {function}()')
    with TestClient(app_for(pg_sessions), raise_server_exceptions=False) as client:
        response = client.delete(f'/api/models/{mid}', headers=headers(pg_case['actors']['standard']))
        assert response.status_code == 204, response.text
    assert state(pg_sessions, mid) == (False, 0, 0, 1)


GUARDS = ('sales orders', 'production orders', 'production order items', 'bundles',
          'packages', 'package items', 'finished goods stock')


def add_references(sessions, mid, kinds):
    """Use a different parent model so each guard can be observed independently."""
    from app.schemas import (Bundle, FinishedGoodsStock, Package, PackageItem,
                             ProductionOrder, ProductionOrderItem, SalesOrder, SalesOrderItem)
    token = uuid4().hex
    with sessions.begin() as db:
        parent_model = Model(code=f'PARENT{token}', name='Reference parent', catalog_scope='standard')
        db.add(parent_model); db.flush()
        order = ProductionOrder(production_no=f'PO{token}', production_type='branded_stock',
                                model_id=mid if 'production orders' in kinds else parent_model.id)
        sales = SalesOrder(order_no=f'SO{token}')
        db.add_all([order, sales]); db.flush()
        if 'sales orders' in kinds:
            db.add(SalesOrderItem(sales_order_id=sales.id, model_id=mid, color='white', size='M', quantity=1))
        if 'production order items' in kinds:
            db.add(ProductionOrderItem(production_order_id=order.id, model_id=mid, color='white', size='M', planned_quantity=1))
        if 'bundles' in kinds:
            db.add(Bundle(bundle_no=f'B{token}', barcode=f'B{token}', production_order_id=order.id,
                          model_id=mid, color='white', size='M', quantity=1))
        if {'packages', 'package items'} & set(kinds):
            package = Package(package_no=f'PK{token}', barcode=f'PK{token}', production_order_id=order.id,
                              model_id=mid if 'packages' in kinds else parent_model.id, color='white')
            db.add(package); db.flush()
            if 'package items' in kinds:
                db.add(PackageItem(package_id=package.id, model_id=mid, color='white', size='M', quantity=1))
        if 'finished goods stock' in kinds:
            db.add(FinishedGoodsStock(model_id=mid, color='white', size='M', quantity=1, available_qty=1))


@pytest.mark.parametrize('kind', [*GUARDS, 'all'])
def test_pg_signed_delete_real_reference_guards_in_order(pg_sessions, pg_case, kind):
    mid, _, _ = seed(pg_sessions)
    kinds = GUARDS if kind == 'all' else (kind,)
    add_references(pg_sessions, mid, kinds)
    with TestClient(app_for(pg_sessions), raise_server_exceptions=False) as client:
        response = client.delete(f'/api/models/{mid}', headers=headers(pg_case['actors']['standard']))
    assert response.status_code == 409, response.text
    assert response.json()['detail'] == f"Model is in use by: {', '.join(kinds)}"
    assert state(pg_sessions, mid) == (True, 1, 1, 0)


def test_pg_delete_blocks_concurrent_sales_reference_then_fk_refuses(pg_sessions, pg_case, monkeypatch):
    """A reference attempted after the deletion lock cannot survive a committed delete."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from time import monotonic, sleep
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError
    from app.models.catalog import models_service
    from app.schemas import SalesOrder, SalesOrderItem

    mid, _, _ = seed(pg_sessions)
    with pg_sessions.begin() as db:
        order = SalesOrder(order_no=f'RACE{uuid4().hex}')
        db.add(order); db.flush(); order_id = order.id
    locked, release, inserting = Event(), Event(), Event()
    pids = {}
    original = models_service.delete_checked_model

    def lock_deleted_model(db, model):
        original(db, model)
        db.flush()
        pids['delete'] = db.scalar(text('select pg_backend_pid()'))
        locked.set()
        if not release.wait(20):
            raise RuntimeError('HOLD: delete lock barrier timed out')

    def delete_request():
        with TestClient(app_for(pg_sessions), raise_server_exceptions=False) as client:
            return client.delete(f'/api/models/{mid}', headers=headers(pg_case['actors']['standard'])).status_code

    def insert_reference():
        with pg_sessions() as db:
            pids['insert'] = db.scalar(text('select pg_backend_pid()'))
            db.add(SalesOrderItem(sales_order_id=order_id, model_id=mid, color='white', size='M', quantity=1))
            inserting.set()
            try:
                db.commit()
            except IntegrityError as exc:
                db.rollback()
                return getattr(exc.orig, 'pgcode', None)
            return 'committed'

    monkeypatch.setattr(models_service, 'delete_checked_model', lock_deleted_model)
    with ThreadPoolExecutor(max_workers=2) as pool:
        deleting = pool.submit(delete_request)
        try:
            assert locked.wait(10), 'HOLD: delete did not acquire its expected row lock'
            inserting_future = pool.submit(insert_reference)
            assert inserting.wait(10), 'HOLD: reference insert did not start'
            deadline = monotonic() + 10
            with pg_sessions() as observer:
                while monotonic() < deadline:
                    blockers = observer.scalar(text('select pg_blocking_pids(:pid)'), {'pid': pids['insert']})
                    if pids['delete'] in blockers:
                        break
                    sleep(0.05)
                else:
                    pytest.fail('HOLD: expected owned delete PID was not observed blocking insert')
        finally:
            release.set()
        assert deleting.result(timeout=20) == 204
        assert inserting_future.result(timeout=20) == '23503'
    with pg_sessions() as db:
        assert db.get(Model, mid) is None
        assert db.query(SalesOrderItem).filter_by(model_id=mid).count() == 0
        assert db.query(AuditLog).filter_by(entity_type='Model', entity_id=mid, action='delete').count() == 1
