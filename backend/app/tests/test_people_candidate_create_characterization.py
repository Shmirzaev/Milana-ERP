"""Recruitment candidate creation contract on both databases."""

from uuid import uuid4

import pytest

from app.api.routes import hr_workspace as routes
from app.schemas import AuditLog, HrRecruitmentCandidate
from app.tests.test_peo01_create_employee_characterization import (
    employee_database as employee_database, h as h, headers,
)


def test_candidate_create_persists_private_data_scope_and_audit(h):
    name = uuid4().hex
    body = {'full_name': f' {name} ', 'passport_number': 'TEST-ONLY', 'pinfl': str(uuid4().int)[:14],
            'stage': 'interview', 'source': 'Editable source', 'notes': 'Test-only notes'}
    response = h[2].post('/api/hr/recruitment', headers=headers(h), json=body)
    assert response.status_code == 201 and set(response.json()) == {'id'}, response.text
    with h[0]() as db:
        row = db.get(HrRecruitmentCandidate, response.json()['id'])
        assert (row.full_name, row.factory_code, row.passport_number, row.source, row.stage) == (
            name, 'MIL', 'TEST-ONLY', 'Editable source', 'interview',
        )
        audit = db.query(AuditLog).filter_by(user_id=h[1]['hr']).one()
        assert (audit.action, audit.entity_type, audit.entity_id, audit.new_value_json) == (
            'create', 'HrRecruitmentCandidate', row.id, {'full_name': name},
        )


def test_candidate_create_duplicate_and_reference_refusals_preserve_state(h):
    pinfl = str(uuid4().int)[:14]
    with h[0]() as db:
        db.add(HrRecruitmentCandidate(factory_code='MIL', full_name='Existing', pinfl=pinfl))
        db.commit(); before = db.query(HrRecruitmentCandidate).count(), db.query(AuditLog).count()
    for actor, payload, status, detail in [
        ('hr', {'full_name': 'Duplicate', 'pinfl': pinfl}, 409, 'A candidate with this PINFL already exists'),
        ('hr', {'full_name': 'Missing', 'position_id': 99999999, 'department_id': 99999999}, 404, 'Staffing position not found'),
        ('denied', {'full_name': 'Denied'}, 403, "Missing permission. Need any of: ['hr.employees', '*']"),
    ]:
        response = h[2].post('/api/hr/recruitment', headers=headers(h, actor), json=payload)
        assert (response.status_code, response.json()) == (status, {'detail': detail})
    with h[0]() as db:
        assert (db.query(HrRecruitmentCandidate).count(), db.query(AuditLog).count()) == before


def test_candidate_create_audit_failure_rolls_back(h, monkeypatch):
    with h[0]() as db:
        before = db.query(HrRecruitmentCandidate).count(), db.query(AuditLog).count()
    original = routes.log_action
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('candidate create audit failure')
    monkeypatch.setattr(routes, 'log_action', fail)
    with pytest.raises(RuntimeError, match='candidate create audit failure'):
        h[2].post('/api/hr/recruitment', headers=headers(h), json={'full_name': 'Rollback'})
    with h[0]() as db:
        assert (db.query(HrRecruitmentCandidate).count(), db.query(AuditLog).count()) == before
