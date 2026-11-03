"""Real route/permission and persistence characterization for ModelSize DELETE."""
import pytest
from app.schemas import AuditLog, ModelSize
from app.tests.conftest import TestSessionLocal
from app.tests.test_modelsize_create_operation import size_case, size_client  # noqa: F401


@pytest.fixture
def delete_sizes(size_case):
    with TestSessionLocal.begin() as db:
        rows = [ModelSize(model_id=size_case['models'][scope], size='oʻlcham 🧵') for scope in ('standard', 'usluga')]
        db.add_all(rows); db.flush()
        return [row.id for row in rows]


@pytest.mark.parametrize(('scope', 'actor', 'prefix', 'index'), [('standard', 'standard', '/api/models', 0), ('usluga', 'eco', '/api/usluga/models', 1)])
def test_http_delete_204_empty_and_repeat_404(size_case, size_client, delete_sizes, scope, actor, prefix, index):
    mid, sid = size_case['models'][scope], delete_sizes[index]
    response = size_client.delete(f'{prefix}/{mid}/sizes/{sid}', headers={'X-Actor': actor})
    assert response.status_code == 204 and response.content == b''
    response = size_client.delete(f'{prefix}/{mid}/sizes/{sid}', headers={'X-Actor': actor})
    assert (response.status_code, response.json()['detail']) == (404, 'Size not found')
    with TestSessionLocal() as db:
        assert db.get(ModelSize, sid) is None
        assert db.get(ModelSize, delete_sizes[1-index]) is not None
        log = db.query(AuditLog).filter_by(entity_type='ModelSize', entity_id=sid).one()
        assert (log.action, log.user_id, log.new_value_json) == ('delete', size_case['actors'][actor], {'model_id': mid, 'size': 'oʻlcham 🧵'})


def test_http_denials_and_404_order_no_delete(size_case, size_client, delete_sizes):
    standard, eco = size_case['models']['standard'], size_case['models']['usluga']
    paths = [(f'/api/models/{standard}/sizes/{delete_sizes[0]}', 'denied', 403, None),
             (f'/api/usluga/models/{eco}/sizes/{delete_sizes[1]}', 'denied', 403, None),
             (f'/api/usluga/models/{eco}/sizes/{delete_sizes[1]}', 'wrong_factory', 403, None),
             (f'/api/models/{eco}/sizes/{delete_sizes[1]}', 'standard', 404, 'Model not found'),
             (f'/api/usluga/models/{standard}/sizes/{delete_sizes[0]}', 'eco', 404, 'Model not found'),
             (f'/api/models/999999/sizes/999999', 'standard', 404, 'Model not found'),
             (f'/api/models/{standard}/sizes/{delete_sizes[1]}', 'standard', 404, 'Size not found')]
    for path, actor, status, detail in paths:
        response = size_client.delete(path, headers={'X-Actor': actor})
        assert response.status_code == status, response.text
        if detail:
            assert response.json()['detail'] == detail
    with TestSessionLocal() as db:
        assert all(db.get(ModelSize, sid) is not None for sid in delete_sizes)
        assert db.query(AuditLog).filter(AuditLog.entity_type == 'ModelSize', AuditLog.entity_id.in_(delete_sizes)).count() == 0
