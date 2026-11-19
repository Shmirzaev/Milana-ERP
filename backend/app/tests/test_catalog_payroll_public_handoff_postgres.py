"""Present-key Catalog public writes followed by Payroll public options on PostgreSQL."""
from copy import deepcopy
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.routes.catalog import router as catalog_router
from app.api.routes.payroll import router as payroll_router
from app.core.deps import get_db
from app.core.security import create_access_token
from app.models import audit_service
from app.models.paid_operations_service import filter_paid_operations_for_factory
from app.schemas import AuditLog, Bundle, Department, Model, ProductionOrder, Role, User
from app.tests.test_model_approval_persistence_postgres import seed
from app.tests.test_modelsize_create_postgres import pg_sessions as pg_sessions  # noqa: F401
from app.tests.test_paid_operation_factory_scope import _operation


def _public_rows(db):
    tables = db.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")).scalars().all()
    result = {}
    for table in tables:
        quoted = db.get_bind().dialect.identifier_preparer.quote(table)
        result[table] = db.execute(text(f"SELECT row_to_json(t)::text FROM public.{quoted} AS t ORDER BY 1")).scalars().all()
    return result


def test_catalog_present_key_public_writes_then_payroll_read(pg_sessions):  # noqa: F811
    _, ids, control_id, key = seed(pg_sessions.kw['bind'])
    suffix = uuid4().hex[:10].upper()
    milana = _operation(f'MIL-{suffix}', 'milana')
    besttex = _operation(f'BST-{suffix}', 'besttex')
    saved = _operation(f'SAVED-{suffix}', 'milana')
    with pg_sessions.begin() as db:
        department = db.query(Department).filter_by(code='MIL').first()
        if department is None:
            department = Department(code='MIL', name='Milana')
            db.add(department)
            db.flush()
        sewing = Role(name=f'Sewing {suffix}', permissions=['modeling.models'])
        payroll = Role(name=f'Payroll {suffix}', permissions=['payroll.view'])
        denied = Role(name=f'Denied {suffix}', permissions=[])
        db.add_all([sewing, payroll, denied])
        db.flush()
        writer = User(name='Writer', email=f'writer-{suffix}@example.invalid', password_hash='unused', role_id=sewing.id, department_id=department.id, factory_code='MIL', is_active=True)
        mil = User(name='MIL reader', email=f'mil-{suffix}@example.invalid', password_hash='unused', role_id=payroll.id, factory_code='MIL', is_active=True)
        bst = User(name='BST reader', email=f'bst-{suffix}@example.invalid', password_hash='unused', role_id=payroll.id, factory_code='BST', is_active=True)
        blocked = User(name='Denied', email=f'denied-{suffix}@example.invalid', password_hash='unused', role_id=denied.id, factory_code='MIL', is_active=True)
        db.add_all([writer, mil, bst, blocked])
        for mid in ids:
            row = db.get(Model, mid)
            details = deepcopy(row.details_json)
            details['paid_operations'] = [milana, besttex]
            row.details_json = details
        for factory in ('MIL', 'BST'):
            order = ProductionOrder(production_no=f'{factory}-PUB-{suffix}', production_type='branded_stock', model_id=ids[0], status='new', planned_quantity=10)
            db.add(order)
            db.flush()
            db.add(Bundle(bundle_no=f'{factory}-PB-{suffix}', barcode=f'{factory}-PBAR-{suffix}', production_order_id=order.id, model_id=ids[0], color='test', size='M', quantity=10, sewing_factory_code=factory, status='created'))
        db.flush()
        writer_id, mil_id, bst_id, blocked_id = writer.id, mil.id, bst.id, blocked.id
        control_before = deepcopy(db.get(Model, control_id).details_json)
    app = FastAPI()
    app.include_router(catalog_router)
    app.include_router(payroll_router)

    def isolated_db():
        with pg_sessions() as db:
            yield db

    app.dependency_overrides[get_db] = isolated_db
    def headers(uid):
        return {'Authorization': f'Bearer {create_access_token(uid)}'}

    with TestClient(app) as client:
        with pg_sessions() as db:
            model = db.get(Model, ids[0])
            incoming = {'code': model.code, 'name': 'Updated '+key, 'details_json': {'general': deepcopy(model.details_json['general']), 'paid_operations': [milana]}}
        with pg_sessions() as db:
            before_denied = _public_rows(db)
        denied_response = client.patch(f'/models/{ids[0]}', headers=headers(blocked_id), json=incoming)
        assert denied_response.status_code == 403
        with pg_sessions() as db:
            assert _public_rows(db) == before_denied
        updated = client.patch(f'/models/{ids[0]}', headers=headers(writer_id), json=incoming)
        assert updated.status_code == 200, updated.text
        result = client.patch(f'/models/{ids[0]}/paid-operations', headers=headers(writer_id), json={'sewing_factory': 'milana', 'paid_operations': [saved]})
        assert result.status_code == 200, result.text
        with pg_sessions() as db:
            for mid in ids:
                details = db.get(Model, mid).details_json
                assert filter_paid_operations_for_factory(details, 'besttex')['paid_operations'] == [besttex]
            assert db.get(Model, control_id).details_json == control_before
            audit_rows = db.query(AuditLog).filter(
                AuditLog.entity_type == 'Model', AuditLog.entity_id.in_(ids),
                AuditLog.action.in_(['update', 'update_paid_operations']),
            ).order_by(AuditLog.id).all()
            assert [(row.action, row.entity_id, row.user_id) for row in audit_rows] == [
                ('update', ids[0], writer_id),
                *[('update_paid_operations', mid, writer_id) for mid in sorted(ids)],
            ]
            assert all(row.entry_hash for row in audit_rows)
            assert audit_service.verify_audit_hash_chain(db)['ok']
            before_get = _public_rows(db)
        for uid, factory, expected, hidden in [(mil_id, 'MIL', saved['code'], besttex['code']), (bst_id, 'BST', besttex['code'], saved['code'])]:
            response = client.get('/payroll/reports/sewing-production/options', params={'factory_code': factory}, headers=headers(uid))
            assert response.status_code == 200, response.text
            codes = {row['value'] for row in response.json()['operations']}
            assert expected in codes and hidden not in codes
    with pg_sessions() as db:
        assert _public_rows(db) == before_get
