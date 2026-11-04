"""Catalog and Usluga model-create route characterization on SQLite."""
from uuid import uuid4

import pytest

from app.schemas import AuditLog, Model
from app.tests.conftest import TestSessionLocal
from app.tests.test_modelcolor_create_baseline import color_case, color_app, color_client  # noqa: F401


@pytest.mark.parametrize(('path', 'actor', 'scope', 'factory'), [
    ('/api/models', 'standard', 'standard', None),
    ('/api/usluga/models', 'eco', 'usluga', 'ECO'),
])
def test_create_route_persists_and_audits(color_case, color_client, path, actor, scope, factory):
    code = 'ROUTE' + uuid4().hex[:12].upper()
    body = {'code': code, 'name': 'Synthetic route'}
    for denied in ('anonymous', 'denied'):
        response = color_client.post(path, headers={'X-Actor': denied}, json=body)
        assert response.status_code == (401 if denied == 'anonymous' else 403)
    if scope == 'usluga':
        assert color_client.post(path, headers={'X-Actor': 'wrong_factory'}, json=body).status_code == 403
    response = color_client.post(path, headers={'X-Actor': actor}, json=body)
    assert response.status_code == 201, response.text
    assert color_client.post(path, headers={'X-Actor': actor}, json=body).status_code == 400
    with TestSessionLocal() as db:
        row = db.get(Model, response.json()['id'])
        assert (row.code, row.catalog_scope, row.factory_code, row.status) == (code, scope, factory, 'draft')
        assert db.query(AuditLog).filter_by(entity_type='Model', entity_id=row.id, action='create').count() == 1
