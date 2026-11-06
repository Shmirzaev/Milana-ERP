"""Period CREATE parity on SQLite and disposable PostgreSQL."""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app.api.routes import payroll
from app.core.dt import as_utc
from app.libs.dto.people.payroll import PayrollPeriodIn
from app.schemas import AuditLog, PayrollPeriod, User
from app.tests.conftest import TestSessionLocal
from app.tests.test_payroll_period_races import payroll_postgres_sessions  # noqa: F401


@pytest.fixture(params=['sqlite', 'postgres'])
def sessions(request):
    return TestSessionLocal if request.param == 'sqlite' else request.getfixturevalue('payroll_postgres_sessions')[0]


def test_period_create_persistence_audit_refusals_and_failure_retry(sessions):
    key = uuid4().hex
    stamp = datetime(2001, 1, 1, tzinfo=timezone.utc)
    with sessions() as db:
        actor = User(name='Payroll manager', email=f'{key}@example.invalid', password_hash='unused', factory_code='BST', extra_permissions=['payroll.manage'])
        db.add(actor)
        db.commit()
        uid = actor.id
        payload = PayrollPeriodIn(name=key, period_no=f' {key} ', start_date=stamp, end_date=stamp)
        def fail_commit(session):
            raise RuntimeError('characterization commit failure')
        event.listen(db, 'before_commit', fail_commit)
        with pytest.raises(RuntimeError, match='characterization commit failure'):
            payroll.create_period(payload, db, actor)
        event.remove(db, 'before_commit', fail_commit)
        db.rollback()
    with sessions() as db:
        assert db.query(PayrollPeriod).filter_by(name=key).count() == 0
        assert db.query(AuditLog).filter_by(entity_type='PayrollPeriod', user_id=uid).count() == 0
        result = payroll.create_period(payload, db, db.get(User, uid))
        pid = result.id
    with sessions() as db:
        row = db.get(PayrollPeriod, pid)
        assert (row.name, row.period_no, row.factory_code, row.created_by, row.status) == (key, key, 'BST', uid, 'open')
        audit = db.query(AuditLog).filter_by(entity_type='PayrollPeriod', entity_id=pid).one()
        assert (audit.action, audit.user_id, audit.new_value_json) == ('create', uid, {'period_no': key})
        assert audit.entry_hash
        actor = db.get(User, uid)
        for status in ['locked', 'approved', 'paid', 'cancelled']:
            with pytest.raises(HTTPException) as caught:
                payroll.create_period(payload.model_copy(update={'status': status}), db, actor)
            assert caught.value.status_code == 400
        with pytest.raises(HTTPException) as caught:
            payroll.create_period(payload.model_copy(update={'period_no': key + '-overlap'}), db, actor)
        assert caught.value.status_code == 409
        db.rollback()
        assert db.query(PayrollPeriod).filter_by(name=key).count() == 1


def test_generated_period_number_uses_factory_month_at_utc_boundary(sessions):
    key = uuid4().hex
    start = datetime(2002, 10, 31, 19, tzinfo=timezone.utc)  # 1 Nov in Tashkent
    end = datetime(2002, 11, 29, 18, 59, 59, tzinfo=timezone.utc)
    with sessions() as db:
        actor = User(name='Payroll manager', email=f'{key}@example.invalid', password_hash='unused', factory_code='BST', extra_permissions=['payroll.manage'])
        db.add(actor)
        db.commit()
        result = payroll.create_period(PayrollPeriodIn(name=key, start_date=start, end_date=end), db, actor)
        assert result.period_no == 'PAY-2002-11'
        assert (as_utc(result.start_date), as_utc(result.end_date)) == (start, end)
