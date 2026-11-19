from app.schemas import AuditLog, PayrollAdjustment, PayrollQrLabel, PayrollRecord
from app.tests.payroll_operation_fixture import payroll_case, payroll_postgres_sessions  # noqa: F401


def _counts(c):
    with c.sessions() as db:
        return tuple(db.query(model).count() for model in (AuditLog, PayrollAdjustment, PayrollQrLabel, PayrollRecord))


def test_employee_options_literal_search_selection_and_paging_without_writes(payroll_case):
    c = payroll_case
    before = _counts(c)
    url = '/api/payroll/employees/options'
    params = {'search': c.employee_no, 'selected_id': c.employee_id, 'page_size': 1}
    r = c.client.get(url, headers=c.headers, params=params)
    assert r.status_code == 200, r.text
    body = r.json()
    assert [row['id'] for row in body['items']] == [c.employee_id]
    assert body['selected']['id'] == c.employee_id and body['has_more'] is False
    literal = c.client.get(url, headers=c.headers, params={'search': '%_'})
    assert literal.status_code == 200 and literal.json()['items'] == []
    assert c.client.get(url, headers=c.denied).status_code == 403
    assert _counts(c) == before
