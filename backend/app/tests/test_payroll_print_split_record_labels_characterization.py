from app.schemas import AuditLog, Employee, PayrollQrLabel, PayrollRecord
from app.tests.payroll_operation_fixture import payroll_case, payroll_postgres_sessions  # noqa: F401
from app.tests.test_payroll_scan_allocations import issue, scan


def test_print_split_record_labels_preserves_cards_refusals_and_no_writes(payroll_case):
    c=payroll_case
    with c.sessions() as db:
        other=Employee(factory_code='MIL',employee_no=c.suffix[:18]+'P',full_name='Print worker '+c.suffix,status='active')
        db.add(other);db.commit();other_id=other.id
    label=issue(c.client,c.headers)
    response=scan(c.client,c.headers,label,{'id':c.employee_id},work_date=(c.stamp.date()).isoformat())
    assert response.status_code==201,response.text
    rid=response.json()['record']['id']
    split=c.client.post(f'/api/payroll/records/{rid}/split',headers=c.headers,json={'parts':[{'employee_id':c.employee_id,'quantity':7},{'employee_id':other_id,'quantity':13}]})
    assert split.status_code==200,split.text
    with c.sessions() as db:
        before=tuple(db.query(model).count() for model in (AuditLog,PayrollQrLabel,PayrollRecord))
    url=f'/api/payroll/records/{rid}/split-labels/print'
    printed=c.client.get(url,headers=c.headers)
    assert printed.status_code==200,printed.text
    assert printed.headers['cache-control']=='no-store' and 'text/html' in printed.headers['content-type']
    assert 'Sew' in printed.text and 'Print worker' in printed.text
    assert c.client.get(url,headers=c.denied).status_code==403
    assert c.client.get(f'/api/payroll/records/{c.record_id}/split-labels/print',headers=c.headers).status_code==404
    with c.sessions() as db:
        assert tuple(db.query(model).count() for model in (AuditLog,PayrollQrLabel,PayrollRecord))==before
