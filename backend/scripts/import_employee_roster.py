"""Import a reviewed, numbered roster; dry-run by default. No payroll amounts."""
import argparse
import json
from pathlib import Path

from sqlalchemy import text
from app.db.session import SessionLocal
from app.models import Department, Employee, User
from app.services.audit import log_action


def import_roster(db, payload, actor, *, apply=False):
    if payload.get('factory_code') != 'ECO' or not payload.get('source_sha256'):
        raise ValueError('Expected a reviewed Eco Cotton source with its hash')
    rows = payload['records']
    numbers = [row['employee_no'] for row in rows]
    if not rows or any(not no.isdigit() for no in numbers) or len(set(numbers)) != len(numbers):
        raise ValueError('Every roster row needs a distinct numeric employee number')
    if db.bind.dialect.name == 'postgresql':
        db.execute(text("SELECT pg_advisory_xact_lock(1297047632, hashtext('employee-roster:ECO'))"))
    departments = {row.code: row.id for row in db.query(Department).filter(Department.code.in_(['ECO', 'ECT', 'ECP']))}
    if set(departments) != {'ECO', 'ECT', 'ECP'}:
        raise ValueError('Eco Cotton departments are missing')
    existing = db.query(Employee).filter_by(factory_code='ECO').all()
    by_number = {str(int(row.employee_no)): row for row in existing if row.employee_no and row.employee_no.isdigit()}
    additions, matched = [], []
    for row in rows:
        name = ' '.join(row['full_name'].split())
        if not name or len(name) > 255:
            raise ValueError('Invalid employee name')
        old = by_number.get(str(int(row['employee_no'])))
        if old:
            if ' '.join(old.full_name.split()).casefold() != name.casefold():
                raise ValueError(f"Employee number {row['employee_no']} belongs to another person")
            matched.append(old.id)
            continue
        if any(' '.join(old.full_name.split()).casefold() == name.casefold() for old in existing):
            raise ValueError('An existing employee has this name under another number; review before importing')
        group = row['source_sheet']
        department = 'ECT' if group.casefold() == 'kroy' else 'ECP' if group.upper() == 'UPAKOVKA' else 'ECO'
        additions.append((row, name, departments[department]))
    created = []
    if apply:
        for row, name, department_id in additions:
            employee = Employee(factory_code='ECO', employee_no=row['employee_no'], full_name=name,
                                department_id=department_id, position=row['source_sheet'], status='active',
                                hr_profile_json={'roster_source': payload['source'], 'roster_sha256': payload['source_sha256'],
                                                 'roster_sheet': row['source_sheet'], 'roster_row': row['source_row']})
            db.add(employee); db.flush()
            log_action(db, actor, 'import_roster', 'Employee', employee.id,
                       new_value={'factory_code': 'ECO', 'employee_no': employee.employee_no, 'source_sha256': payload['source_sha256']})
            created.append(employee.id)
    return {'source_rows': len(rows), 'to_create': len(additions), 'matched': len(matched), 'created': len(created), 'employee_ids': created}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('input', type=Path)
    parser.add_argument('--actor-id', type=int, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    with SessionLocal() as db:
        actor = db.get(User, args.actor_id)
        if not actor:
            raise ValueError('Audit actor not found')
        result = import_roster(db, json.loads(args.input.read_text(encoding='utf-8')), actor, apply=args.apply)
        if args.apply:
            db.commit()
        else:
            db.rollback()
        print(json.dumps(result))
