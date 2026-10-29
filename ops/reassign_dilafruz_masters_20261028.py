"""Owner-authorized exact master links; never merge people or move earnings.

Execute inside the existing backend container, after a verified backup. Default
is a rollback rehearsal; apply is an explicit caller choice. No runtime install.
"""
import importlib
import json
from sqlalchemy import event, text


def reassign(db, *, apply=False):
    # The existing audit chain finalizer requires READ COMMITTED. Lock exactly
    # the reviewed employees and attribute changed rows to our transaction ID.
    # Concurrent factory work remains independent; no broad table locks.
    db.execute(text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED"))
    db.execute(text("SET LOCAL lock_timeout='5s'"))
    db.execute(text("SET LOCAL statement_timeout='30s'"))
    targets = db.execute(text(
        "SELECT id,employee_no,full_name,factory_code FROM employees "
        "WHERE id IN (129,313,1581,1587) ORDER BY id FOR UPDATE"
    )).mappings().all()
    rows = {r['id']: r for r in targets}
    assert set(rows) == {129, 313, 1581, 1587}, 'Reviewed employee missing'
    assert all(r['factory_code'] == 'MIL' for r in rows.values()), 'Factory changed'
    assert rows[129]['employee_no'] == '503' and rows[313]['employee_no'] == '321'
    assert rows[129]['full_name'] == rows[313]['full_name'] == 'Akbarova Dilafruz'
    reports = db.execute(text(
        'SELECT id FROM employees WHERE manager_employee_id=129 ORDER BY id FOR UPDATE'
    )).scalars().all()
    assert reports == [1581, 1587], 'Direct reports changed; review again'
    assert db.execute(text('SELECT manager_employee_id FROM employees WHERE id=313')).scalar() != 129
    ancestor = 313
    visited = set()
    while ancestor is not None:
        assert ancestor not in visited and ancestor not in {1581, 1587}, 'Target master ancestry would create a cycle'
        visited.add(ancestor)
        ancestor = db.execute(text('SELECT manager_employee_id FROM employees WHERE id=:eid FOR UPDATE'),
                              {'eid': ancestor}).scalar()

    # Reject unreviewed trigger/rule side effects (xmin does not detect DELETE).
    assert db.execute(text(
        "SELECT count(*) FROM pg_trigger WHERE NOT tgisinternal AND tgrelid IN "
        "(CAST('employees' AS regclass),CAST('audit_logs' AS regclass))"
    )).scalar_one() == 0, 'Custom employee/audit triggers require review'
    assert db.execute(text(
        "SELECT count(*) FROM pg_rules WHERE schemaname=current_schema() "
        "AND tablename IN ('employees','audit_logs')"
    )).scalar_one() == 0, 'Custom employee/audit rules require review'
    xid = db.execute(text('SELECT (txid_current() % 4294967296)::text')).scalar_one()
    def employee_snapshot():
        return dict(db.execute(text(
            "SELECT id,to_jsonb(e)-'manager_employee_id'-'updated_at' FROM employees e "
            "WHERE id IN (129,313,1581,1587) ORDER BY id"
        )).all())

    before = employee_snapshot()
    tables = db.execute(text(
        "SELECT tablename FROM pg_tables WHERE schemaname=current_schema() "
        "AND tablename NOT IN ('employees','audit_logs','alembic_version') ORDER BY tablename"
    )).scalars().all()
    try:
        log_action = importlib.import_module('app.models.audit_service').log_action
    except ModuleNotFoundError as exc:
        if exc.name not in {'app.models.audit_service', 'app.models'}:
            raise
        log_action = importlib.import_module('app.services.audit').log_action
    result = db.execute(text(
        'UPDATE employees SET manager_employee_id=313,updated_at=now() '
        'WHERE id IN (1581,1587) AND factory_code=\'MIL\' AND manager_employee_id=129 RETURNING id'
    )).scalars().all()
    assert sorted(result) == [1581, 1587]
    for eid in sorted(result):
        log_action(db, None, 'reassign_employee_master', 'Employee', eid,
                   old_value={'manager_employee_id': 129, 'manager_employee_no': '503'},
                   new_value={'manager_employee_id': 313, 'manager_employee_no': '321',
                              'reason': 'Owner requested master reassignment only; both Dilafruz employees remain separate'})
    evidence = {'changed_employee_ids': sorted(result), 'from_employee_no': '503',
                'to_employee_no': '321', 'checked_unmodified_tables': len(tables),
                'transaction_id': xid, 'employee_identity_preserved': True, 'applied': apply}

    class RehearsalRollback(Exception):
        pass

    def verify_before_commit(session):
        # Registered AFTER log_action's audit finalizer, so the actual audit
        # commit path is checked even during a rollback rehearsal.
        session.flush()
        assert before == employee_snapshot(), 'Employee identity or other fields changed'
        own_rows = session.execute(text(
            'SELECT id,manager_employee_id FROM employees WHERE xmin::text=:xid ORDER BY id'
        ), {'xid': xid}).all()
        assert own_rows == [(1581, 313), (1587, 313)], 'Unexpected employee writes in this transaction'
        for table in tables:
            assert table.replace('_', '').isalnum()
            changed = session.execute(text(
                f'SELECT count(*) FROM "{table}" WHERE xmin::text=:xid'
            ), {'xid': xid}).scalar_one()
            assert changed == 0, 'Unexpected business writes in this transaction: ' + table
        audits = session.execute(text(
            "SELECT id,entity_id,action,old_value_json,new_value_json,prev_hash,entry_hash "
            "FROM audit_logs WHERE xmin::text=:xid ORDER BY id"
        ), {'xid': xid}).all()
        assert [row.entity_id for row in audits] == [1581, 1587], 'Exact audit rows missing'
        assert all(row.action == 'reassign_employee_master' and row.entry_hash
                   and row.old_value_json == {'manager_employee_id': 129, 'manager_employee_no': '503'}
                   and row.new_value_json['manager_employee_id'] == 313
                   and row.new_value_json['manager_employee_no'] == '321' for row in audits)
        assert audits[1].prev_hash == audits[0].entry_hash, 'New audit links do not match'
        evidence['audit_ids'] = [row.id for row in audits]
        if not apply:
            raise RehearsalRollback()

    event.listen(db, 'before_commit', verify_before_commit)
    try:
        db.commit()
    except RehearsalRollback:
        db.rollback()
    finally:
        event.remove(db, 'before_commit', verify_before_commit)
    return evidence


if __name__ == '__main__':
    import sys
    from app.db.session import SessionLocal
    with SessionLocal() as session:
        print(json.dumps(reassign(session, apply='--apply' in sys.argv)))
