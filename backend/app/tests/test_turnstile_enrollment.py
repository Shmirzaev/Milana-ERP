from fastapi import HTTPException
import pytest
from app.core.config import settings
from app.libs.dto.people.turnstile_input import GateEnrollmentInput
from app.libs.enums.turnstile import GateMode, GateTargetState
from app.models.people.turnstile_access_service import enroll_gate_employee
from app.schemas import AttendanceDevice, Employee, User
from app.schemas.people.turnstile import GateOperation, GatePhotoAsset, GateSimulatorDevice
from app.tests.conftest import TestSessionLocal

def test_enrollment_atomic_retry(monkeypatch):
    monkeypatch.setattr(settings, "TURNSTILE_PROVISIONING_MODE", GateMode.SIMULATOR)
    with TestSessionLocal() as db:
        actor = db.query(User).filter_by(email="admin@example.com").one()
        employee = Employee(factory_code="MIL", employee_no="SYN-1991", full_name="Synthetic User", status="active")
        device = AttendanceDevice(factory_code="MIL", device_key="synthetic-gate", name="Synthetic gate", sync_enabled=True, read_only=True)
        db.add_all([employee, device]); db.flush()
        photo = GatePhotoAsset(employee_id=employee.id, factory_code="MIL", created_by=actor.id, stored_name="synthetic-private", sha256="a"*64, width=20, height=20, content_type="image/png")
        db.add_all([photo, GateSimulatorDevice(device_id=device.id, factory_code="MIL", mode=GateMode.SIMULATOR, online=True)]); db.commit()
        from app.models.people.turnstile_access_service import get_gate_context
        assert get_gate_context(db, actor, employee.id).devices[0].online is True
        payload = GateEnrollmentInput(expected_employee_no="SYN-1991", device_ids=[device.id], photo_asset_id=photo.id, manual_face_reviewed=True)
        first = enroll_gate_employee(db, actor, employee.id, payload, "retry-one")
        second = enroll_gate_employee(db, actor, employee.id, payload, "retry-one")
        assert first.id == second.id
        assert [target.state for target in second.targets] == [GateTargetState.QUEUED]
        assert db.query(GateOperation).count() == 1
        with pytest.raises(HTTPException) as error:
            enroll_gate_employee(db, actor, employee.id, payload.model_copy(update={"reviewed_name": "Changed"}), "retry-one")
        assert error.value.status_code == 409
        assert db.get(Employee, employee.id).full_name == "Synthetic User"
        second_device = AttendanceDevice(factory_code="MIL", device_key="second-gate", name="Second", sync_enabled=True, read_only=True)
        db.add(second_device); db.flush()
        db.add(GateSimulatorDevice(device_id=second_device.id, factory_code="MIL", mode=GateMode.SIMULATOR, online=True)); db.commit()
        mixed = GateEnrollmentInput(expected_employee_no="SYN-1991", device_ids=[device.id, second_device.id], photo_asset_id=photo.id, manual_face_reviewed=True)
        with pytest.raises(HTTPException) as duplicate:
            enroll_gate_employee(db, actor, employee.id, mixed, "duplicate")
        assert duplicate.value.status_code == 409
        assert db.query(GateOperation).count() == 1
        only_new = GateEnrollmentInput(expected_employee_no="SYN-1991", device_ids=[second_device.id], photo_asset_id=photo.id, manual_face_reviewed=True)
        later = enroll_gate_employee(db, actor, employee.id, only_new, "new-device")
        assert later.revision == first.revision + 1

def test_request_requires_review_and_devices():
    with pytest.raises(ValueError):
        GateEnrollmentInput(expected_employee_no="SYN-1992", device_ids=[], photo_asset_id=1, manual_face_reviewed=True)
    with pytest.raises(ValueError):
        GateEnrollmentInput(expected_employee_no="SYN-1992", device_ids=[1], photo_asset_id=1, manual_face_reviewed=False)

@pytest.mark.parametrize("failure", ["archived", "number", "drift", "photo", "device", "alias", "mirror", "mirror_same", "mirror_cross", "disabled"])
def test_refusals_leave_no_operation(monkeypatch, failure):
    from datetime import datetime, timezone
    from app.schemas import AttendancePerson, SystemSetting
    monkeypatch.setattr(settings, "TURNSTILE_PROVISIONING_MODE", GateMode.DISABLED if failure == "disabled" else GateMode.SIMULATOR)
    with TestSessionLocal() as db:
        actor = db.query(User).filter_by(email="admin@example.com").one()
        employee = Employee(factory_code="MIL", employee_no=None if failure == "number" else "NEW-NUMBER" if failure == "drift" else "SYN-1992", full_name="Synthetic User", status="archived" if failure == "archived" else "active")
        device = AttendanceDevice(factory_code="MIL", device_key="test-gate", name="Gate", sync_enabled=True, read_only=True)
        db.add_all([employee, device]); db.flush()
        photo = GatePhotoAsset(employee_id=employee.id, factory_code="MIL", created_by=actor.id, stored_name="private", sha256="a"*64, width=20, height=20, content_type="image/png")
        db.add(photo)
        if failure != "device":
            db.add(GateSimulatorDevice(device_id=device.id, factory_code="MIL", mode=GateMode.SIMULATOR, online=True))
        if failure == "alias":
            db.add(SystemSetting(key="employee_merge_aliases:MIL", value_json={"numbers": {"SYN-1992": 99999}}))
        if failure in {"mirror", "mirror_same", "mirror_cross"}:
            db.add(AttendancePerson(factory_code="BET" if failure == "mirror_cross" else "MIL", device_id=device.id, external_person_id="SYN-1992", full_name="Synthetic User" if failure == "mirror_same" else "Other Person", last_synced_at=datetime.now(timezone.utc)))
        db.commit()
        payload = GateEnrollmentInput(expected_employee_no="SYN-1992", device_ids=[device.id], photo_asset_id=999999 if failure == "photo" else photo.id, manual_face_reviewed=True)
        with pytest.raises(HTTPException):
            enroll_gate_employee(db, actor, employee.id, payload, "refusal")
        assert db.query(GateOperation).count() == 0
        assert db.get(Employee, employee.id).full_name == "Synthetic User"
        if failure in {"mirror", "mirror_same", "mirror_cross"}:
            retained = db.query(AttendancePerson).filter_by(device_id=device.id, external_person_id="SYN-1992").one()
            assert retained.full_name == ("Synthetic User" if failure == "mirror_same" else "Other Person")

@pytest.mark.parametrize("permissions", [[], ["hr.employees"], ["attendance.provision"], ["attendance.manage", "hr.employees"]])
def test_permissions_are_independently_required(permissions):
    from app.models.people.turnstile_access_service import authorize_gate_employee
    from app.schemas import Role
    with TestSessionLocal() as db:
        role = Role(name="Gate test", permissions=permissions)
        actor = User(name="Test", email="gate-test@example.com", password_hash="unused", factory_code="MIL", is_active=True, role=role)
        employee = Employee(factory_code="MIL", employee_no="SYN-1993", full_name="Test", status="active")
        db.add_all([actor, employee]); db.commit()
        with pytest.raises(HTTPException) as error:
            authorize_gate_employee(db, actor, employee.id)
        assert error.value.status_code == 403

def test_cross_factory_employee_is_hidden():
    from app.models.people.turnstile_access_service import authorize_gate_employee
    with TestSessionLocal() as db:
        actor = db.query(User).filter_by(email="admin@example.com").one()
        employee = Employee(factory_code="BET", employee_no="SYN-1994", full_name="Test", status="active")
        db.add(employee); db.commit()
        with pytest.raises(HTTPException) as error:
            authorize_gate_employee(db, actor, employee.id)
        assert error.value.status_code == 404

def test_operation_read_rejects_actor_before_lookup():
    from app.models.people.turnstile_access_service import get_gate_operation
    with TestSessionLocal() as db:
        with pytest.raises(HTTPException) as error:
            get_gate_operation(db, None, 999999)
        assert error.value.status_code == 401

def test_changed_hr_number_cannot_remap_existing_device_identity(monkeypatch):
    from app.libs.enums.turnstile import GateBindingState
    from app.schemas.people.turnstile import GateEmployeeDevice
    monkeypatch.setattr(settings, "TURNSTILE_PROVISIONING_MODE", GateMode.SIMULATOR)
    with TestSessionLocal() as db:
        actor = db.query(User).filter_by(email="admin@example.com").one()
        employee = Employee(factory_code="MIL", employee_no="CURRENT-NO", full_name="Synthetic", status="active")
        old = AttendanceDevice(factory_code="MIL", device_key="identity-old", name="Original gate", read_only=True)
        new = AttendanceDevice(factory_code="MIL", device_key="identity-new", name="New gate", read_only=True)
        db.add_all([employee, old, new]); db.flush()
        asset = GatePhotoAsset(employee_id=employee.id, factory_code="MIL", created_by=actor.id,
            stored_name="identity-asset.jpg", sha256="a"*64, width=10, height=10, content_type="image/jpeg")
        binding = GateEmployeeDevice(employee_id=employee.id, factory_code="MIL", device_id=old.id,
            external_person_id="PREVIOUS-NO", state=GateBindingState.ACTIVE, desired_revision=1)
        db.add_all([asset, binding, GateSimulatorDevice(device_id=new.id, factory_code="MIL", online=True, mode=GateMode.SIMULATOR)])
        db.commit()
        payload = GateEnrollmentInput(expected_employee_no="CURRENT-NO", device_ids=[new.id],
            photo_asset_id=asset.id, manual_face_reviewed=True)
        with pytest.raises(HTTPException) as error:
            enroll_gate_employee(db, actor, employee.id, payload, "identity-drift")
        assert error.value.status_code == 409
        assert db.query(GateOperation).count() == 0
        assert db.query(GateEmployeeDevice).count() == 1
        assert db.get(GateEmployeeDevice, binding.id).external_person_id == "PREVIOUS-NO"
