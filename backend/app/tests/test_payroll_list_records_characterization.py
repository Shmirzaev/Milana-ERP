from app.schemas import AuditLog, PayrollAdjustment, PayrollQrLabel, PayrollRecord
from app.tests.payroll_operation_fixture import payroll_case, payroll_postgres_sessions  # noqa: F401


def _counts(c):
    with c.sessions() as db:
        return tuple(db.query(model).count() for model in (AuditLog, PayrollAdjustment, PayrollQrLabel, PayrollRecord))


def test_records_filter_pagination_and_denial_without_writes(payroll_case):
    c = payroll_case
    before = _counts(c)
    params = {'employee_id': c.employee_id, 'period_id': c.period_id}
    r = c.client.get('/api/payroll/records', headers=c.headers, params=params)
    assert r.status_code == 200, r.text
    assert [row['id'] for row in r.json()] == [c.record_id]
    assert r.json()[0]['employee_id'] == c.employee_id
    paged = c.client.get('/api/payroll/records', headers=c.headers, params={**params, 'page': 1, 'page_size': 1})
    assert paged.status_code == 200, paged.text
    assert paged.json()['total'] == 1 and paged.json()['has_more'] is False
    assert [row['id'] for row in paged.json()['rows']] == [c.record_id]
    assert c.client.get('/api/payroll/records?status=unsupported', headers=c.headers).status_code == 400
    assert c.client.get('/api/payroll/records', headers=c.denied).status_code == 403
    assert _counts(c) == before
