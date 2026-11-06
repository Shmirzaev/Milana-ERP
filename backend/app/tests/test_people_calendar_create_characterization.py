"""HR calendar creation's current persistence, validation and audit contract."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.api.routes import hr_workspace as routes
from app.schemas import AuditLog, HrCalendarEvent
from app.tests.test_peo01_create_employee_characterization import (
    employee_database as employee_database, h as h, headers,
)


def test_calendar_create_persists_defaults_scope_and_audit(h):
    title = uuid4().hex
    starts_at = datetime(2026, 11, 5, 9, tzinfo=timezone.utc)
    response = h[2].post('/api/hr/calendar', headers=headers(h), json={
        'title': f' {title} ', 'event_type': 'training', 'starts_at': starts_at.isoformat(),
        'notes': 'Editable test notes',
    })
    assert response.status_code == 201 and set(response.json()) == {'id'}, response.text
    with h[0]() as db:
        row = db.get(HrCalendarEvent, response.json()['id'])
        assert (row.factory_code, row.title, row.status, row.ends_at, row.notes) == (
            'MIL', title, 'scheduled', None, 'Editable test notes',
        )
        assert row.starts_at.replace(tzinfo=timezone.utc) == starts_at
        audit = db.query(AuditLog).filter_by(user_id=h[1]['hr']).one()
        assert (audit.action, audit.entity_type, audit.entity_id, audit.new_value_json) == (
            'create', 'HrCalendarEvent', row.id, {'title': title, 'event_type': 'training'},
        )


def test_calendar_create_refusals_preserve_state(h):
    with h[0]() as db:
        before = db.query(HrCalendarEvent).count(), db.query(AuditLog).count()
    for actor, changes, status in [
        ('hr', {'employee_id': 99999999}, 404),
        ('denied', {}, 403),
        ('hr', {'ends_at': '2026-11-04T09:00:00Z'}, 422),
    ]:
        response = h[2].post('/api/hr/calendar', headers=headers(h, actor), json={
            'title': 'Refused', 'event_type': 'training', 'starts_at': '2026-11-05T09:00:00Z', **changes,
        })
        assert response.status_code == status, response.text
    with h[0]() as db:
        assert (db.query(HrCalendarEvent).count(), db.query(AuditLog).count()) == before


def test_calendar_create_audit_failure_rolls_back(h, monkeypatch):
    with h[0]() as db:
        before = db.query(HrCalendarEvent).count(), db.query(AuditLog).count()
    original = routes.log_action
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('calendar audit failure')
    monkeypatch.setattr(routes, 'log_action', fail)
    with pytest.raises(RuntimeError, match='calendar audit failure'):
        h[2].post('/api/hr/calendar', headers=headers(h), json={
            'title': 'Rollback', 'event_type': 'other', 'starts_at': '2026-11-05T09:00:00Z',
        })
    with h[0]() as db:
        assert (db.query(HrCalendarEvent).count(), db.query(AuditLog).count()) == before
