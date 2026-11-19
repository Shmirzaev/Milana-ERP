
from app.schemas import AuditLog, PayrollQrLabel, PayrollRecord
from app.tests.payroll_operation_fixture import payroll_case, payroll_postgres_sessions  # noqa: F401

def test_control_preview_is_read_only_scoped_and_permission_checked(payroll_case):

    c = payroll_case
    rows = [
        {'label_uid': 'PENDING-' + c.suffix, 'batch_no': c.suffix[:12], 'size': 'L', 'operation_section': 'sewing', 'operation_name': 'Pending sewing', 'quantity': 12, 'rate_per_piece': 250},
        {'label_uid': 'CONTROL-' + c.suffix, 'batch_no': c.suffix[:12], 'size': 'L', 'operation_section': 'control', 'operation_name': 'Kontrol', 'quantity': 12, 'rate_per_piece': 250},
    ]
    issued = c.client.post('/api/payroll/qr-labels/issue', headers=c.headers, json={'labels': rows})
    assert issued.status_code == 200, issued.text
    control_uid = rows[1]['label_uid']
    body = {'label_uid': control_uid, 'employee_id': c.employee_id}

    with c.sessions() as db:
        before_records = db.query(PayrollRecord).filter_by(employee_id=c.employee_id).count()
        before_audits = db.query(AuditLog).filter_by(user_id=c.actor_id).count()
    assert c.client.post('/api/payroll/scan/control-preview', headers=c.denied, json=body).status_code == 403
    first = c.client.post('/api/payroll/scan/control-preview', headers=c.headers, json=body)
    assert first.status_code == 200, first.text
    assert {row['label_uid'] for row in first.json()['operations']} == {row['label_uid'] for row in rows}
    repeat = c.client.post('/api/payroll/scan/control-preview', headers=c.headers, json=body)
    assert repeat.status_code == 200 and repeat.json()['review_token'] == first.json()['review_token'], repeat.text
    with c.sessions() as db:
        assert db.query(PayrollRecord).filter_by(employee_id=c.employee_id).count() == before_records
        assert db.query(AuditLog).filter_by(user_id=c.actor_id).count() == before_audits
        assert db.query(PayrollQrLabel).filter_by(label_uid=control_uid).one().status == 'available'
