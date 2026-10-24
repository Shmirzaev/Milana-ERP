"""Reviewed employee consolidation. No commit: caller must rehearse and back up first."""
from copy import deepcopy
from sqlalchemy import update, select
from app.db.base import Base
from app.models import Employee, SystemSetting
from app.models.audit_service import log_action
from app.models.employee_names_service import latin_employee_name


def reconcile_employees(db, plan):
    ids = {n['id'] for n in plan['names']} | {n[k] for n in plan['merges'] for k in ('source', 'target')} | {plan['report_manager']}
    employees = {e.id: e for e in db.query(Employee).filter(Employee.id.in_(ids)).order_by(Employee.id).with_for_update().all()}
    assert set(employees) == ids, 'Reviewed employee disappeared'
    for change in plan['names']:
        employee = employees[change['id']]
        assert employee.full_name == change['old'], 'Name changed since review'
        assert latin_employee_name(change['old']) == change['new']
        log_action(db, None, 'normalize_name', 'Employee', employee.id,
                   old_value={'full_name': employee.full_name}, new_value={'full_name': change['new'], 'reason': 'Owner requested Latin names and spelling cleanup'})
        employee.full_name = change['new']
    db.flush()
    counts = {}
    for merge in plan['merges']:
        source, target = employees[merge['source']], employees[merge['target']]
        assert source.factory_code == target.factory_code == merge['factory']
        assert source.full_name == target.full_name == merge['name']
        assert source.employee_no == merge['source_no'] and target.employee_no == merge['target_no']
        snapshot = lambda employee: {c.name: deepcopy(getattr(employee, c.name)) for c in Employee.__table__.columns}
        before = {'source': snapshot(source), 'target': snapshot(target)}
        key = f'employee_merge_aliases:{source.factory_code}'
        setting = db.query(SystemSetting).filter(SystemSetting.key == key).with_for_update().first()
        if not setting:
            setting = SystemSetting(key=key, value_json={'ids': {}, 'numbers': {}})
            db.add(setting)
        aliases = deepcopy(setting.value_json)
        for group in ('ids', 'numbers'):
            aliases.setdefault(group, {})
            aliases[group] = {k: target.id if v == source.id else v for k, v in aliases[group].items()}
        aliases['ids'][str(source.id)] = target.id
        aliases['numbers'][source.employee_no or str(source.id)] = target.id
        setting.value_json = aliases
        moved = {}
        # Includes self-references, HR documents/events, model owners and the payroll ledger.
        for table in Base.metadata.tables.values():
            for column in table.columns:
                if any(fk.target_fullname == 'employees.id' for fk in column.foreign_keys):
                    result = db.execute(update(table).where(column == source.id).values({column.name: target.id}))
                    if result.rowcount:
                        moved[f'{table.name}.{column.name}'] = result.rowcount
        if source.status == 'active':
            target.status = 'active'
        if target.user_id is None:
            target.user_id = source.user_id
        # Conflicting profile fields remain in the audit; only missing fields are filled.
        target.hr_profile_json = {**(source.hr_profile_json or {}), **(target.hr_profile_json or {})}
        db.flush()
        db.refresh(target)
        if target.manager_employee_id == target.id:
            target.manager_employee_id = None
        log_action(db, None, 'merge_employee', 'Employee', target.id, old_value=before,
                   new_value={'source_id': source.id, 'target_id': target.id, 'moved': moved,
                              'reason': 'Owner explicitly requested merging all identical full names within each factory; old badges retained as aliases'})
        db.delete(source)
        db.flush()
        counts[str(source.id)] = moved
    manager = employees[plan['report_manager']]
    assert manager.factory_code == 'MIL' and manager.employee_no == '322'
    assert manager.full_name.startswith('Aliyeva Mushtariy')
    old_profile = deepcopy(manager.hr_profile_json or {})
    manager.hr_profile_json = {**old_profile, 'payroll_report_group': True}
    log_action(db, None, 'enable_payroll_report_group', 'Employee', manager.id,
               old_value={'hr_profile_json': old_profile},
               new_value={'hr_profile_json': manager.hr_profile_json, 'reason': 'Owner requested packaging/pressing master only in production salary reports, without a Sewing flow'})
    db.flush()
    for merge in plan['merges']:
        for table in Base.metadata.tables.values():
            for column in table.columns:
                if any(fk.target_fullname == 'employees.id' for fk in column.foreign_keys):
                    assert db.execute(select(column).where(column == merge['source']).limit(1)).first() is None
    db.expire_all()
    return {'normalized_names': len(plan['names']), 'merged_employees': counts, 'report_manager': manager.id}
