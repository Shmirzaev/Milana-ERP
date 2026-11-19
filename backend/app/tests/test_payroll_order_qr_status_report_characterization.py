from decimal import Decimal

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


def test_order_qr_report_aggregates_all_labels_independently_of_page(payroll_case):
    c = payroll_case
    order, ids = _labels(c)
    before = _counts(c)
    url = '/api/payroll/reports/order-qr-status'
    r = c.client.get(url, headers=c.headers, params={'order_no': order, 'limit': 1})
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body['total_labels'], body['scanned_labels'], body['available_labels']) == (2, 1, 1)
    assert (Decimal(body['total_quantity']), Decimal(body['scanned_quantity']), Decimal(body['available_quantity'])) == (20, 10, 10)
    assert body['total'] == 2 and len(body['items']) == 1
    assert body['sizes'] == ['L'] and body['operations'][0]['issued_labels'] == 2
    assert c.client.get(url, headers=c.headers).status_code == 400
    assert c.client.get(url, headers=c.headers, params={'order_no': order, 'status': 'closed'}).status_code == 400
    assert c.client.get(url, headers=c.denied, params={'order_no': order}).status_code == 403
    assert _counts(c) == before
