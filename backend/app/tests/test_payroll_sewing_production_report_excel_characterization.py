from io import BytesIO
from openpyxl import load_workbook

from app.schemas import AuditLog, PayrollAdjustment, PayrollQrLabel, PayrollRecord
from app.tests.payroll_operation_fixture import payroll_case, payroll_postgres_sessions  # noqa: F401


def _counts(c):
    with c.sessions() as db:
        return tuple(db.query(model).count() for model in (AuditLog, PayrollAdjustment, PayrollQrLabel, PayrollRecord))


def test_sewing_excel_download_contains_scoped_employee_and_denies_role(payroll_case):
    c = payroll_case
    before = _counts(c)
    url = '/api/payroll/reports/sewing-production.xlsx'
    r = c.client.get(url, headers=c.headers, params={'employee_id': c.employee_id, 'lang': 'en'})
    assert r.status_code == 200, r.text
    assert r.headers['content-type'].startswith('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    assert 'sewing-production-report-' in r.headers['content-disposition']
    book = load_workbook(BytesIO(r.content), data_only=False)
    values = [cell.value for sheet in book for row in sheet for cell in row]
    assert any(c.suffix in str(value) for value in values)
    assert c.client.get(url, headers=c.denied).status_code == 403
    assert _counts(c) == before
