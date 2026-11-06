"""Recruitment candidate replacement behavior on SQLite and PostgreSQL."""

from uuid import uuid4

import pytest

from app.api.routes import hr_workspace as routes
from app.schemas import AuditLog, HrRecruitmentCandidate
from app.tests.test_peo01_create_employee_characterization import (
    employee_database as employee_database, h as h, headers,
)


def _candidate(h, factory_code='MIL'):
    with h[0]() as db:
        row = HrRecruitmentCandidate(factory_code=factory_code, full_name=uuid4().hex,
                                     pinfl=str(uuid4().int)[:14], passport_number='TEST-OLD', stage='interview')
        db.add(row); db.commit(); return row.id, row.pinfl


def test_candidate_update_is_full_replacement_and_stage_only_audit(h):
    row_id, _ = _candidate(h)
    response = h[2].patch(f'/api/hr/recruitment/{row_id}', headers=headers(h), json={'full_name': ' Updated candidate '})
    assert response.status_code == 200 and response.json() == {'id': row_id}, response.text
    with h[0]() as db:
        row = db.get(HrRecruitmentCandidate, row_id)
        assert (row.full_name, row.stage, row.pinfl, row.passport_number, row.factory_code) == (
            'Updated candidate', 'applied', None, None, 'MIL',
        )
        audit = db.query(AuditLog).filter_by(user_id=h[1]['hr']).one()
        assert (audit.action, audit.entity_type, audit.entity_id, audit.new_value_json) == (
            'update', 'HrRecruitmentCandidate', row_id, {'stage': 'applied'},
        )


def test_candidate_update_refusals_and_self_pinfl_exclusion(h):
    row_id, pinfl = _candidate(h)
    other_id, duplicate = _candidate(h)
    eco_id, _ = _candidate(h, 'ECO')
    for target, actor, payload, status in [
        (row_id, 'hr', {'full_name': 'Duplicate', 'pinfl': duplicate}, 409),
        (eco_id, 'hr', {'full_name': 'Cross'}, 404),
        (99999999, 'hr', {'full_name': 'Missing', 'position_id': 99999999}, 404),
        (row_id, 'denied', {'full_name': 'Denied'}, 403),
    ]:
        response = h[2].patch(f'/api/hr/recruitment/{target}', headers=headers(h, actor), json=payload)
        assert response.status_code == status, response.text
    with h[0]() as db:
        assert db.get(HrRecruitmentCandidate, row_id).pinfl == pinfl
        assert db.query(AuditLog).filter_by(user_id=h[1]['hr']).count() == 0
        assert db.get(HrRecruitmentCandidate, other_id).pinfl == duplicate
    response = h[2].patch(f'/api/hr/recruitment/{row_id}', headers=headers(h), json={'full_name': 'Self PINFL', 'pinfl': pinfl})
    assert response.status_code == 200, response.text


def test_candidate_update_audit_failure_rolls_back(h, monkeypatch):
    row_id, pinfl = _candidate(h)
    original = routes.log_action
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('candidate update audit failure')
    monkeypatch.setattr(routes, 'log_action', fail)
    with pytest.raises(RuntimeError, match='candidate update audit failure'):
        h[2].patch(f'/api/hr/recruitment/{row_id}', headers=headers(h), json={'full_name': 'Rollback'})
    with h[0]() as db:
        assert db.get(HrRecruitmentCandidate, row_id).pinfl == pinfl
        assert db.query(AuditLog).filter_by(user_id=h[1]['hr']).count() == 0
