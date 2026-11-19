from decimal import Decimal
from datetime import timedelta

from app.schemas import AuditLog, PayrollQrLabel, PayrollRecord
from app.tests.payroll_operation_fixture import payroll_case, payroll_postgres_sessions  # noqa: F401

def test_control_confirmation_closes_reviewed_work_and_replays_once(payroll_case):

    c = payroll_case
    rows = [
        {'label_uid': 'PENDING-' + c.suffix, 'batch_no': c.suffix[:12], 'size': 'L', 'operation_section': 'sewing', 'operation_name': 'Pending sewing', 'quantity': 12, 'rate_per_piece': 250},
        {'label_uid': 'CONTROL-' + c.suffix, 'batch_no': c.suffix[:12], 'size': 'L', 'operation_section': 'control', 'operation_name': 'Kontrol', 'quantity': 12, 'rate_per_piece': 250},
    ]
    issued = c.client.post('/api/payroll/qr-labels/issue', headers=c.headers, json={'labels': rows})
    assert issued.status_code == 200, issued.text
    control_uid = rows[1]['label_uid']
    body = {'label_uid': control_uid, 'employee_id': c.employee_id}

    preview = c.client.post('/api/payroll/scan/control-preview', headers=c.headers, json=body)
    assert preview.status_code == 200, preview.text
    body.update(review_token=preview.json()['review_token'], work_date=(c.stamp + timedelta(days=1)).date().isoformat(), close_unscanned=True, closure_reason='Reviewed unpaid work')
    url = '/api/payroll/scan/control-confirm'
    assert c.client.post(url, headers=c.denied, json=body).status_code == 403
    assert c.client.post(url, headers=c.headers, json={**body, 'review_token': 'changed'}).status_code == 409
    confirmed = c.client.post(url, headers=c.headers, json=body)
    assert confirmed.status_code == 201, confirmed.text
    rid = confirmed.json()['id']
    assert Decimal(confirmed.json()['total_amount']) == 3000
    # Closing changes the control review snapshot, so obtain the current token before replay.
    current = c.client.post('/api/payroll/scan/control-preview', headers=c.headers, json={'label_uid': control_uid, 'employee_id': c.employee_id})
    assert current.status_code == 200, current.text
    replay_body = {**body, 'review_token': current.json()['review_token']}
    retry = c.client.post(url, headers=c.headers, json=replay_body)
    assert retry.status_code == 201 and retry.json()['id'] == rid and retry.json()['duplicate'] is True, retry.text
    with c.sessions() as db:
        pending = db.query(PayrollQrLabel).filter_by(label_uid=rows[0]['label_uid']).one()
        control = db.query(PayrollQrLabel).filter_by(label_uid=control_uid).one()
        assert pending.status == 'closed' and control.status == 'scanned'
        assert pending.id in control.closure_details['closed_label_ids']
        assert db.query(PayrollRecord).filter_by(scan_uid=control_uid).count() == 1
        audit = db.query(AuditLog).filter_by(entity_type='PayrollQrLabel', entity_id=control.id, action='close_unscanned_qrs').one()
        assert audit.new_value_json['reason'] == 'Reviewed unpaid work' and audit.entry_hash
