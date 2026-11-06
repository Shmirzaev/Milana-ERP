"""Managed-device contract without Super Admin, on both databases."""
import hashlib

import pytest

from app.api.routes import attendance
from app.schemas import AttendanceDevice,AuditLog
from app.tests.attendance_operation_fixtures import attendance_database,ah,headers,managed_payload  # noqa:F401


def test_device_create_exact_response_hash_only_audit_and_scope(ah,monkeypatch):
    token='characterization-connector-token'
    monkeypatch.setattr(attendance.secrets,'token_urlsafe',lambda length: token)
    response=ah[2].post('/api/attendance/devices',headers=headers(ah),json=managed_payload())
    assert response.status_code==201,response.text
    body=response.json();did=body['id']
    assert body=={'id':did,'device_key':'test-device','name':'Test gate','vendor':'Hikvision','model':None,'serial_no':None,
                  'source_host':'https://test-device.invalid','certificate_sha256':'ab'*32,'managed':True,'sync_enabled':True,
                  'read_only':True,'reported_person_count':None,'last_seen_at':None,'last_people_sync_at':None,
                  'last_event_sync_at':None,'connector_token':token}
    with ah[0]() as db:
        row=db.get(AttendanceDevice,did)
        assert row.connector_token_hash==hashlib.sha256(token.encode()).hexdigest()
        assert row.factory_code=='MIL' and row.configured_by==ah[1]['hr']
        audit=db.query(AuditLog).filter_by(user_id=ah[1]['hr'],action='create',entity_type='AttendanceDeviceConfig').one()
        assert audit.entity_id==did and audit.new_value_json=={'factory_code':'MIL','device_key':'test-device','vendor':'Hikvision'}
        assert token not in str(audit.new_value_json)
    assert ah[2].post('/api/attendance/devices',headers=headers(ah),json=managed_payload()).content==b'{"detail":"Attendance device key already exists in this factory"}'
    monkeypatch.setattr(attendance.secrets,'token_urlsafe',lambda length:token+'-eco')
    assert ah[2].post('/api/attendance/devices',headers=headers(ah,'eco'),json=managed_payload()).status_code==201


def test_device_create_auth_and_validation_leave_no_row(ah):
    for hdr,status in [({},401),(headers(ah,'denied'),403)]:
        r=ah[2].post('/api/attendance/devices',headers=hdr,json=managed_payload());assert r.status_code==status
    r=ah[2].post('/api/attendance/devices',headers=headers(ah),json={**managed_payload(),'source_host':'http://bad'})
    assert r.status_code==422
    with ah[0]() as db:assert db.query(AttendanceDevice).count()==0


def test_device_create_audit_failure_rolls_back(ah,monkeypatch):
    original=attendance.log_action
    def fail(*args,**kwargs):
        original(*args,**kwargs);raise RuntimeError('synthetic device audit failure')
    monkeypatch.setattr(attendance,'log_action',fail)
    with pytest.raises(RuntimeError,match='synthetic device audit failure'):
        ah[2].post('/api/attendance/devices',headers=headers(ah),json=managed_payload())
    with ah[0]() as db:
        assert db.query(AttendanceDevice).count()==0
        assert db.query(AuditLog).filter_by(user_id=ah[1]['hr']).count()==0
