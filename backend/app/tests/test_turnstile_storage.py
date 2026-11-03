import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.libs.dto.people.turnstile_input import GateEnrollmentInput
from app.libs.enums.turnstile import GateAction, GateBindingState, GateMode, GatePhotoValidation, GateTargetState
from app.schemas.people.turnstile import GatePhotoAsset, GateEmployeeDevice, GateOperation, GateTarget, GateSimulatorDevice, GateSimulatorPerson
from app.schemas.people.turnstile_persistence import insert_photo_asset, insert_binding, insert_operation, insert_target

@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    @event.listens_for(engine, "connect")
    def fk(dbapi_connection, _):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE employees (id INTEGER PRIMARY KEY, factory_code VARCHAR(3) NOT NULL, UNIQUE(id, factory_code))"))
        conn.execute(text("CREATE TABLE attendance_devices (id INTEGER PRIMARY KEY, factory_code VARCHAR(3) NOT NULL, UNIQUE(id, factory_code))"))
        conn.execute(text("INSERT INTO users VALUES (1)"))
        conn.execute(text("INSERT INTO employees VALUES (1, 'MIL'), (2, 'BST')"))
        conn.execute(text("INSERT INTO attendance_devices VALUES (1, 'MIL'), (2, 'BST')"))
        for model in (GatePhotoAsset, GateEmployeeDevice, GateOperation, GateTarget, GateSimulatorDevice, GateSimulatorPerson):
            model.__table__.create(conn)
    with Session(engine) as s:
        yield s
    engine.dispose()

def test_input_contract():
    dto = GateEnrollmentInput(expected_employee_no="e1", device_ids=[1], photo_asset_id=1, manual_face_reviewed=True)
    assert dto.action is GateAction.ENROLL
    assert GateEnrollmentInput.model_fields["action"].annotation is GateAction
    for data in ({"device_ids": [1, 1]}, {"device_ids": [0]}, {"device_ids": list(range(1, 34))}, {"manual_face_reviewed": False}, {"action": "edit"}):
        with pytest.raises(ValidationError):
            GateEnrollmentInput(**({"expected_employee_no": "e1", "device_ids": [1], "photo_asset_id": 1, "manual_face_reviewed": True} | data))

def test_scope_and_enum_round_trip(session):
    asset = insert_photo_asset(session, employee_id=1, factory_code="MIL", created_by=1, stored_name="private", sha256="a" * 64, width=100, height=100, content_type="image/jpeg")
    binding = insert_binding(session, employee_id=1, factory_code="MIL", device_id=1, external_person_id="e1", state=GateBindingState.PENDING, desired_revision=1)
    operation = insert_operation(session, employee_id=1, factory_code="MIL", requested_by=1, action=GateAction.ENROLL, mode=GateMode.SIMULATOR, revision=1, full_name="Test", photo_asset_id=asset.id, external_person_id="e1", snapshot_hash="b" * 64)
    target = insert_target(session, operation_id=operation.id, binding_id=binding.id, device_id=1, device_name="Gate One", factory_code="MIL", employee_id=1, revision=1)
    session.commit()
    session.expire_all()
    assert session.get(GatePhotoAsset, asset.id).validation is GatePhotoValidation.TECHNICAL_VALIDATED
    assert session.get(GateTarget, target.id).state is GateTargetState.QUEUED
    assert session.execute(text("SELECT action, mode FROM gate_operations")).one() == ("enroll", "simulator")
    with pytest.raises(IntegrityError):
        insert_binding(session, employee_id=1, factory_code="MIL", device_id=2, external_person_id="e2", state=GateBindingState.PENDING, desired_revision=1)
    session.rollback()
    with pytest.raises(IntegrityError):
        insert_binding(session, employee_id=1, factory_code="MIL", device_id=1, external_person_id="other", state=GateBindingState.PENDING, desired_revision=1)
    session.rollback()
    with pytest.raises(IntegrityError):
        insert_photo_asset(session, employee_id=2, factory_code="MIL", created_by=1, stored_name="other", sha256="c" * 64, width=10, height=10, content_type="image/jpeg")
    session.rollback()

    with pytest.raises(IntegrityError):
        insert_binding(session, employee_id=2, factory_code="BST", device_id=1, external_person_id="e1", state=GateBindingState.PENDING, desired_revision=1)
    session.rollback()
    with pytest.raises(IntegrityError):
        insert_target(session, operation_id=operation.id, binding_id=binding.id, device_id=2, device_name="Gate Two", factory_code="MIL", employee_id=1, revision=1)
    session.rollback()
