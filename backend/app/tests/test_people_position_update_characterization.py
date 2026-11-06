"""Full replacement, refusals and atomic audit for staffing-position update."""

from uuid import uuid4

import pytest

from app.api.routes import hr_workspace as routes
from app.schemas import AuditLog, HrPosition
from app.tests.test_peo01_create_employee_characterization import (
    employee_database as employee_database, h as h, headers,
)


def _position(h, factory_code='MIL'):
    with h[0]() as db:
        row = HrPosition(factory_code=factory_code, name=uuid4().hex, required_skills_json=['old'],
                         approved_count=5, is_active=False, salary_min=100, salary_max=200)
        db.add(row); db.commit(); return row.id


def test_position_update_replaces_omitted_fields_and_audits(h):
    row_id = _position(h)
    response = h[2].patch(f'/api/hr/positions/{row_id}', headers=headers(h), json={'name': ' New position '})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['name'] == 'New position' and body['required_skills'] == []
    assert body['salary_min'] is None and body['salary_max'] is None
    assert body['approved_count'] == 0 and body['is_active'] is True
    with h[0]() as db:
        row = db.get(HrPosition, row_id)
        assert row.factory_code == 'MIL' and row.name == body['name']
        audit = db.query(AuditLog).filter_by(user_id=h[1]['hr']).one()
        values = routes.PositionIn(name='New position').model_dump()
        values['required_skills_json'] = values.pop('required_skills')
        assert (audit.action, audit.entity_type, audit.entity_id, audit.new_value_json) == ('update', 'HrPosition', row_id, values)


def test_position_update_missing_scope_permissions_and_validation_preserve_row(h):
    row_id = _position(h)
    other_id = _position(h, 'ECO')
    for target, actor, payload, status in [
        (99999999, 'hr', {'name': 'Missing', 'org_unit_id': 99999999}, 404),
        (other_id, 'hr', {'name': 'Cross'}, 404),
        (row_id, 'denied', {'name': 'Denied'}, 403),
        (row_id, 'hr', {'name': 'Bad range', 'salary_min': 20, 'salary_max': 10}, 422),
    ]:
        response = h[2].patch(f'/api/hr/positions/{target}', headers=headers(h, actor), json=payload)
        assert response.status_code == status, response.text
    with h[0]() as db:
        assert db.get(HrPosition, row_id).required_skills_json == ['old']
        assert db.query(AuditLog).filter_by(user_id=h[1]['hr']).count() == 0


def test_position_update_audit_failure_rolls_back(h, monkeypatch):
    row_id = _position(h)
    original = routes.log_action
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('update position audit failure')
    monkeypatch.setattr(routes, 'log_action', fail)
    with pytest.raises(RuntimeError, match='update position audit failure'):
        h[2].patch(f'/api/hr/positions/{row_id}', headers=headers(h), json={'name': 'Rollback'})
    with h[0]() as db:
        assert db.get(HrPosition, row_id).required_skills_json == ['old']
        assert db.query(AuditLog).filter_by(user_id=h[1]['hr']).count() == 0
