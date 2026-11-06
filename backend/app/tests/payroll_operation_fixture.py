"""Isolated payroll HTTP cases on SQLite and explicitly supplied PostgreSQL."""
from datetime import datetime, timedelta, timezone
from itertools import count
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.payroll import router
from app.core.deps import get_db
from app.core.security import create_access_token
from app.schemas import Employee, PayrollPeriod, PayrollRecord, Role, User
from app.tests.conftest import TestSessionLocal
from app.tests.test_payroll_period_races import payroll_postgres_sessions  # noqa: F401

_CASES = count()


@pytest.fixture(params=['sqlite', 'postgres'])
def payroll_case(request):
    sessions = TestSessionLocal if request.param == 'sqlite' else request.getfixturevalue('payroll_postgres_sessions')[0]
    suffix = uuid4().hex
    stamp = datetime(2000, 1, 1, tzinfo=timezone.utc) + timedelta(days=20 * (next(_CASES) % 300))
    with sessions() as db:
        role = Role(name='Payroll '+suffix, permissions=['payroll.view', 'payroll.manage', 'payroll.approve', 'payroll.pay'])
        denied_role = Role(name='Denied '+suffix, permissions=[])
        db.add_all([role, denied_role]); db.flush()
        actor = User(name='Payroll '+suffix, email=suffix+'@example.invalid', password_hash='unused', role_id=role.id, factory_code='MIL', is_active=True)
        denied = User(name='Denied '+suffix, email='denied-'+suffix+'@example.invalid', password_hash='unused', role_id=denied_role.id, factory_code='MIL', is_active=True)
        employee = Employee(full_name='Payroll worker '+suffix, employee_no=suffix[:20], factory_code='MIL', status='active')
        db.add_all([actor, denied, employee]); db.flush()
        period = PayrollPeriod(factory_code='MIL', period_no='SRC-'+suffix, name='Source '+suffix, start_date=stamp, end_date=stamp+timedelta(days=5), status='open', created_by=actor.id)
        target = PayrollPeriod(factory_code='MIL', period_no='DST-'+suffix, name='Target '+suffix, start_date=stamp+timedelta(days=6), end_date=stamp+timedelta(days=10), status='open', created_by=actor.id)
        db.add_all([period, target]); db.flush()
        record = PayrollRecord(factory_code='MIL', payroll_period_id=period.id, dedupe_key=suffix, employee_id=employee.id, quantity=10, rate_per_piece=250, total_amount=2500, currency='UZS', scanned_at=stamp+timedelta(days=1), status='recorded', source='characterization')
        db.add(record); db.commit()
        case = SimpleNamespace(sessions=sessions, actor_id=actor.id, denied_id=denied.id, employee_id=employee.id, employee_no=employee.employee_no, period_id=period.id, target_id=target.id, record_id=record.id, stamp=stamp, suffix=suffix)
    app = FastAPI()
    app.include_router(router, prefix='/api')
    def isolated_db():
        with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = isolated_db
    case.headers = {'Authorization': 'Bearer '+create_access_token(case.actor_id)}
    case.denied = {'Authorization': 'Bearer '+create_access_token(case.denied_id)}
    with TestClient(app) as client:
        case.client = client
        yield case
