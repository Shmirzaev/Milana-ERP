"""Characterization of one existing HR workspace operation, on both databases."""

from uuid import uuid4

import pytest

from app.api.routes import hr_workspace as routes
from app.schemas import AuditLog, HrOrgUnit
from app.tests.test_peo01_create_employee_characterization import (
    employee_database as employee_database, h as h, headers,
)


def test_org_delete_removes_only_selected_factory_row_and_audits(h):
    factory, users, client = h
    with factory() as db:
        row = HrOrgUnit(name=uuid4().hex, unit_type='team', factory_code='MIL')
        other = HrOrgUnit(name=uuid4().hex, unit_type='team', factory_code='ECO')
        db.add_all([row, other]); db.commit()
        row_id, other_id = row.id, other.id
    response = client.delete(f'/api/hr/organization/{row_id}', headers=headers(h))
    assert response.status_code == 204 and response.content == b''
    with factory() as db:
        assert db.get(HrOrgUnit, row_id) is None
        assert db.get(HrOrgUnit, other_id) is not None
        audit = db.query(AuditLog).filter_by(user_id=users['hr']).one()
        assert (audit.action, audit.entity_type, audit.entity_id) == ('delete', 'HrOrgUnit', row_id)
    assert client.delete(f'/api/hr/organization/{row_id}', headers=headers(h)).status_code == 404
    assert client.delete(f'/api/hr/organization/{other_id}', headers=headers(h)).status_code == 404
    assert client.delete(f'/api/hr/organization/{other_id}', headers=headers(h, 'denied')).status_code == 403


def test_org_delete_audit_failure_rolls_back(h, monkeypatch):
    factory, _, client = h
    with factory() as db:
        row = HrOrgUnit(name=uuid4().hex, unit_type='team', factory_code='MIL')
        db.add(row); db.commit(); row_id = row.id
        before = db.query(AuditLog).count()
    original = routes.log_action
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('org delete audit failure')
    monkeypatch.setattr(routes, 'log_action', fail)
    with pytest.raises(RuntimeError, match='org delete audit failure'):
        client.delete(f'/api/hr/organization/{row_id}', headers=headers(h))
    with factory() as db:
        assert db.get(HrOrgUnit, row_id) is not None
        assert db.query(AuditLog).count() == before
