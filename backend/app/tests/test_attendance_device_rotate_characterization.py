"""Token rotation keeps connector behavior, scope and rollback on both databases."""
import hashlib

import pytest

from app.api.routes import attendance
from app.schemas import AttendanceDevice,AuditLog
from app.tests.attendance_operation_fixtures import attendance_database,ah,headers,managed_payload  # noqa:F401


def create(ah):
    r=ah[2].post('/api/attendance/devices',headers=headers(ah),json=managed_payload())
    assert r.status_code==201
    return r.json()


def test_rotation_one_time_token_invalidates_old_and_new_authenticates(ah,monkeypatch):
    tokens=iter(['old-characterization-token','new-characterization-token'])
    monkeypatch.setattr(attendance.secrets,'token_urlsafe',lambda length:next(tokens))
    first=create(ah);did=first['id']
    r=ah[2].post(f'/api/attendance/devices/{did}/rotate-token',headers=headers(ah))
    assert r.status_code==200
    assert r.json()=={**first,'connector_token':'new-characterization-token'}
    with ah[0]() as db:
        device=db.get(AttendanceDevice,did)
        assert device.connector_token_hash==hashlib.sha256(b'new-characterization-token').hexdigest()
        assert device.configured_by==ah[1]['hr']
        audit=db.query(AuditLog).filter_by(user_id=ah[1]['hr'],action='rotate_connector_token').one()
        assert audit.entity_type=='AttendanceDeviceConfig' and audit.entity_id==did
        assert audit.old_value_json is None and audit.new_value_json is None
    payload={'device':{'device_key':'test-device'},'events':[]}
    old=ah[2].post('/api/attendance/integration/events',headers={'X-Attendance-Token':first['connector_token']},json=payload)
    assert old.status_code==401 and old.content==b'{"detail":"Invalid attendance integration credentials"}'
    new=ah[2].post('/api/attendance/integration/events',headers={'X-Attendance-Token':r.json()['connector_token']},json=payload)
    assert new.status_code==200 and new.content==b'{"received":0,"inserted":0,"duplicates":0,"metadata_ignored":false}'


def test_rotate_refusals_and_disabled_state_preserved(ah):
    original=create(ah);did=original['id'];path=f'/api/attendance/devices/{did}/rotate-token'
    for hdr,status in [({},401),(headers(ah,'denied'),403),(headers(ah,'eco'),404)]:
        assert ah[2].post(path,headers=hdr).status_code==status
    assert ah[2].post('/api/attendance/devices/99999999/rotate-token',headers=headers(ah)).content==b'{"detail":"Attendance device not found"}'
    assert ah[2].patch(f'/api/attendance/devices/{did}',headers=headers(ah),json={'sync_enabled':False}).status_code==200
    result=ah[2].post(path,headers=headers(ah));assert result.status_code==200 and result.json()['sync_enabled'] is False
    disabled=ah[2].post('/api/attendance/integration/events',headers={'X-Attendance-Token':result.json()['connector_token']},json={'device':{'device_key':'test-device'},'events':[]})
    assert disabled.status_code==403 and disabled.content==b'{"detail":"Attendance device synchronization is disabled"}'


def test_rotate_audit_failure_restores_old_hash(ah,monkeypatch):
    did=create(ah)['id']
    with ah[0]() as db:old_hash=db.get(AttendanceDevice,did).connector_token_hash
    real=attendance.log_action
    def fail(*args,**kwargs):
        real(*args,**kwargs);raise RuntimeError('synthetic rotation failure')
    monkeypatch.setattr(attendance,'log_action',fail)
    with pytest.raises(RuntimeError,match='synthetic rotation failure'):
        ah[2].post(f'/api/attendance/devices/{did}/rotate-token',headers=headers(ah))
    with ah[0]() as db:
        assert db.get(AttendanceDevice,did).connector_token_hash==old_hash
        assert db.query(AuditLog).filter_by(user_id=ah[1]['hr'],action='rotate_connector_token').count()==0
