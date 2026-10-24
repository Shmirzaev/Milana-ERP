"""Factory-scoped badge aliases left by reviewed employee consolidations."""
from app.models import Employee, SystemSetting


def merged_employee(db, factory_code, *, employee_id=None, employee_no=None):
    key = f'employee_merge_aliases:{factory_code}'
    setting = db.query(SystemSetting.value_json).filter(SystemSetting.key == key).scalar()
    if not isinstance(setting, dict):
        return None
    aliases = setting.get('ids' if employee_id is not None else 'numbers', {})
    target = aliases.get(str(employee_id if employee_id is not None else employee_no))
    if not target:
        return None
    return db.query(Employee).filter(Employee.id == int(target), Employee.factory_code == factory_code).first()
