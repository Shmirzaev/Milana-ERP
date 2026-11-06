from app.schemas import AuditLog, PayrollAdjustment, PayrollQrLabel, PayrollRecord
from app.tests.payroll_operation_fixture import payroll_case, payroll_postgres_sessions  # noqa: F401


def _counts(c):
    with c.sessions() as db:
        return tuple(db.query(model).count() for model in (AuditLog, PayrollAdjustment, PayrollQrLabel, PayrollRecord))


def test_resolve_employee_number_trims_case_and_refuses_missing_and_denied(payroll_case):
    c = payroll_case
    before = _counts(c)
    url = '/api/payroll/employees/resolve'
    r = c.client.get(url, headers=c.headers, params={'employee_no': ' ' + c.employee_no.upper() + ' '})
    assert r.status_code == 200, r.text
    assert r.json()['employee_id'] == c.employee_id and r.json()['type'] == 'employee_payroll'
    assert c.client.get(url, headers=c.headers, params={'employee_no': 'missing-' + c.suffix[:10]}).status_code == 404
    assert c.client.get(url, headers=c.headers, params={'employee_no': 'x' * 33}).status_code == 400
    assert c.client.get(url, headers=c.denied, params={'employee_no': c.employee_no}).status_code == 403
    assert _counts(c) == before
