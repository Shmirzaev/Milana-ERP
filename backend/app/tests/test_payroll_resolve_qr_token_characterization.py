from app.schemas import AuditLog, PayrollAdjustment, PayrollQrLabel, PayrollRecord
from app.tests.payroll_operation_fixture import payroll_case, payroll_postgres_sessions  # noqa: F401


def _counts(c):
    with c.sessions() as db:
        return tuple(db.query(model).count() for model in (AuditLog, PayrollAdjustment, PayrollQrLabel, PayrollRecord))


def _labels(c):
    order = 'SO-QA-' + c.suffix
    with c.sessions() as db:
        labels = [PayrollQrLabel(factory_code=factory, label_uid=c.suffix + '-' + status + '-' + factory,
            sales_order_no=order, model_code='MODEL-' + c.suffix, operation_section='sewing',
            operation_code='SEW', operation_name='Assembly', quantity=10, rate_per_piece=250,
            currency='UZS', size='L', status=status, issued_by=c.actor_id,
            payroll_record_id=c.record_id if status == 'scanned' and factory == 'MIL' else None)
            for factory, status in [('MIL', 'available'), ('MIL', 'scanned'), ('MIL', 'superseded'), ('ECO', 'available')]]
        db.add_all(labels); db.commit()
        return order, [label.id for label in labels]


def test_resolve_numeric_employee_and_work_qr_without_writes(payroll_case):
    c = payroll_case
    order, ids = _labels(c)
    before = _counts(c)
    employee = c.client.get(f'/api/payroll/qr/resolve/1{c.employee_id:08d}', headers=c.headers)
    assert employee.status_code == 200 and employee.json()['employee_id'] == c.employee_id, employee.text
    work = c.client.get(f'/api/payroll/qr/resolve/2{ids[0]:08d}', headers=c.headers)
    assert work.status_code == 200, work.text
    assert work.json()['label_id'] == c.suffix + '-available-MIL'
    assert c.client.get(f'/api/payroll/qr/resolve/2{ids[2]:08d}', headers=c.headers).status_code == 409
    assert c.client.get('/api/payroll/qr/resolve/123', headers=c.headers).status_code == 400
    assert c.client.get(f'/api/payroll/qr/resolve/1{c.employee_id:08d}', headers=c.denied).status_code == 403
    assert _counts(c) == before
