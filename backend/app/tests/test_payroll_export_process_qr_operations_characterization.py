from io import BytesIO
from openpyxl import load_workbook

from app.schemas import AuditLog, PayrollAdjustment, PayrollQrLabel, PayrollRecord
from app.tests.payroll_operation_fixture import payroll_case, payroll_postgres_sessions  # noqa: F401


def _counts(c):
    with c.sessions() as db:
        return tuple(db.query(model).count() for model in (AuditLog, PayrollAdjustment, PayrollQrLabel, PayrollRecord))


def test_process_export_preserves_excel_text_and_denies_role_without_writes(payroll_case):
    c = payroll_case
    before = _counts(c)
    payload = {'lang': 'en', 'model': '=MODEL-' + c.suffix, 'order': 'QA-' + c.suffix,
        'factory': 'MIL', 'currency': 'UZS', 'headers': [str(i) for i in range(8)],
        'rows': [{'selected': True, 'section': 'sewing', 'code': 'SEW', 'name': '=2+3', 'rate': '250', 'copies': 1, 'division': 'piece'}]}
    url = '/api/payroll/process-qr/export.xlsx'
    r = c.client.post(url, headers=c.headers, json=payload)
    assert r.status_code == 200, r.text
    assert 'paid-processes.xlsx' in r.headers['content-disposition']
    book = load_workbook(BytesIO(r.content), data_only=False)
    assert book.active['C6'].value == '=2+3' and book.active['C6'].data_type == 's'
    assert book.active['D6'].value == 250
    assert c.client.post(url, headers=c.denied, json=payload).status_code == 403
    assert _counts(c) == before
