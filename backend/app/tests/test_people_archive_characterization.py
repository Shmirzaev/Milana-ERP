"""Both archive entry points retain employee links and one audit on both databases."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.api.routes import hr
from app.schemas import AuditLog, Employee, PayrollRecord, Role, User
from app.tests.test_peo01_create_employee_characterization import (
    employee_database, h, headers,  # noqa: F401
)


def target(h):
    response = h[2].post('/api/employees', headers=headers(h), json={'full_name': f'Archive {uuid4().hex}'})
    assert response.status_code == 201, response.text
    return response.json()['id']


def state(h, eid):
    with h[0]() as db:
        return (db.get(Employee, eid).status,
                db.query(AuditLog).filter_by(entity_type='Employee', entity_id=eid, action='archive').count())


def test_archive_preserves_payroll_manager_links_and_repeated_audit(h):
    eid = target(h)
    with h[0]() as db:
        record = PayrollRecord(factory_code='MIL', employee_id=eid, dedupe_key=uuid4().hex,
                               quantity=10, rate_per_piece=25, total_amount=250,
                               scanned_at=datetime.now(timezone.utc))
        subordinate = Employee(factory_code='MIL', full_name='Retain manager link', manager_employee_id=eid)
        db.add_all([record, subordinate]); db.commit()
        rid, sid = record.id, subordinate.id
    for _ in range(2):
        response = h[2].post(f'/api/employees/{eid}/archive', headers=headers(h))
        assert response.status_code == 204 and response.content == b''
    assert state(h, eid) == ('archived', 1)
    with h[0]() as db:
        assert db.get(PayrollRecord, rid).employee_id == eid
        assert db.get(Employee, sid).manager_employee_id == eid
        audit = db.query(AuditLog).filter_by(entity_type='Employee', entity_id=eid, action='archive').one()
        assert audit.user_id == h[1]['hr']
        assert audit.old_value_json == {'status': 'active'}
        assert audit.new_value_json == {'status': 'archived'}
    assert h[2].get(f'/api/employees/{eid}', headers=headers(h)).json()['status'] == 'archived'
    assert h[2].patch(f'/api/employees/{eid}', headers=headers(h), json={'status': 'active'}).status_code == 200
    assert state(h, eid)[0] == 'active'


def test_archive_and_legacy_delete_permission_scope_contract(h):
    eid = target(h)
    path = f'/api/employees/{eid}'
    for actor, expected in [('denied', 403), ('eco', 404)]:
        assert h[2].post(path+'/archive', headers=headers(h, actor)).status_code == expected
        assert h[2].delete(path, headers=headers(h, actor)).status_code == expected
    assert h[2].post(path+'/archive').status_code == 401
    assert state(h, eid) == ('active', 0)
    with h[0]() as db:
        actor = db.get(User, h[1]['hr'])
        db.get(Role, actor.role_id).permissions = ['payroll.manage']
        db.commit()
    assert h[2].delete(path, headers=headers(h)).status_code == 403
    assert h[2].post(path+'/archive', headers=headers(h)).status_code == 204
    with h[0]() as db:
        actor = db.get(User, h[1]['hr'])
        db.get(Role, actor.role_id).permissions = ['hr.employees']
        db.get(Employee, eid).status = 'inactive'
        db.commit()
    assert h[2].delete(path, headers=headers(h)).status_code == 204
    assert state(h, eid) == ('archived', 2)
    assert h[2].post('/api/employees/99999999/archive', headers=headers(h)).status_code == 404


def test_archive_audit_failure_rolls_back(h, monkeypatch):
    eid = target(h)
    original = hr.log_action

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('synthetic archive audit failure')

    monkeypatch.setattr(hr, 'log_action', fail)
    with pytest.raises(RuntimeError, match='synthetic archive audit failure'):
        h[2].post(f'/api/employees/{eid}/archive', headers=headers(h))
    assert state(h, eid) == ('active', 0)
