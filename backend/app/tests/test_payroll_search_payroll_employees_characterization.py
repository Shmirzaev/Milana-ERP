from app.schemas import AuditLog, PayrollAdjustment, PayrollQrLabel, PayrollRecord
from app.tests.payroll_operation_fixture import payroll_case, payroll_postgres_sessions  # noqa: F401


def _counts(c):
    with c.sessions() as db:
        return tuple(db.query(model).count() for model in (AuditLog, PayrollAdjustment, PayrollQrLabel, PayrollRecord))


def test_employee_search_literal_number_and_denial_without_writes(payroll_case):
    c = payroll_case
    before = _counts(c)
    url = '/api/payroll/employees/search'
    r = c.client.get(url, headers=c.headers, params={'q': c.employee_no})
    assert r.status_code == 200, r.text
    assert [row['employee_id'] for row in r.json()['items']] == [c.employee_id]
    assert r.json()['has_more'] is False
    wildcards = c.client.get(url, headers=c.headers, params={'q': '%_'})
    assert wildcards.status_code == 200 and wildcards.json()['items'] == []
    assert c.client.get(url, headers=c.denied, params={'q': c.employee_no}).status_code == 403
    assert _counts(c) == before
