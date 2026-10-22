from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.models import AuditLog, Department, Employee, PayrollRecord, User
from app.tests.conftest import TestSessionLocal
from app.tests.test_payroll import _create_user_with_permissions
from app.tests.test_payroll_control_confirmation import _issue
from scripts.besttex_master_teams import TEAMS, apply_teams, plan_hash, plan_teams


@pytest.mark.parametrize("factory", ["MIL", "BST", "ECO"])
def test_archive_preserves_employee_salary_links_and_can_be_restored(client, auth_headers, factory):
    headers = _create_user_with_permissions(client, auth_headers, email=f"archive-{factory}@example.com",
        permissions=["payroll.manage", "payroll.view"], factory_code=factory)
    employee = client.post("/api/employees", headers=headers, json={"full_name": "Archive target"}).json()
    eid = employee["id"]
    with TestSessionLocal() as db:
        record = PayrollRecord(factory_code=factory, employee_id=eid, dedupe_key=uuid4().hex,
            quantity=10, rate_per_piece=25, total_amount=250, scanned_at=datetime.now(timezone.utc))
        worker = Employee(factory_code=factory, full_name="Keep manager link", manager_employee_id=eid)
        db.add_all([record, worker]); db.commit(); rid, wid = record.id, worker.id
    assert client.post(f"/api/employees/{eid}/archive", headers=headers).status_code == 204
    assert client.post(f"/api/employees/{eid}/archive", headers=headers).status_code == 204
    assert not any(e["id"] == eid for e in client.get("/api/employees", headers=headers).json())
    listed = client.get("/api/employees?page=1&include_archived=true&search=Archive target", headers=headers).json()
    assert listed["total"] == 1 and listed["rows"][0]["status"] == "archived"
    assert listed["include_archived"] is True
    assert client.get(f"/api/payroll/employees/resolve?employee_no=EMP-{eid}", headers=headers).status_code == 404
    assert client.get(f"/api/payroll/qr/resolve/1{eid:08}", headers=headers).status_code == 404
    assert client.get(f"/api/employees/{eid}", headers=headers).json()["full_name"] == "Archive target"
    report = client.get(f"/api/payroll/reports/sewing-production?report_view=salary&employee_id={eid}", headers=headers).json()
    assert float(report["salary_summary"][0]["total_amount"]) == 250
    with TestSessionLocal() as db:
        assert db.get(Employee, wid).manager_employee_id == eid
        assert db.get(PayrollRecord, rid).employee_id == eid
        assert db.query(AuditLog).filter_by(entity_type="Employee", entity_id=eid, action="archive").count() == 1
    assert client.patch(f"/api/employees/{eid}", headers=headers, json={"status": "active"}).status_code == 200
    assert client.get(f"/api/payroll/employees/resolve?employee_no=EMP-{eid}", headers=headers).status_code == 200
    assert any(e["id"] == eid for e in client.get("/api/employees", headers=headers).json())


def test_archive_scope_permissions_and_legacy_delete(client, auth_headers):
    eid = client.post("/api/employees", headers=auth_headers, json={"full_name": "Keep this row"}).json()["id"]
    for permissions, factory, expected in [(["payroll.view"], "MIL", 403), (["payroll.manage"], "BST", 404)]:
        headers = _create_user_with_permissions(client, auth_headers, email=f"{factory}-{expected}@example.com",
                                               permissions=permissions, factory_code=factory)
        assert client.post(f"/api/employees/{eid}/archive", headers=headers).status_code == expected
    assert client.post(f"/api/employees/{eid}/archive").status_code == 401
    assert client.delete(f"/api/employees/{eid}", headers=auth_headers).status_code == 204
    with TestSessionLocal() as db:
        assert db.get(Employee, eid).status == "archived"


@pytest.mark.parametrize("control", [False, True])
def test_archived_employee_cannot_accrue_new_scanned_work(client, auth_headers, control):
    eid = client.post("/api/employees", headers=auth_headers, json={"full_name": "Archive scan target"}).json()["id"]
    label = _issue(client, auth_headers, operation_name="Kontrol" if control else "Tikuv",
                   operation_code="QC" if control else "SEW", operation_section="control" if control else "sewing")
    assert client.post(f"/api/employees/{eid}/archive", headers=auth_headers).status_code == 204
    response = client.post("/api/payroll/scan/numeric-work", headers=auth_headers,
                           json={"token": label["qr_token"], "employee_id": eid})
    assert response.status_code == 404, response.text
    with TestSessionLocal() as db:
        assert not db.query(PayrollRecord).filter_by(employee_id=eid).count()


def seed_teams(db):
    department = db.query(Department).filter_by(code="BST").one()
    master = Employee(full_name="Xaydarova Irodaxon", factory_code="BST", department_id=department.id,
                      hr_profile_json={"section": "Masterlar", "company": "Keep"})
    db.add(master)
    for section, _, count in TEAMS:
        db.add_all([Employee(full_name=f"{section} {n}", factory_code="BST", department_id=department.id,
                            hr_profile_json={"section": section}) for n in range(count)])
    db.flush()
    return master


def test_besttex_exact_teams_create_one_master_preserve_payroll_and_replay(client, auth_headers):
    with TestSessionLocal() as db:
        master = seed_teams(db)
        other = Employee(full_name="Unrelated", factory_code="BST", hr_profile_json={"section": "Kroy"})
        db.add(other); db.commit()
        mid, oid = master.id, other.id
        plan = plan_teams(db)
        actor = db.query(User).filter_by(email="admin@example.com").one()
        applied = apply_teams(db, actor, plan_hash(plan)); db.commit()
        assert [x["employee_count"] for x in applied] == [24, 44]
        assert applied[1]["master_id"] == mid
        assert db.get(Employee, oid).manager_employee_id is None
        assert db.get(Employee, mid).hr_profile_json["company"] == "Keep"
        assert not db.query(PayrollRecord).count()
        result = apply_teams(db, actor, plan_hash(plan_teams(db))); db.commit()
        assert result == applied
        assert db.query(Employee).filter_by(full_name="Isaqova Nigora", factory_code="BST").count() == 1


def test_team_plan_rejects_stale_roster_and_conflicting_manager(client, auth_headers):
    with TestSessionLocal() as db:
        seed_teams(db); db.commit()
        original = plan_hash(plan_teams(db))
        person = db.query(Employee).filter_by(full_name="Dazmol 0").one()
        person.full_name = "Changed roster"; db.commit()
        actor = db.query(User).filter_by(email="admin@example.com").one()
        with pytest.raises(AssertionError, match="Roster changed"):
            apply_teams(db, actor, original)
        assert not db.query(Employee).filter_by(full_name="Isaqova Nigora").count()
        person.manager_employee_id = db.query(Employee).filter_by(full_name="Xaydarova Irodaxon").one().id
        db.commit()
        with pytest.raises(AssertionError, match="Conflicting manager"):
            plan_teams(db)


def test_besttex_salary_options_and_export_follow_both_current_teams(client, auth_headers):
    from io import BytesIO
    from openpyxl import load_workbook

    headers = _create_user_with_permissions(client, auth_headers, email="besttex-teams@example.com",
        permissions=["payroll.manage", "payroll.view"], factory_code="BST")
    with TestSessionLocal() as db:
        seed_teams(db); db.commit()
        actor = db.query(User).filter_by(email="admin@example.com").one()
        teams = apply_teams(db, actor, plan_hash(plan_teams(db)))
        for employee in db.query(Employee).filter(Employee.manager_employee_id.in_([t["master_id"] for t in teams])):
            db.add(PayrollRecord(factory_code="BST", employee_id=employee.id, dedupe_key=uuid4().hex,
                quantity=1, rate_per_piece=100, total_amount=100,
                raw_work_json={"sewing_line_code": "OTHER"}, scanned_at=datetime.now(timezone.utc)))
        db.commit()
    options = client.get("/api/payroll/reports/sewing-production/options", headers=headers).json()
    for team in teams:
        selector = f"manager:{team['master_id']}"
        assert any(row["value"] == selector for row in options["salary_masters"])
        assert any(row["value"] == selector for row in options["sewing_lines"])
        url = f"/api/payroll/reports/sewing-production?report_view=salary&sewing_line={selector}"
        report = client.get(url, headers=headers).json()
        assert len(report["salary_summary"]) == team["employee_count"]
        assert all(row["master_name"] == team["master_name"] for row in report["salary_summary"])
        assert sum(float(row["total_amount"]) for row in report["salary_summary"]) == 100 * team["employee_count"]
        export = client.get(url.replace("sewing-production?", "sewing-production.xlsx?"), headers=headers)
        assert export.status_code == 200
        cells = str(list(load_workbook(BytesIO(export.content)).active.values))
        assert team["master_name"] in cells
        assert next(t["master_name"] for t in teams if t != team) not in cells
