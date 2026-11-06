
import importlib.util

import pytest
from sqlalchemy import event

from app.schemas import AuditLog, PayrollQrLabel, PayrollRecord
from app.tests.payroll_operation_fixture import payroll_case, payroll_postgres_sessions  # noqa: F401

@pytest.fixture
def issuance_case(payroll_case, monkeypatch):
    c = payroll_case
    if importlib.util.find_spec('app.models.people.payroll_qr_service'):
        from app.models.people.payroll_qr_service import issue_qr_labels
        for route in c.client.app.routes:
            if getattr(route, 'path', None) == '/api/payroll/qr-labels/issue':
                monkeypatch.setattr(route.dependant, 'call', issue_qr_labels)
    return c


def test_issue_duplicates_keep_one_label_and_audit(issuance_case):
    c = issuance_case
    uid = 'ISSUE-' + c.suffix
    row = {'label_uid': uid, 'quantity': 2, 'rate_per_piece': 25, 'operation_name': 'Synthetic sewing'}
    body = {'labels': [row, row]}
    assert c.client.post('/api/payroll/qr-labels/issue', headers=c.denied, json=body).status_code == 403
    first = c.client.post('/api/payroll/qr-labels/issue', headers=c.headers, json=body)
    assert first.status_code == 200, first.text
    assert (first.json()['issued_count'], first.json()['created_count'], first.json()['existing_count']) == (2, 1, 1)
    assert first.json()['labels'][0] == first.json()['labels'][1]
    retry = c.client.post('/api/payroll/qr-labels/issue', headers=c.headers, json=body)
    assert retry.status_code == 200, retry.text
    assert (retry.json()['created_count'], retry.json()['existing_count']) == (0, 2)
    conflict = c.client.post('/api/payroll/qr-labels/issue', headers=c.headers, json={'labels': [{**row, 'operation_name': 'Different payable work'}]})
    assert conflict.status_code == 409, conflict.text
    with c.sessions() as db:
        label = db.query(PayrollQrLabel).filter_by(label_uid=uid).one()
        assert label.status == 'available' and label.quantity == 2 and label.rate_per_piece == 25
        audit = db.query(AuditLog).filter_by(entity_type='PayrollQrLabel', entity_id=label.id, action='issue').one()
        assert audit.new_value_json['count'] == 1 and audit.entry_hash


def test_issue_failure_rolls_back_label_and_audit_then_retry(issuance_case):
    c = issuance_case
    uid = 'ROLLBACK-' + c.suffix
    row = {'label_uid': uid, 'operation_name': 'Retry sewing', 'quantity': 2, 'rate_per_piece': 25}
    def fail_commit(session):
        raise RuntimeError('characterized issue commit failure')
    event.listen(c.sessions.class_, 'before_commit', fail_commit)
    try:
        with pytest.raises(RuntimeError, match='characterized issue commit failure'):
            c.client.post('/api/payroll/qr-labels/issue', headers=c.headers, json={'labels': [row]})
    finally:
        event.remove(c.sessions.class_, 'before_commit', fail_commit)
    with c.sessions() as db:
        assert db.query(PayrollQrLabel).filter_by(label_uid=uid).count() == 0
        assert db.query(AuditLog).filter_by(entity_type='PayrollQrLabel', user_id=c.actor_id, action='issue').count() == 0
    retried = c.client.post('/api/payroll/qr-labels/issue', headers=c.headers, json={'labels': [row]})
    assert retried.status_code == 200 and retried.json()['created_count'] == 1, retried.text
    with c.sessions() as db:
        label = db.query(PayrollQrLabel).filter_by(label_uid=uid).one()
        assert db.query(AuditLog).filter_by(entity_type='PayrollQrLabel', entity_id=label.id, action='issue').count() == 1


def test_issue_duplicate_query_timing_and_batch_reads(issuance_case):
    c = issuance_case
    counts = []
    for size in (1, 20):
        prefix = f'BOUNDED-{c.suffix}-{size}'
        rows = [{'label_uid': f'{prefix}-{index}', 'operation_name': 'Batch sewing', 'quantity': 2, 'rate_per_piece': 25} for index in range(size)]
        statements = []
        engine = c.sessions.kw['bind']
        def capture(_connection, _cursor, statement, _parameters, _context, _many):
            statements.append(statement)
        event.listen(engine, 'before_cursor_execute', capture)
        try:
            result = c.client.post('/api/payroll/qr-labels/issue', headers=c.headers, json={'labels': rows})
        finally:
            event.remove(engine, 'before_cursor_execute', capture)
        assert result.status_code == 200 and result.json()['created_count'] == size, result.text
        counts.append(sum(statement.lstrip().upper().startswith('SELECT') for statement in statements))
        label_insert = next(index for index, sql in enumerate(statements) if sql.lstrip().upper().startswith('INSERT INTO PAYROLL_QR_LABELS'))
        record_read = next(index for index, sql in enumerate(statements) if sql.lstrip().upper().startswith('SELECT') and 'FROM payroll_records' in sql)
        assert label_insert < record_read
    assert counts[1] <= counts[0] + 1, counts


def test_issue_links_existing_scan_after_flush_and_validation_order(issuance_case):
    c = issuance_case
    uid = 'SCANNED-' + c.suffix
    with c.sessions() as db:
        record = db.get(PayrollRecord, c.record_id)
        record.scan_uid = uid
        db.commit()
    row = {'label_uid': uid, 'operation_name': 'Existing scan', 'quantity': 10, 'rate_per_piece': 250}
    issued = c.client.post('/api/payroll/qr-labels/issue', headers=c.headers, json={'labels': [row, row]})
    assert issued.status_code == 200, issued.text
    assert (issued.json()['created_count'], issued.json()['existing_count']) == (1, 1)
    with c.sessions() as db:
        label = db.query(PayrollQrLabel).filter_by(label_uid=uid).one()
        assert label.status == 'scanned' and label.payroll_record_id == c.record_id and label.last_scanned_at == db.get(PayrollRecord, c.record_id).scanned_at
    invalid = c.client.post('/api/payroll/qr-labels/issue', headers=c.headers, json={'labels': [dict(row, label_uid='FAIL-' + c.suffix, sewing_flow_id=99999999), dict(row, label_uid='')]})
    assert invalid.status_code == 404 and invalid.json()['detail'] == 'Sewing line was not found in this factory'
    with c.sessions() as db:
        assert db.query(PayrollQrLabel).filter_by(label_uid='FAIL-' + c.suffix).count() == 0
