"""HR settings replacement, factory isolation and audit-before-flush behavior."""

import pytest

from app.api.routes import hr_workspace as routes
from app.schemas import AuditLog, SystemSetting
from app.tests.test_peo01_create_employee_characterization import (
    employee_database as employee_database, h as h, headers,
)


def _seed(h, exists):
    with h[0]() as db:
        db.query(SystemSetting).filter(SystemSetting.key.in_(['hr.settings.mil', 'hr.settings.eco'])).delete()
        db.add(SystemSetting(key='hr.settings.eco', value_json={'company_name': 'Keep ECO'}))
        if exists:
            db.add(SystemSetting(key='hr.settings.mil', value_json={'company_name': 'Old', 'probation_days': 55}))
        db.commit()


@pytest.mark.parametrize('exists', [False, True])
def test_hr_settings_save_replaces_omitted_fields_scopes_and_audits(h, exists):
    _seed(h, exists)
    response = h[2].put('/api/hr/settings', headers=headers(h), json={'company_name': 'Editable company', 'weekend_days': [0, 8]})
    assert response.status_code == 200, response.text
    expected = routes.HrSettingsIn(company_name='Editable company', weekend_days=[0, 8]).model_dump()
    assert response.json() == expected
    with h[0]() as db:
        row = db.query(SystemSetting).filter_by(key='hr.settings.mil').one()
        assert row.value_json == expected
        assert db.query(SystemSetting).filter_by(key='hr.settings.eco').one().value_json == {'company_name': 'Keep ECO'}
        audit = db.query(AuditLog).filter_by(user_id=h[1]['hr']).one()
        assert (audit.action, audit.entity_type, audit.entity_id, audit.new_value_json) == (
            'update', 'HrSettings', row.id if exists else None, expected,
        )
    assert h[2].get('/api/hr/settings', headers=headers(h)).json() == expected


def test_hr_settings_save_permission_and_validation_refusals(h):
    _seed(h, True)
    with h[0]() as db:
        original = db.query(SystemSetting).filter_by(key='hr.settings.mil').one().value_json
    for actor, payload, status in [('denied', {'company_name': 'Denied'}, 403), ('hr', {'default_workday_hours': 25}, 422)]:
        response = h[2].put('/api/hr/settings', headers=headers(h, actor), json=payload)
        assert response.status_code == status, response.text
    with h[0]() as db:
        assert db.query(SystemSetting).filter_by(key='hr.settings.mil').one().value_json == original
        assert db.query(AuditLog).filter_by(user_id=h[1]['hr']).count() == 0


@pytest.mark.parametrize('exists', [False, True])
def test_hr_settings_save_audit_failure_rolls_back(h, monkeypatch, exists):
    _seed(h, exists)
    original = routes.log_action
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('HR settings audit failure')
    monkeypatch.setattr(routes, 'log_action', fail)
    with pytest.raises(RuntimeError, match='HR settings audit failure'):
        h[2].put('/api/hr/settings', headers=headers(h), json={'company_name': 'Rollback'})
    with h[0]() as db:
        row = db.query(SystemSetting).filter_by(key='hr.settings.mil').first()
        assert (row.value_json if row else None) == ({'company_name': 'Old', 'probation_days': 55} if exists else None)
        assert db.query(AuditLog).filter_by(user_id=h[1]['hr']).count() == 0
