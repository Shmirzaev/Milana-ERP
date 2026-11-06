"""Real PostgreSQL Usluga paid-operation permissions and persistence."""
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.usluga import router
from app.core.deps import get_db
from app.core.security import create_access_token
from app.models import audit_service
from app.schemas import AuditLog, Model, Role, User
from app.tests.test_modelsize_create_postgres import pg_sessions as pg_sessions  # noqa: F401
from app.tests.test_paid_operation_factory_scope import _operation


def test_usluga_paid_operations_auth_and_persistence(pg_sessions):  # noqa: F811
    suffix = uuid4().hex[:10]
    with pg_sessions.begin() as db:
        roles = [Role(name=f'usluga-{suffix}-{i}', permissions=permissions) for i, permissions in enumerate(([], ['usluga.manage'], ['usluga.manage']))]
        db.add_all(roles)
        db.flush()
        actors = [User(name=f'actor-{i}', email=f'usluga-{suffix}-{i}@example.invalid', password_hash='unused', role_id=role.id, factory_code=factory, is_active=True) for i, (role, factory) in enumerate(zip(roles, ('ECO', 'MIL', 'ECO')))]
        model = Model(code=f'USLUGA-{suffix}', name='Usluga PG test', status='draft', catalog_scope='usluga', factory_code='ECO', details_json={})
        db.add_all([*actors, model])
        db.flush()
        ids, model_id = [actor.id for actor in actors], model.id

    app = FastAPI()
    app.include_router(router)

    def isolated_db():
        with pg_sessions() as db:
            yield db

    app.dependency_overrides[get_db] = isolated_db
    payload = {'sewing_factory': 'eco_cotton', 'paid_operations': [_operation('eco-test', 'eco_cotton')]}
    def headers(actor_id):
        return {'Authorization': f'Bearer {create_access_token(actor_id)}'}

    with TestClient(app, raise_server_exceptions=False) as client:
        path = f'/usluga/models/{model_id}/paid-operations'
        assert client.patch(path, json=payload).status_code == 401
        assert client.patch(path, headers=headers(ids[0]), json=payload).status_code == 403
        assert client.patch(path, headers=headers(ids[1]), json=payload).status_code == 403
        invalid = {'sewing_factory': 'milana', 'paid_operations': [_operation('wrong-factory', 'milana')]}
        assert client.patch(path, headers=headers(ids[2]), json=invalid).status_code == 403
        with pg_sessions() as db:
            assert db.get(Model, model_id).details_json == {}
            assert db.query(AuditLog).filter_by(action='update_paid_operations', entity_id=model_id).count() == 0
        response = client.patch(path, headers=headers(ids[2]), json=payload)
        assert response.status_code == 200, response.text

    with pg_sessions() as db:
        assert db.get(Model, model_id).details_json['paid_operations'] == payload['paid_operations']
        audit = db.query(AuditLog).filter_by(action='update_paid_operations', entity_id=model_id).one()
        assert audit.user_id == ids[2]
        assert audit.entry_hash
        assert audit_service.verify_audit_hash_chain(db)['ok']
