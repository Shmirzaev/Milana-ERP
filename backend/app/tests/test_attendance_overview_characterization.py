"""Pin overview reconciliation/counts before moving its read operation."""

from datetime import date, datetime, timezone
from uuid import uuid4

from app.api.routes import attendance
from app.schemas import AttendanceDevice, AttendanceEvent, AttendancePerson, User
from app.tests.attendance_operation_fixtures import (
    attendance_database as attendance_database, ah as ah, headers,
)


def seed_read_profiles(ah):
    """A duplicate profile, historical profile, unknown ID and raw failed event."""
    now = datetime(2026, 11, 5, 12, tzinfo=timezone.utc)
    with ah[0]() as db:
        first = AttendanceDevice(factory_code='MIL', device_key=uuid4().hex, name='Gate A', read_only=True)
        second = AttendanceDevice(factory_code='MIL', device_key=uuid4().hex, name='Gate B', read_only=True)
        eco = AttendanceDevice(factory_code='ECO', device_key=uuid4().hex, name='Other factory', read_only=True)
        db.add_all([first, second, eco]); db.flush()
        profiles = [
            AttendancePerson(factory_code='MIL', device_id=first.id, external_person_id='735', full_name='Old 735', present_on_device=False, last_synced_at=now),
            AttendancePerson(factory_code='MIL', device_id=second.id, external_person_id='735', full_name='A Current 735', present_on_device=True, last_synced_at=now),
            AttendancePerson(factory_code='MIL', device_id=first.id, external_person_id='736', full_name='B Absent 736', present_on_device=True, last_synced_at=now),
            AttendancePerson(factory_code='MIL', device_id=first.id, external_person_id='737', full_name='C Historical 737', present_on_device=False, last_synced_at=now),
            AttendancePerson(factory_code='MIL', device_id=first.id, external_person_id='738', full_name='Unused historical', present_on_device=False, last_synced_at=now),
            AttendancePerson(factory_code='ECO', device_id=eco.id, external_person_id='735', full_name='Other factory 735', present_on_device=True, last_synced_at=now),
        ]
        db.add_all(profiles); db.flush(); current_id = profiles[1].id
        cases = [
            ('735', '2026-11-05T03:00:00+00:00', 'success', 'MIL', first.id),
            ('735', '2026-11-05T02:00:00+00:00', None, 'MIL', first.id),
            ('735', '2026-11-05T02:00:00+00:00', ' Success ', 'MIL', second.id),
            ('735', '2026-11-05T04:00:00+00:00', 'denied', 'MIL', first.id),
            ('737', '2026-11-05T01:00:00+00:00', None, 'MIL', first.id),
            ('999', '2026-11-05T05:00:00+00:00', None, 'MIL', first.id),
            (None, '2026-11-05T06:00:00+00:00', None, 'MIL', first.id),
            ('735', '2026-11-05T07:00:00+00:00', None, 'ECO', eco.id),
            ('735', '2026-11-04T18:59:59+00:00', None, 'MIL', first.id),
            ('735', '2026-11-05T19:00:00+00:00', None, 'MIL', first.id),
        ]
        for person, stamp, result, factory, device_id in cases:
            db.add(AttendanceEvent(factory_code=factory, device_id=device_id, event_uid=uuid4().hex,
                                   external_person_id=person, occurred_at=datetime.fromisoformat(stamp),
                                   received_at=now, direction='unknown', result=result))
        db.commit()
    return current_id


def test_overview_preserves_representative_profile_counts_and_unknown_id_semantics(ah):
    current_id = seed_read_profiles(ah)
    response = ah[2].get('/api/attendance/overview?day=2026-11-05', headers=headers(ah))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['date'] == '2026-11-05'
    assert body['summary'] == {'total_people': 3, 'used_today': 3, 'not_used_today': 0, 'events_today': 7, 'unmatched_events': 1}
    assert body['pagination'] == {'page': 1, 'page_size': 50, 'total': 3, 'pages': 1}
    assert [row['external_person_id'] for row in body['people']] == ['735', '736', '737']
    current, absent, historical = body['people']
    assert current['id'] == current_id and current['full_name'] == 'A Current 735'
    assert (current['event_count'], current['worked_minutes'], current['attendance_status']) == (3, 60, 'complete')
    assert current['arrival_at'] == current['first_seen_at'] and current['departure_at'] == current['last_seen_at']
    assert (absent['event_count'], absent['worked_minutes'], absent['attendance_status']) == (0, None, 'absent')
    assert (historical['event_count'], historical['departure_at'], historical['attendance_status']) == (1, None, 'single_scan')
    assert [row['name'] for row in body['devices']] == ['Gate A', 'Gate B']


def test_overview_usage_search_pagination_and_authorization(ah):
    seed_read_profiles(ah)
    client = ah[2]
    for suffix, expected in [('usage=used', ['735', '737']), ('usage=not_used', ['736']), ('query=%20b%20absent%20', ['736']), ('page=2&page_size=10', [])]:
        response = client.get('/api/attendance/overview?day=2026-11-05&'+suffix, headers=headers(ah))
        assert response.status_code == 200, response.text
        assert [row['external_person_id'] for row in response.json()['people']] == expected
    assert client.get('/api/attendance/overview?day=2026-11-05', headers=headers(ah, 'eco')).json()['summary']['total_people'] == 1
    assert client.get('/api/attendance/overview').status_code == 401
    assert client.get('/api/attendance/overview', headers=headers(ah, 'denied')).status_code == 403
    for suffix in ('usage=invalid', 'page=0', 'page_size=9', 'query='+'x'*121):
        assert client.get('/api/attendance/overview?'+suffix, headers=headers(ah)).status_code == 422


def test_overview_read_preserves_no_commit_boundary(ah, monkeypatch):
    seed_read_profiles(ah)
    with ah[0]() as db:
        actor = db.get(User, ah[1]['hr'])
        def no_commit():
            raise AssertionError('Read operation must not commit')
        monkeypatch.setattr(db, 'commit', no_commit)
        body = attendance.attendance_overview(db, actor, date(2026, 11, 5), '', 'all', 1, 50)
        assert body['pagination']['total'] == 3
        assert not db.new and not db.dirty and not db.deleted
