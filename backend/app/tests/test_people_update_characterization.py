"""Employee update's existing HTTP contract, on SQLite and approved PostgreSQL."""

from decimal import Decimal
from uuid import uuid4

import pytest

from app.api.routes import hr
from app.schemas import AuditLog, Employee
from app.tests.test_peo01_create_employee_characterization import (
    employee_database, h, headers,  # noqa: F401
)


def target(h):
    result = h[2].post('/api/employees', headers=headers(h), json={
        'full_name': 'Keep employee', 'employee_no': str(uuid4().int)[:14],
        'phone': 'keep', 'salary': '100.1234', 'hr_profile_json': {'scheduled_daily_hours': 8},
    })
    assert result.status_code == 201, result.text
    return result.json()


def state(h, eid):
    with h[0]() as db:
        row = db.get(Employee, eid)
        return (row.full_name, row.employee_no, row.phone, row.salary, row.hr_profile_json,
                db.query(AuditLog).filter_by(entity_type='Employee', entity_id=eid).count())


def test_update_preserves_omissions_null_rounding_and_exact_audit(h):
    employee = target(h)
    patch = {'phone': None, 'salary': '251.23456', 'employee_no': '  123456789  '}
    response = h[2].patch(f"/api/employees/{employee['id']}", headers=headers(h), json=patch)
    assert response.status_code == 200, response.text
    assert response.json()['phone'] is None
    assert response.json()['full_name'] == 'Keep employee'
    assert response.json()['employee_no'] == '123456789'
    assert response.json()['salary'] == 251.2346
    with h[0]() as db:
        row = db.get(Employee, employee['id'])
        assert row.salary == Decimal('251.2346')
        assert row.hr_profile_json == {'scheduled_daily_hours': 8}
        audit = db.query(AuditLog).filter_by(entity_type='Employee', entity_id=row.id, action='update').one()
        assert audit.user_id == h[1]['hr'] and audit.old_value_json is None
        assert audit.new_value_json == {'phone': None, 'salary': 251.2346, 'employee_no': '123456789'}
    assert h[2].get(f"/api/employees/{employee['id']}", headers=headers(h)).json()['phone'] is None


@pytest.mark.parametrize('patch,status,detail', [
    ({'user_id': 99999999, 'salary': '-1'}, 404, 'Employee user not found'),
    ({'salary': '-1'}, 422, 'Employee salary must be nonnegative'),
    ({'hr_profile_json': {'scheduled_daily_hours': 25}}, 422,
     'scheduled_daily_hours must be finite and greater than 0 and no more than 24'),
])
def test_update_refusal_order_and_no_writes(h, patch, status, detail):
    employee = target(h)
    before = state(h, employee['id'])
    response = h[2].patch(f"/api/employees/{employee['id']}", headers=headers(h), json=patch)
    assert (response.status_code, response.json()) == (status, {'detail': detail})
    assert state(h, employee['id']) == before


def test_update_scope_permissions_empty_patch_and_duplicate(h):
    first, second = target(h), target(h)
    before = state(h, second['id'])
    path = f"/api/employees/{second['id']}"
    for actor, status in [('denied', 403), ('eco', 404)]:
        response = h[2].patch(path, headers=headers(h, actor), json={'phone': 'refused'})
        assert response.status_code == status, response.text
    assert h[2].patch(path, json={'phone': 'refused'}).status_code == 401
    response = h[2].patch(path, headers=headers(h), json={'employee_no': first['employee_no']})
    assert response.status_code == 409
    assert state(h, second['id']) == before
    assert h[2].patch(path, headers=headers(h), json={}).status_code == 200
    assert state(h, second['id'])[:-1] == before[:-1]
    with h[0]() as db:
        audit = db.query(AuditLog).filter_by(entity_type='Employee', entity_id=second['id'], action='update').one()
        assert audit.new_value_json == {}


def test_update_audit_failure_rolls_back(h, monkeypatch):
    employee = target(h)
    before = state(h, employee['id'])
    original = hr.log_action

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('synthetic update audit failure')

    monkeypatch.setattr(hr, 'log_action', fail)
    with pytest.raises(RuntimeError, match='synthetic update audit failure'):
        h[2].patch(f"/api/employees/{employee['id']}", headers=headers(h), json={'phone': 'rollback'})
    assert state(h, employee['id']) == before
