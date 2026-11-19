"""Pin managed-device partial update and refusals on both databases."""
import pytest

from app.api.routes import attendance
from app.schemas import AttendanceDevice,AuditLog
from app.tests.attendance_operation_fixtures import attendance_database,ah,headers,managed_payload  # noqa:F401


def create(ah):
    response=ah[2].post('/api/attendance/devices',headers=headers(ah),json=managed_payload())
    assert response.status_code==201
    return response.json()


def test_partial_update_and_empty_patch_preserve_other_fields(ah):
    original=create(ah);did=original['id']
    with ah[0]() as db:old_hash=db.get(AttendanceDevice,did).connector_token_hash
    response=ah[2].patch(f'/api/attendance/devices/{did}',headers=headers(ah),json={'name':' Changed gate ','sync_enabled':False})
    assert response.status_code==200
    expected={k:v for k,v in original.items() if k!='connector_token'};expected.update(name='Changed gate',sync_enabled=False)
    assert response.json()==expected
    assert ah[2].patch(f'/api/attendance/devices/{did}',headers=headers(ah),json={}).json()==expected
    with ah[0]() as db:
        device=db.get(AttendanceDevice,did)
        assert device.connector_token_hash==old_hash and device.configured_by==ah[1]['hr']
        audits=db.query(AuditLog).filter_by(user_id=ah[1]['hr'],action='update',entity_type='AttendanceDeviceConfig').all()
        assert len(audits)==2 and all(a.new_value_json=={'name':'Changed gate','sync_enabled':False} for a in audits)


def test_update_auth_factory_missing_and_validation_refusals(ah):
    did=create(ah)['id'];path=f'/api/attendance/devices/{did}'
    for hdr,status in [({},401),(headers(ah,'denied'),403),(headers(ah,'eco'),404)]:
        assert ah[2].patch(path,headers=hdr,json={'name':'refused'}).status_code==status
    assert ah[2].patch('/api/attendance/devices/99999999',headers=headers(ah),json={}).content==b'{"detail":"Attendance device not found"}'
    assert ah[2].patch(path,headers=headers(ah),json={'name':''}).status_code==422
    with ah[0]() as db:assert db.get(AttendanceDevice,did).name=='Test gate'


def test_update_audit_failure_rolls_back(ah,monkeypatch):
    did=create(ah)['id'];original=attendance.log_action
    def fail(*args,**kwargs):
        original(*args,**kwargs);raise RuntimeError('synthetic device update failure')
    monkeypatch.setattr(attendance,'log_action',fail)
    with pytest.raises(RuntimeError,match='synthetic device update failure'):
        ah[2].patch(f'/api/attendance/devices/{did}',headers=headers(ah),json={'sync_enabled':False})
    with ah[0]() as db:
        assert db.get(AttendanceDevice,did).sync_enabled is True
        assert db.query(AuditLog).filter_by(user_id=ah[1]['hr'],action='update').count()==0
