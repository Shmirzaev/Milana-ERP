"""Current HR reconciliation semantics on SQLite and approved PostgreSQL."""

from datetime import date, datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.api.routes import hr_workspace
from app.core.security import create_access_token
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.schemas import AttendanceDevice, AttendanceEvent, Employee, Role, SystemSetting, User
from app.tests.conftest import TestSessionLocal
from app.tests.pg_approved_instance import (
    ApprovedInstanceUnavailable, create_target_database, finalize_target,
    load_approved_instance, require_or_skip, target_engine,
)


@pytest.fixture(scope='module', params=['sqlite', 'postgres'])
def reconciliation_database(request):
    if request.param == 'sqlite':
        yield TestSessionLocal
        return
    try:
        instance = load_approved_instance()
    except ApprovedInstanceUnavailable as exc:
        require_or_skip(exc)
    target = create_target_database(instance)
    engine = None
    try:
        engine = target_engine(target, options='-ctimezone=UTC')
        Base.metadata.create_all(engine)
        yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    finally:
        finalize_target(target, engine)


@pytest.fixture
def reconciliation(reconciliation_database):
    factory = reconciliation_database
    marker = uuid4().hex
    actors = {}
    with factory() as db:
        for name, permissions in [('hr', ['hr.employees']), ('denied', ['finance.view'])]:
            role = Role(name=f'HR reconciliation {name} {marker}', permissions=permissions)
            db.add(role); db.flush()
            user = User(name=name, email=f'{name}-{marker}@example.invalid', password_hash='unused',
                        role_id=role.id, factory_code='MIL', is_active=True)
            db.add(user); db.flush(); actors[name] = user.id
        db.commit()
    def sessions():
        with factory() as db:
            yield db
    previous = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = sessions
    try:
        yield factory, actors, TestClient(app)
    finally:
        app.dependency_overrides[get_db] = previous


def _headers(reconciliation, actor='hr'):
    return {'Authorization': f"Bearer {create_access_token(reconciliation[1][actor], {'factory_code': 'MIL'})}"}


def _utc(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def test_reconciliation_sorts_duplicate_punches_ignores_unknown_people_and_scopes(reconciliation):
    factory, _, client = reconciliation
    url = '/api/hr/attendance?day=2026-11-05'
    before = client.get(url, headers=_headers(reconciliation)).json()['summary']
    number = str(uuid4().int)[:20]
    with factory() as db:
        setting = db.query(SystemSetting).filter_by(key='hr.settings.mil').first()
        if setting is None:
            setting = SystemSetting(key='hr.settings.mil', value_json={}); db.add(setting)
        setting.value_json = {'default_workday_hours': 7.5}
        employees = [
            Employee(full_name='Sorted duplicates', employee_no=number, factory_code='MIL',
                     status='active', hr_profile_json={'scheduled_daily_hours': '6.5'}),
            Employee(full_name='Absent', employee_no=number+'a', factory_code='MIL', status='active'),
            Employee(full_name='Single scan', employee_no=number+'s', factory_code='MIL', status='active'),
            Employee(full_name='Blank number', factory_code='MIL', status='active', hr_profile_json='legacy'),
            Employee(full_name='Archived', employee_no=number+'x', factory_code='MIL', status='archived'),
            Employee(full_name='Other factory', employee_no=number, factory_code='ECO', status='active'),
        ]
        db.add_all(employees); db.flush()
        ids = [row.id for row in employees]
        device = AttendanceDevice(factory_code='MIL', device_key=uuid4().hex, name='Test only', read_only=True)
        db.add(device); db.flush()
        cases = [
            (number, '2026-11-05T18:00:00Z', None, 'MIL'),
            (number, '2026-11-05T00:00:00Z', 'success', 'MIL'),
            (number, '2026-11-05T00:00:00Z', None, 'MIL'),
            (number, '2026-11-05T09:00:00Z', ' Success ', 'MIL'),
            (number, '2026-11-05T18:30:00Z', 'denied', 'MIL'),
            (number, '2026-11-05T19:00:00Z', None, 'MIL'),
            (number, '2026-11-04T18:59:00Z', None, 'MIL'),
            (number, '2026-11-05T18:45:00Z', None, 'ECO'),
            (number+'s', '2026-11-05T12:00:00Z', None, 'MIL'),
            (number+'x', '2026-11-05T10:00:00Z', None, 'MIL'),
            ('unknown-'+number, '2026-11-05T10:00:00Z', None, 'MIL'),
            ('', '2026-11-05T10:00:00Z', None, 'MIL'),
        ]
        for external_id, timestamp, result, scope in cases:
            stamp = _utc(timestamp)
            db.add(AttendanceEvent(factory_code=scope, device_id=device.id, event_uid=uuid4().hex,
                                   external_person_id=external_id, occurred_at=stamp, received_at=stamp,
                                   direction='unknown', result=result))
        db.commit()
    response = client.get(url, headers=_headers(reconciliation))
    assert response.status_code == 200, response.text
    body = response.json()
    rows = {row['employee_id']: row for row in body['rows']}
    assert body['day'] == '2026-11-05'
    assert ids[4] not in rows and ids[5] not in rows
    row = rows[ids[0]]
    assert _utc(row['arrival_at']) == _utc('2026-11-05T00:00:00Z')
    assert _utc(row['departure_at']) == _utc('2026-11-05T18:00:00Z')
    assert (row['worked_minutes'], row['scheduled_minutes'], row['variance_minutes'], row['status']) == (1080, 390, 690, 'present')
    assert (rows[ids[2]]['worked_minutes'], rows[ids[2]]['departure_at'], rows[ids[2]]['status']) == (0, None, 'present')
    for absent_id in (ids[1], ids[3]):
        assert (rows[absent_id]['status'], rows[absent_id]['scheduled_minutes']) == ('absent', 450)
    assert body['summary'] == {**before, 'employees': before['employees']+4, 'present': before['present']+2,
                               'absent': before['absent']+2, 'overtime_minutes': before['overtime_minutes']+690}


def test_reconciliation_permission_missing_auth_and_invalid_day(reconciliation):
    client = reconciliation[2]
    assert client.get('/api/hr/attendance').status_code == 401
    assert client.get('/api/hr/attendance', headers=_headers(reconciliation, 'denied')).status_code == 403
    assert client.get('/api/hr/attendance?day=invalid', headers=_headers(reconciliation)).status_code == 422


def test_reconciliation_read_does_not_commit_or_mutate(reconciliation, monkeypatch):
    with reconciliation[0]() as db:
        actor = db.get(User, reconciliation[1]['hr'])
        def commit_forbidden():
            raise AssertionError('Read operation must not commit')
        monkeypatch.setattr(db, 'commit', commit_forbidden)
        result = hr_workspace.hr_attendance(db, actor, date(2026, 11, 5))
        assert result['day'] == date(2026, 11, 5)
        assert not db.new and not db.dirty and not db.deleted
