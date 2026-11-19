"""Stored People vocabularies keep the same public JSON on both databases."""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.api.routes import hr
from app.core.config import settings
from app.db.base import Base
from app.libs.dto.people.payroll import (
    PayrollAdjustmentOut,
    PayrollPeriodOut,
    PayrollQrLabelOut,
    PayrollRecordOut,
)
from app.schemas import AuditLog, Employee, PayrollAdjustment, PayrollPeriod, PayrollQrLabel, PayrollRecord, Role, User
from app.tests.test_payroll_period_races import payroll_postgres_sessions  # noqa: F401 - pytest fixture, used by name


@pytest.fixture(params=["sqlite", "postgres"])
def sessions(request):
    if request.param == "postgres":
        yield request.getfixturevalue("payroll_postgres_sessions")[0]
        return
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    finally:
        engine.dispose()


def test_payroll_checked_values_round_trip_without_json_changes(sessions):
    marker = uuid4().hex
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with sessions() as db:
        employee = Employee(factory_code="MIL", employee_no=marker[:16], full_name="Vocabulary fixture", status="active")
        period = PayrollPeriod(factory_code="MIL", period_no=marker, name=marker, start_date=stamp, end_date=stamp, status="open")
        db.add_all([employee, period])
        db.flush()
        record = PayrollRecord(
            factory_code="MIL", employee_id=employee.id, dedupe_key=marker, scanned_at=stamp,
            quantity=Decimal("1"), rate_per_piece=Decimal("2"), total_amount=Decimal("2"),
            currency="UZS", source="payroll_scan", status="recorded",
        )
        label = PayrollQrLabel(factory_code="MIL", label_uid=marker, status="available")
        adjustment = PayrollAdjustment(
            factory_code="MIL", employee_id=employee.id, adjustment_type="bonus",
            amount=Decimal("2"), currency="UZS", reason="Vocabulary fixture",
        )
        db.add_all([record, label, adjustment])
        db.commit()

        cases = (
            (period, PayrollPeriodOut, "status", ("draft", "open", "locked", "approved", "paid", "cancelled")),
            (record, PayrollRecordOut, "status", ("recorded", "voided", "approved", "paid")),
            (label, PayrollQrLabelOut, "status", ("available", "scanned", "superseded", "closed")),
            (adjustment, PayrollAdjustmentOut, "adjustment_type", ("bonus", "deduction")),
        )
        for row, dto, field, values in cases:
            for value in values:
                setattr(row, field, value)
                db.flush()
                db.refresh(row)
                assert getattr(row, field) == value
                source = row if row is not label else {**row.__dict__, "qr_token": "200000001"}
                assert dto.model_validate(source).model_dump(mode="json")[field] == value
        for factory_code in ("MIL", "BST", "ECO"):
            employee.factory_code = factory_code
            for row, *_ in cases:
                row.factory_code = factory_code
            db.flush()
            for row, dto, *_ in cases:
                db.refresh(row)
                source = row if row is not label else {**row.__dict__, "qr_token": "200000001"}
                assert dto.model_validate(source).model_dump(mode="json")["factory_code"] == factory_code
        db.rollback()


def test_enabled_employee_list_backfills_missing_users_once_across_factories(sessions, monkeypatch):
    marker = uuid4().hex[:12]
    monkeypatch.setattr(settings, "BACKFILL_EMPLOYEES_FROM_USERS", True)
    with sessions() as db:
        role = Role(name=f"role-{marker}", permissions=[])
        db.add(role)
        db.flush()
        actors = [
            User(name="Viewer", email=f"viewer-{marker}@example.invalid", password_hash="unused", factory_code="MIL", extra_permissions=["hr.employees"]),
            User(name="Active", email=f"active-{marker}@example.invalid", password_hash="unused", factory_code="MIL", role_id=role.id),
            User(name="Inactive", email=f"inactive-{marker}@example.invalid", password_hash="unused", factory_code="MIL", is_active=False),
            User(name="Other factory", email=f"other-{marker}@example.invalid", password_hash="unused", factory_code="BST"),
            User(name="Existing", email=f"existing-{marker}@example.invalid", password_hash="unused", factory_code="MIL"),
        ]
        db.add_all(actors)
        db.flush()
        existing = Employee(factory_code="MIL", user_id=actors[-1].id, full_name="Keep existing", status="on_leave")
        db.add(existing)
        db.commit()
        commits = []
        event.listen(db, "before_commit", lambda session: commits.append(1))
        rows = hr.list_employees(db, actors[0], q=None, limit=None, page=None, page_size=None, search=None)
        assert {"Viewer", "Active", "Inactive", "Keep existing"} <= {row["full_name"] for row in rows}
        assert commits == [1]
        assert hr.list_employees(db, actors[0], q=None, limit=None, page=None, page_size=None, search=None) == rows
        assert commits == [1]
        db.expire_all()
        by_user = {row.user_id: row for row in db.query(Employee).filter(Employee.user_id.in_([actor.id for actor in actors]))}
        assert len(by_user) == 5
        assert (by_user[actors[1].id].position, by_user[actors[2].id].status) == (role.name, "inactive")
        assert (by_user[actors[3].id].factory_code, by_user[actors[4].id].full_name, by_user[actors[4].id].status) == ("BST", "Keep existing", "on_leave")
        assert db.query(AuditLog).filter(AuditLog.entity_type == "Employee").count() == 0
