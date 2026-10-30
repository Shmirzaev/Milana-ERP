from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.libs.dto.people.payroll import PayrollAdjustmentIn, PayrollAdjustmentOut
from app.libs.enums.factory import FactoryCode
from app.libs.enums.people import PayrollAdjustmentType
from app.schemas import AuditLog, Employee, PayrollAdjustment, PayrollPeriod
from app.schemas.people.payroll import FactoryCodeStorage, PayrollAdjustmentTypeStorage
from app.tests.conftest import TestSessionLocal


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({}, PayrollAdjustmentType.BONUS),
        ({"adjustment_type": None}, PayrollAdjustmentType.BONUS),
        ({"adjustment_type": "   "}, PayrollAdjustmentType.BONUS),
        ({"adjustment_type": "  DeDuCtIoN  "}, PayrollAdjustmentType.DEDUCTION),
    ],
)
def test_manual_adjustment_dto_normalizes_legacy_type_inputs_to_enum(fields, expected):
    payload = PayrollAdjustmentIn(employee_id=1, amount="1.00", reason="Normalize type", **fields)

    assert payload.adjustment_type is expected


def test_payroll_adjustment_type_mapping_keeps_existing_string_storage_and_check():
    column = PayrollAdjustment.__table__.c.adjustment_type
    checks = {str(constraint.sqltext) for constraint in PayrollAdjustment.__table__.constraints if constraint.name == "ck_payroll_adjustments_type"}

    assert isinstance(column.type, PayrollAdjustmentTypeStorage)
    assert column.type.length == 16
    assert column.default.arg is PayrollAdjustmentType.BONUS
    assert checks == {"adjustment_type IN ('bonus', 'deduction')"}


def test_adjustment_factory_code_storage_maps_all_codes_and_keeps_database_refusal():
    column = PayrollAdjustment.__table__.c.factory_code
    checks = {
        str(constraint.sqltext)
        for constraint in PayrollAdjustment.__table__.constraints
        if constraint.name == "ck_payroll_adjustments_factory_code"
    }

    assert isinstance(column.type, FactoryCodeStorage)
    assert column.type.length == 3
    assert column.default.arg is FactoryCode.MIL
    assert column.server_default.arg == "MIL"
    assert checks == {"factory_code IN ('MIL', 'BST', 'ECO')"}


@pytest.mark.parametrize("factory_code", list(FactoryCode))
def test_adjustment_factory_code_wire_storage_reload_and_raw_query_bind(factory_code):
    with TestSessionLocal() as db:
        marker = uuid4().hex
        employee = Employee(
            factory_code=factory_code.value,
            employee_no=f"ADJ-FC-{marker[:12]}",
            full_name=f"Adjustment factory {factory_code.value} {marker[:8]}",
            status="active",
        )
        db.add(employee)
        db.flush()
        employee_id = employee.id
        adjustment = PayrollAdjustment(
            factory_code=factory_code,
            employee_id=employee_id,
            adjustment_type=PayrollAdjustmentType.BONUS,
            amount=Decimal("1.00"),
            reason=f"Factory code {factory_code.value}",
        )
        db.add(adjustment)
        db.flush()
        adjustment_id = adjustment.id
        assert db.query(PayrollAdjustment).filter_by(
            employee_id=employee_id, factory_code=factory_code.value
        ).one().id == adjustment_id
        assert db.execute(
            text("SELECT factory_code FROM payroll_adjustments WHERE id=:id"), {"id": adjustment_id}
        ).scalar_one() == factory_code.value
        db.commit()

    with TestSessionLocal() as db:
        reloaded = db.get(PayrollAdjustment, adjustment_id)
        assert reloaded.factory_code is factory_code
        assert PayrollAdjustmentOut.model_validate(reloaded).model_dump(mode="json")["factory_code"] == factory_code.value


def test_adjustment_factory_code_invalid_raw_string_reaches_database_check(client, auth_headers):
    employee = client.post(
        "/api/employees",
        json={"full_name": f"Adjustment invalid factory {uuid4().hex[:8]}", "position": "Operator", "status": "active"},
        headers=auth_headers,
    )
    assert employee.status_code == 201, employee.text

    with TestSessionLocal() as db:
        invalid = PayrollAdjustment(
            factory_code="XYZ",
            employee_id=employee.json()["id"],
            adjustment_type=PayrollAdjustmentType.BONUS,
            amount=Decimal("1.00"),
            reason="Invalid factory code must reach database CHECK",
        )
        db.add(invalid)
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()


def test_adjustment_storage_preserves_legacy_raw_strings_and_database_check(client, auth_headers):
    employee = client.post(
        "/api/employees",
        json={"full_name": f"Adjustment raw ORM {uuid4().hex[:8]}", "position": "Operator", "status": "active"},
        headers=auth_headers,
    )
    assert employee.status_code == 201, employee.text
    employee_id = employee.json()["id"]

    with TestSessionLocal() as db:
        factory_code = db.get(Employee, employee_id).factory_code
        bonus = PayrollAdjustment(
            factory_code=factory_code,
            employee_id=employee_id,
            adjustment_type="bonus",
            amount=Decimal("5.00"),
            reason="Legacy raw ORM bonus",
        )
        deduction = PayrollAdjustment(
            factory_code=factory_code,
            employee_id=employee_id,
            adjustment_type="deduction",
            amount=Decimal("7.00"),
            reason="Legacy raw ORM deduction",
        )
        assert bonus.signed_amount == Decimal("5.00")
        assert deduction.signed_amount == Decimal("-7.00")
        db.add_all([bonus, deduction])
        db.flush()
        bonus_id, deduction_id = bonus.id, deduction.id
        assert (
            db.query(PayrollAdjustment)
            .filter_by(employee_id=employee_id, adjustment_type="deduction")
            .one()
            .id
            == deduction_id
        )
        db.commit()

    with TestSessionLocal() as db:
        assert db.get(PayrollAdjustment, bonus_id).adjustment_type is PayrollAdjustmentType.BONUS
        persisted_deduction = db.get(PayrollAdjustment, deduction_id)
        assert persisted_deduction.adjustment_type is PayrollAdjustmentType.DEDUCTION
        assert persisted_deduction.signed_amount == Decimal("-7.00")

    with TestSessionLocal() as db:
        invalid = PayrollAdjustment(
            factory_code=factory_code,
            employee_id=employee_id,
            adjustment_type="refund",
            amount=Decimal("1.00"),
            reason="Invalid legacy type must reach database CHECK",
        )
        db.add(invalid)
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()


def test_manual_adjustment_api_and_storage_round_trip_canonical_type_and_legacy_audit(client, auth_headers):
    employee = client.post(
        "/api/employees",
        json={"full_name": f"Adjustment enum {uuid4().hex[:8]}", "position": "Operator", "status": "active"},
        headers=auth_headers,
    )
    assert employee.status_code == 201, employee.text

    response = client.post(
        "/api/payroll/adjustments",
        json={
            "employee_id": employee.json()["id"],
            "adjustment_type": "  DEDUCTION ",
            "amount": "-12.30",
            "currency": "usdollar99",
            "reason": "Enum storage round trip",
        },
        headers=auth_headers,
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["adjustment_type"] == "deduction"
    assert body["factory_code"] == "MIL"
    assert Decimal(str(body["amount"])) == Decimal("12.30")
    assert Decimal(str(body["signed_amount"])) == Decimal("-12.30")
    assert body["currency"] == "USDOLLAR"

    with TestSessionLocal() as db:
        row = db.get(PayrollAdjustment, body["id"])
        assert row is not None
        assert row.adjustment_type is PayrollAdjustmentType.DEDUCTION
        assert row.signed_amount == Decimal("-12.30")
        stored_value = db.execute(
            text("SELECT adjustment_type FROM payroll_adjustments WHERE id=:id"), {"id": body["id"]}
        ).scalar_one()
        assert stored_value == "deduction"
        db.expire(row, ["adjustment_type"])
        assert row.adjustment_type is PayrollAdjustmentType.DEDUCTION
        assert PayrollAdjustmentOut.model_validate(row).model_dump(mode="json")["adjustment_type"] == "deduction"

        audit = db.query(AuditLog).filter_by(
            action="create", entity_type="PayrollAdjustment", entity_id=body["id"]
        ).one()
        assert audit.user_id == body["created_by"]
        assert audit.new_value_json == {
            "employee_id": employee.json()["id"],
            "adjustment_type": "deduction",
            "amount": 12.3,
            "signed_amount": -12.3,
            "reason": "Enum storage round trip",
        }


def test_manual_adjustment_invalid_type_keeps_literal_422_contract(client, auth_headers):
    employee = client.post(
        "/api/employees",
        json={"full_name": f"Adjustment invalid type {uuid4().hex[:8]}", "position": "Operator", "status": "active"},
        headers=auth_headers,
    )
    assert employee.status_code == 201, employee.text

    response = client.post(
        "/api/payroll/adjustments",
        json={"employee_id": employee.json()["id"], "adjustment_type": "refund", "amount": "1.00", "reason": "Invalid type"},
        headers=auth_headers,
    )

    assert response.status_code == 422, response.text
    error = next(item for item in response.json()["detail"] if item["loc"][-1] == "adjustment_type")
    assert error["type"] == "literal_error"
    assert error["msg"] == "Input should be 'bonus' or 'deduction'"


def test_manual_adjustment_create_hides_cross_factory_period_and_employee(client, auth_headers):
    marker = uuid4().hex[:10]
    now = datetime.now(timezone.utc)
    with TestSessionLocal() as db:
        employee = Employee(
            factory_code="ECO",
            employee_no=f"ADJ-SCOPE-{marker}",
            full_name=f"Other factory adjustment {marker}",
            status="active",
        )
        period = PayrollPeriod(
            factory_code="ECO",
            period_no=f"ADJ-SCOPE-{marker}",
            name=f"Other factory period {marker}",
            start_date=now - timedelta(days=1),
            end_date=now + timedelta(days=1),
            status="open",
        )
        db.add_all([employee, period])
        db.commit()
        employee_id, period_id = employee.id, period.id
        before = (db.query(PayrollAdjustment).count(), db.query(AuditLog).count())

    wrong_period = client.post(
        "/api/payroll/adjustments",
        json={"employee_id": employee_id, "payroll_period_id": period_id, "amount": "1.00", "reason": "Scope"},
        headers=auth_headers,
    )
    assert wrong_period.status_code == 404
    assert wrong_period.json() == {"detail": "Payroll period not found"}

    wrong_employee = client.post(
        "/api/payroll/adjustments",
        json={"employee_id": employee_id, "amount": "1.00", "reason": "Scope"},
        headers=auth_headers,
    )
    assert wrong_employee.status_code == 404
    assert wrong_employee.json() == {"detail": "Employee not found"}
    with TestSessionLocal() as db:
        assert (db.query(PayrollAdjustment).count(), db.query(AuditLog).count()) == before
