from decimal import Decimal

from app.schemas import AuditLog, PayrollAdjustment, PayrollQrLabel, PayrollRecord
from app.tests.payroll_operation_fixture import payroll_case, payroll_postgres_sessions  # noqa: F401


def _counts(c):
    with c.sessions() as db:
        return tuple(db.query(model).count() for model in (AuditLog, PayrollAdjustment, PayrollQrLabel, PayrollRecord))


def test_sewing_details_salary_and_status_validation_without_writes(payroll_case):
    c = payroll_case
    before = _counts(c)
    url = '/api/payroll/reports/sewing-production'
    params = {'employee_id': c.employee_id, 'limit': 1}
    r = c.client.get(url, headers=c.headers, params=params)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body['total'] == 1 and [row['id'] for row in body['items']] == [c.record_id]
    assert Decimal(body['total_quantity']) == 10 and Decimal(body['total_amount']) == 2500
    salary = c.client.get(url, headers=c.headers, params={**params, 'report_view': 'salary'})
    assert salary.status_code == 200, salary.text
    assert salary.json()['items'] == [] and len(salary.json()['salary_summary']) == 1
    assert Decimal(salary.json()['total_amount']) == 2500
    assert c.client.get(url, headers=c.headers, params={'status': 'unsupported'}).status_code == 400
    assert c.client.get(url, headers=c.denied).status_code == 403
    assert _counts(c) == before
