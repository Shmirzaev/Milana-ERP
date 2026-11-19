"""Position creation contract before extraction, on both databases."""

from uuid import uuid4

import pytest

from app.api.routes import hr_workspace as routes
from app.schemas import AuditLog, HrPosition
from app.tests.test_peo01_create_employee_characterization import (
    employee_database as employee_database, h as h, headers,
)


def test_position_create_defaults_scope_and_audit(h):
    factory, users, client = h
    name = uuid4().hex
    response = client.post('/api/hr/positions', headers=headers(h), json={
        'name': f' {name} ', 'required_skills': ['editable skill'], 'salary_min': 100.25,
        'salary_max': 200.5, 'approved_count': 3,
    })
    assert response.status_code == 201, response.text
    body = response.json()
    assert body['name'] == name and body['required_skills'] == ['editable skill']
    assert (body['occupied_count'], body['vacant_count']) == (0, 3)
    with factory() as db:
        row = db.get(HrPosition, body['id'])
        assert row.factory_code == 'MIL' and row.required_skills_json == ['editable skill']
        assert float(row.salary_min) == 100.25
        audit = db.query(AuditLog).filter_by(user_id=users['hr']).one()
        assert (audit.action, audit.entity_type, audit.entity_id, audit.new_value_json) == (
            'create', 'HrPosition', row.id, {'name': name},
        )


def test_position_create_refusals_no_writes(h):
    factory, _, client = h
    with factory() as db:
        before = db.query(HrPosition).count(), db.query(AuditLog).count()
    for actor, payload, status in [
        ('hr', {'name': 'Missing', 'org_unit_id': 99999999, 'department_id': 99999999}, 404),
        ('denied', {'name': 'Denied'}, 403),
        ('hr', {'name': 'Invalid range', 'salary_min': 20, 'salary_max': 10}, 422),
    ]:
        response = client.post('/api/hr/positions', headers=headers(h, actor), json=payload)
        assert response.status_code == status, response.text
    with factory() as db:
        assert (db.query(HrPosition).count(), db.query(AuditLog).count()) == before


def test_position_create_audit_failure_rolls_back(h, monkeypatch):
    factory, _, client = h
    with factory() as db:
        before = db.query(HrPosition).count(), db.query(AuditLog).count()
    original = routes.log_action
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('position audit failure')
    monkeypatch.setattr(routes, 'log_action', fail)
    with pytest.raises(RuntimeError, match='position audit failure'):
        client.post('/api/hr/positions', headers=headers(h), json={'name': 'Rollback'})
    with factory() as db:
        assert (db.query(HrPosition).count(), db.query(AuditLog).count()) == before
