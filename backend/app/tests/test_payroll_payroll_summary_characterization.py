from decimal import Decimal

from app.schemas import AuditLog, PayrollAdjustment, PayrollQrLabel, PayrollRecord
from app.tests.payroll_operation_fixture import payroll_case, payroll_postgres_sessions  # noqa: F401


def _counts(c):
    with c.sessions() as db:
        return tuple(db.query(model).count() for model in (AuditLog, PayrollAdjustment, PayrollQrLabel, PayrollRecord))


def test_summary_totals_operation_group_and_employee_page_without_writes(payroll_case):
    c = payroll_case
    with c.sessions() as db:
        db.add(PayrollAdjustment(factory_code='MIL', payroll_period_id=c.period_id, employee_id=c.employee_id,
            adjustment_type='bonus', amount=500, currency='UZS', reason='summary fixture'))
        db.commit()
    before = _counts(c)
    url = '/api/payroll/summary'
    params = {'period_id': c.period_id, 'employee_id': c.employee_id}
    r = c.client.get(url, headers=c.headers, params=params)
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body['records_count'], body['adjustment_count']) == (1, 1)
    assert (Decimal(body['piecework_amount']), Decimal(body['bonus_amount']), Decimal(body['total_amount'])) == (2500, 500, 3000)
    assert body['employees'][0]['employee_id'] == c.employee_id
    assert Decimal(body['employees'][0]['operations'][0]['total_amount']) == 2500
    page = c.client.get(url, headers=c.headers, params={**params, 'page': 1, 'page_size': 1})
    assert page.status_code == 200 and page.json()['employees_total'] == 1 and page.json()['employees_has_more'] is False
    assert Decimal(page.json()['total_amount']) == 3000
    assert c.client.get(url, headers=c.denied).status_code == 403
    assert _counts(c) == before
