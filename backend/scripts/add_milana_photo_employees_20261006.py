"""Add only the two missing people from the owner's three-person photo.

2495 is already present under her full legal name and must remain unchanged.
Dry-run by default; run --apply only for the explicitly authorized data change.
"""
import argparse
import json

from app.api.routes.hr import EmployeeIn, create_employee
from app.core.deps import user_permissions
from app.db.session import SessionLocal
from app.models import Department, Employee, Role, User

EXPECTED_EXISTING_NAME = "Алматова Мадинабону Абдумўмин қизи"
MISSING = [("2910", "Abdurahimova Muxarram"), ("2905", "Qodirova Umida")]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    with SessionLocal() as db:
        existing = db.query(Employee).filter_by(factory_code="MIL", employee_no="2495").one()
        assert existing.full_name == EXPECTED_EXISTING_NAME and existing.status == "active"
        packaging = db.query(Department).filter_by(code="PKG").one()
        assert existing.department_id == packaging.id
        actor = (db.query(User).join(Role).filter(Role.name == "Super Admin", User.is_active.is_(True))
                 .order_by(User.id).first())
        assert actor and "*" in user_permissions(actor), "Active super admin audit actor required"
        actor.session_factory_code = "MIL"
        planned = []
        for number, name in MISSING:
            found = db.query(Employee).filter_by(factory_code="MIL", employee_no=number).one_or_none()
            if found:
                assert found.full_name == name and found.department_id == packaging.id and found.position == "dazmolchi"
                planned.append({"employee_no": number, "full_name": name, "state": "already_exists", "id": found.id})
            else:
                assert not db.query(Employee.id).filter_by(factory_code="MIL", full_name=name).first()
                planned.append({"employee_no": number, "full_name": name, "state": "create"})
        for row in planned:
            if args.apply and row["state"] == "create":
                created = create_employee(EmployeeIn(employee_no=row["employee_no"], full_name=row["full_name"],
                    department_id=packaging.id, position="dazmolchi", status="active"), db, actor)
                row["id"] = created["id"]
                row["state"] = "created"
        print(json.dumps({"applied": args.apply, "preserved_employee_no": "2495", "employees": planned}, ensure_ascii=False))


if __name__ == "__main__":
    main()
