from app.tests.payroll_operation_fixture import payroll_case, payroll_postgres_sessions  # noqa: F401


def test_list_periods_preserves_status_filter_factory_and_permissions(payroll_case):
    c = payroll_case
    response = c.client.get('/api/payroll/periods', headers=c.headers)
    assert response.status_code == 200, response.text
    assert c.period_id in {row['id'] for row in response.json()}
    assert all(row['factory_code'] == 'MIL' for row in response.json())
    assert c.client.get('/api/payroll/periods?status=paid', headers=c.headers).json() == []
    assert c.client.get('/api/payroll/periods', headers=c.denied).status_code == 403
