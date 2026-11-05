"""Attendance writes in the business operation's supplied Session."""
from sqlalchemy.orm import Session

from app.schemas import AttendanceDevice, AttendanceEvent, AttendancePerson, SystemSetting


def insert_managed_device(db: Session, *, values: dict) -> AttendanceDevice:
    device = AttendanceDevice(**values)
    db.add(device)
    return device


def update_managed_device(db: Session, *, device: AttendanceDevice, changes: dict) -> None:
    for field, value in changes.items():
        setattr(device, field, value)


def insert_attendance_person(db: Session, *, values: dict) -> AttendancePerson:
    person = AttendancePerson(**values)
    db.add(person)
    return person


def update_attendance_person(db: Session, *, person: AttendancePerson, changes: dict) -> None:
    for field, value in changes.items():
        setattr(person, field, value)


def mark_other_people_absent(db: Session, *, device_id: int, seen: set[str]) -> int:
    query = db.query(AttendancePerson).filter(
        AttendancePerson.device_id == device_id,
        AttendancePerson.present_on_device.is_(True),
    )
    if seen:
        query = query.filter(AttendancePerson.external_person_id.notin_(seen))
    return query.update({AttendancePerson.present_on_device: False}, synchronize_session=False)


def insert_source_checkpoint(db: Session, *, key: str, state: dict[str, object]) -> None:
    db.add(SystemSetting(key=key, value_json=state))


def update_source_checkpoint(db: Session, *, row: SystemSetting, state: dict[str, object]) -> None:
    row.value_json = state


def insert_attendance_event(db: Session, *, values: dict) -> None:
    db.add(AttendanceEvent(**values))
