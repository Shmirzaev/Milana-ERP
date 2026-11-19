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


def test_order_qr_options_count_selected_factory_and_hide_superseded(payroll_case):
    c = payroll_case
    order, ids = _labels(c)
    before = _counts(c)
    r = c.client.get('/api/payroll/reports/order-qr-status/orders', headers=c.headers, params={'search': c.suffix, 'limit': 1})
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1
    assert r.json()[0]['order_no'] == order and r.json()[0]['label_count'] == 2
    assert c.client.get('/api/payroll/reports/order-qr-status/orders', headers=c.denied).status_code == 403
    assert _counts(c) == before
