from decimal import Decimal

from app.schemas import AuditLog, PayrollAdjustment, PayrollQrLabel, PayrollRecord
from app.tests.payroll_operation_fixture import payroll_case, payroll_postgres_sessions  # noqa: F401


def _counts(c):
    with c.sessions() as db:
        return tuple(db.query(model).count() for model in (AuditLog, PayrollAdjustment, PayrollQrLabel, PayrollRecord))


def test_adjustment_legacy_and_page_shape_filter_and_denial_without_writes(payroll_case):
    c = payroll_case
    with c.sessions() as db:
        row = PayrollAdjustment(factory_code='MIL', payroll_period_id=c.period_id, employee_id=c.employee_id,
            adjustment_type='deduction', amount=100, currency='UZS', reason='list fixture')
        db.add(row); db.commit(); aid = row.id
    before = _counts(c)
    url = '/api/payroll/adjustments'
    params = {'employee_id': c.employee_id, 'period_id': c.period_id}
    r = c.client.get(url, headers=c.headers, params=params)
    assert r.status_code == 200 and [row['id'] for row in r.json()] == [aid], r.text
    assert Decimal(r.json()[0]['signed_amount']) == -100
    page = c.client.get(url, headers=c.headers, params={**params, 'page': 1, 'page_size': 1})
    assert page.status_code == 200, page.text
    assert page.json()['total'] == 1 and page.json()['has_more'] is False
    assert page.json()['rows'][0]['employee_name'].endswith(c.suffix)
    assert c.client.get(url, headers=c.denied).status_code == 403
    assert _counts(c) == before
