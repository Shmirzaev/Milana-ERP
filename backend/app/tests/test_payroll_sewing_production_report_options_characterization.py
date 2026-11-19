from app.schemas import AuditLog, PayrollAdjustment, PayrollQrLabel, PayrollRecord
from app.tests.payroll_operation_fixture import payroll_case, payroll_postgres_sessions  # noqa: F401


def _counts(c):
    with c.sessions() as db:
        return tuple(db.query(model).count() for model in (AuditLog, PayrollAdjustment, PayrollQrLabel, PayrollRecord))


def test_sewing_options_include_scoped_employee_and_refuse_denied_role(payroll_case):
    c = payroll_case
    with c.sessions() as db:
        record = db.get(PayrollRecord, c.record_id)
        record.operation_section, record.operation_code, record.operation_name = 'sewing', 'SEW', 'Assembly'
        db.commit()
    before = _counts(c)
    url = '/api/payroll/reports/sewing-production/options'
    r = c.client.get(url, headers=c.headers)
    assert r.status_code == 200, r.text
    assert str(c.employee_id) in {row['value'] for row in r.json()['employees']}
    assert 'SEW' in {row['value'] for row in r.json()['operations']}
    assert c.client.get(url, headers=c.denied).status_code == 403
    assert _counts(c) == before
