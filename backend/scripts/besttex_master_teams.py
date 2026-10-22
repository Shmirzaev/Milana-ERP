"""Owner-requested Besttex HR assignments; review a plan before applying it."""
import argparse
import hashlib
import json

from sqlalchemy import select

from app.models import Department, Employee, User
from app.services.audit import log_action


TEAMS = (("Dazmol", "Isaqova Nigora", 24),
         ("Chistka-kontrol", "Xaydarova Irodaxon", 44))


def plan_teams(db, *, lock=False):
    query = select(Employee).where(Employee.factory_code == "BST").order_by(Employee.id)
    if lock:
        query = query.with_for_update()
    people = list(db.scalars(query))
    department = db.query(Department).filter_by(code="BST").one()
    result = {"factory": "BST", "department_id": department.id, "teams": []}
    for section, name, count in TEAMS:
        masters = [e for e in people if e.full_name == name]
        assert len(masters) <= 1, "Ambiguous master identity"
        master = masters[0] if masters else None
        assert master or section == "Dazmol", "Existing Chistka master missing"
        if master:
            assert master.status == "active" and master.department_id == department.id
            assert master.manager_employee_id is None, "Master already belongs to another team"
        workers = [e for e in people if (e.hr_profile_json or {}).get("section") == section
                   and (not master or e.id != master.id)]
        assert len(workers) == count, "Current roster changed; review a fresh plan"
        assert all(e.status == "active" and e.department_id == department.id for e in workers)
        for worker in workers:
            if worker.manager_employee_id in (None, master.id if master else None):
                continue
            # The owner separately confirmed this exact existing cross-team link.
            previous = db.get(Employee, worker.manager_employee_id)
            assert (section == "Chistka-kontrol" and worker.id == 791
                    and worker.full_name == "Xusanova Maftuna Abdullajon qizi"
                    and previous and previous.id == 888 and previous.factory_code == "BST"
                    and previous.full_name == "Xoliqova Kamola"), "Conflicting manager"
        result["teams"].append({"section": section, "master_name": name,
            "master_id": master.id if master else None,
            "master_profile": master.hr_profile_json if master else None,
            "workers": [{"id": e.id, "name": e.full_name, "manager_id": e.manager_employee_id,
                         "updated_at": str(e.updated_at)} for e in workers]})
    return result


def plan_hash(plan):
    return hashlib.sha256(json.dumps(plan, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def apply_teams(db, actor, expected_hash):
    plan = plan_teams(db, lock=True)
    assert plan_hash(plan) == expected_hash, "Roster changed since review"
    assert actor and actor.is_active, "Active audit actor required"
    result = []
    for team in plan["teams"]:
        master = db.get(Employee, team["master_id"]) if team["master_id"] else None
        if master is None:
            master = Employee(full_name=team["master_name"], factory_code="BST",
                department_id=plan["department_id"], position="Dazmol master", status="active",
                hr_profile_json={"section": "Masterlar", "payroll_report_group": True})
            db.add(master)
            db.flush()
            log_action(db, actor, "create", "Employee", master.id,
                       new_value={"full_name": master.full_name, "factory_code": "BST",
                                  "reason": "Owner requested Dazmol master"})
        elif (master.hr_profile_json or {}).get("payroll_report_group") is not True:
            old = dict(master.hr_profile_json or {})
            master.hr_profile_json = {**old, "payroll_report_group": True}
            log_action(db, actor, "update", "Employee", master.id,
                       old_value={"hr_profile_json": old},
                       new_value={"hr_profile_json": master.hr_profile_json})
        for row in team["workers"]:
            worker = db.get(Employee, row["id"])
            if worker.manager_employee_id == master.id:
                continue
            worker.manager_employee_id = master.id
            log_action(db, actor, "update", "Employee", worker.id,
                       old_value={"manager_employee_id": row["manager_id"]},
                       new_value={"manager_employee_id": master.id,
                                  "reason": "Owner requested current Besttex team assignment"})
        result.append({"master_id": master.id, "master_name": master.full_name,
                       "section": team["section"], "employee_count": len(team["workers"])})
    db.flush()
    return result


if __name__ == "__main__":
    from app.db.session import SessionLocal
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply-plan-sha256")
    parser.add_argument("--actor-id", type=int)
    args = parser.parse_args()
    with SessionLocal() as db:
        if args.apply_plan_sha256:
            assert args.actor_id, "Audit actor required"
            result = apply_teams(db, db.get(User, args.actor_id), args.apply_plan_sha256)
            db.commit()
            print(json.dumps(result, ensure_ascii=False))
        else:
            plan = plan_teams(db)
            print(json.dumps({"sha256": plan_hash(plan), "plan": plan}, ensure_ascii=False))
