"""Existing organization-unit creation contract on both databases."""

from uuid import uuid4

import pytest

from app.api.routes import hr_workspace as routes
from app.schemas import AuditLog, HrOrgUnit
from app.tests.test_peo01_create_employee_characterization import (
    employee_database as employee_database, h as h, headers,
)


def test_org_create_persists_normalization_scope_and_audit(h):
    factory, users, client = h
    name = f"Organization {uuid4().hex}"
    response = client.post('/api/hr/organization', headers=headers(h), json={
        'name': f' {name} ', 'unit_type': 'team', 'code': ' editable ', 'sort_order': -3,
    })
    assert response.status_code == 201, response.text
    assert set(response.json()) == {'id'}
    with factory() as db:
        row = db.get(HrOrgUnit, response.json()['id'])
        assert (row.name, row.factory_code, row.code, row.sort_order) == (name, 'MIL', ' editable ', -3)
        audit = db.query(AuditLog).filter_by(entity_type='HrOrgUnit', entity_id=row.id).one()
        assert (audit.action, audit.user_id, audit.new_value_json) == (
            'create', users['hr'], {'name': name, 'unit_type': 'team'},
        )


@pytest.mark.parametrize('actor,status,detail', [
    ('hr', 404, 'Organization unit not found'),
    ('denied', 403, "Missing permission. Need any of: ['hr.employees', '*']"),
])
def test_org_create_refusal_order_no_writes(h, actor, status, detail):
    factory, _, client = h
    with factory() as db:
        before = db.query(HrOrgUnit).count(), db.query(AuditLog).count()
    response = client.post('/api/hr/organization', headers=headers(h, actor), json={
        'name': 'Refused', 'unit_type': 'team', 'parent_id': 99999999,
        'department_id': 99999999, 'manager_employee_id': 99999999,
    })
    assert (response.status_code, response.json()) == (status, {'detail': detail})
    with factory() as db:
        assert (db.query(HrOrgUnit).count(), db.query(AuditLog).count()) == before


def test_org_create_audit_failure_rolls_back(h, monkeypatch):
    factory, _, client = h
    with factory() as db:
        before = db.query(HrOrgUnit).count(), db.query(AuditLog).count()
    original = routes.log_action

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('org audit failure')

    monkeypatch.setattr(routes, 'log_action', fail)
    with pytest.raises(RuntimeError, match='org audit failure'):
        client.post('/api/hr/organization', headers=headers(h), json={'name': 'Rollback', 'unit_type': 'team'})
    with factory() as db:
        assert (db.query(HrOrgUnit).count(), db.query(AuditLog).count()) == before
