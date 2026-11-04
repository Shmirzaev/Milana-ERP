"""Operator-only, reviewed BST roster handoff. No commit and no HTTP entry point.

The supplied plan freezes every roster row and both flows. No employee identity,
historical evidence, account or flow ID is rewritten. Production execution needs
its own reviewed plan and backup; merely importing this module performs no work.
"""
from copy import deepcopy
from hashlib import sha256
import json
from typing import TypedDict

from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session

from app.models.audit_service import log_action
from app.schemas import AuditLog, Employee, SewingFlow
from app.schemas.people.master_handoff_persistence import assign_current_master
from app.schemas.production.master_handoff_persistence import rename_current_master_flow


class HandoffRefused(ValueError):
    pass


class HandoffSpec(TypedDict):
    old_master_id: int
    new_master_id: int
    flow_id: int
    new_display_name: str


def fingerprint(value: dict) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=True).encode()).hexdigest()


def _employee(row: Employee) -> dict:
    # Only the two operational labels leave the private profile. All other
    # fields remain server-side and have a digest to detect concurrent drift.
    snapshot = {key: deepcopy(getattr(row, key)) for key in (
        "id", "factory_code", "full_name", "employee_no", "status", "user_id",
        "department_id", "hr_position_id", "manager_employee_id", "position",
    )}
    profile = row.hr_profile_json or {}
    snapshot["hr_profile_json"] = {key: deepcopy(profile[key]) for key in ("section", "workplace") if key in profile}
    snapshot["profile_other_sha256"] = fingerprint({key: value for key, value in profile.items()
                                                   if key not in {"section", "workplace"}})
    return snapshot


def _flow(row: SewingFlow) -> dict:
    return {key: getattr(row, key) for key in (
        "id", "factory_code", "name", "code", "description", "supervisor_id", "is_active",
    )}


def capture_plan(db: Session, specifications: list[HandoffSpec]) -> dict:
    """Read only: freeze exact old/new identities, roster membership and labels.

    Each specification supplies old_master_id, new_master_id, flow_id and
    new_display_name. The operator must separately verify the identities.
    """
    if not isinstance(specifications, list) or len(specifications) != 2:
        raise HandoffRefused("Exactly two reviewed BST flows are required")
    keys = {"old_master_id", "new_master_id", "flow_id", "new_display_name"}
    for item in specifications:
        if not isinstance(item, dict) or set(item) != keys:
            raise HandoffRefused("Incomplete or unknown specification fields")
        if any(type(item[key]) is not int or item[key] <= 0
               for key in ("old_master_id", "new_master_id", "flow_id")):
            raise HandoffRefused("Identifiers must be positive integer database IDs")
        if (not isinstance(item["new_display_name"], str)
                or not item["new_display_name"].strip()
                or item["new_display_name"] != item["new_display_name"].strip()
                or len(item["new_display_name"]) > 64):
            raise HandoffRefused("Invalid flow display name")
    olds = {item["old_master_id"] for item in specifications}
    news = {item["new_master_id"] for item in specifications}
    flows = {item["flow_id"] for item in specifications}
    if len(olds) != 2 or len(news) != 2 or len(flows) != 2 or olds & news:
        raise HandoffRefused("Master identities and flows must be distinct")
    people = db.scalars(select(Employee).where(or_(
        Employee.id.in_(olds | news), Employee.manager_employee_id.in_(olds | news),
    )).order_by(Employee.id).execution_options(populate_existing=True)).all()
    flow_rows = db.scalars(select(SewingFlow).where(SewingFlow.id.in_(flows))
                          .order_by(SewingFlow.id).execution_options(populate_existing=True)).all()
    if not (olds | news) <= {person.id for person in people} or len(flow_rows) != 2:
        raise HandoffRefused("A reviewed master or flow is missing")
    if any(row.factory_code != "BST" for row in [*people, *flow_rows]):
        raise HandoffRefused("Cross-factory relationship found")
    leaders = {row.id: row for row in people if row.id in olds | news}
    if any(row.status != "active" for row in leaders.values()):
        raise HandoffRefused("All reviewed leaders must be active")
    if any(row.manager_employee_id is not None for key, row in leaders.items() if key in olds):
        raise HandoffRefused("Old masters must be root leaders")
    if any(row.manager_employee_id in news for row in people):
        raise HandoffRefused("A new leader already has workers; review separately")
    if any(row.user_id is not None for row in leaders.values()):
        raise HandoffRefused("Linked login accounts require a separate account-access review")
    if any(row.supervisor_id is not None or not row.is_active for row in flow_rows):
        raise HandoffRefused("Flow supervisor/access or inactive-flow review required")
    return {"version": 1, "specifications": deepcopy(specifications),
            "employees": [_employee(row) for row in people], "flows": [_flow(row) for row in flow_rows]}


def preview_plan(plan: dict) -> dict:
    """Pure before/after calculation, also used by execution; no DB writes."""
    people = {row["id"]: deepcopy(row) for row in plan["employees"]}
    flows = {row["id"]: deepcopy(row) for row in plan["flows"]}
    incoming = {item["new_master_id"] for item in plan["specifications"]}
    counts = {}
    for item in plan["specifications"]:
        old_id, new_id = item["old_master_id"], item["new_master_id"]
        source = people[old_id]
        old_profile = source["hr_profile_json"] or {}
        section = old_profile.get("section")
        if not section or not str(source["position"] or "").endswith(" master"):
            raise HandoffRefused("Old master band metadata needs explicit review")
        flow = flows[item["flow_id"]]
        if old_profile.get("workplace") != flow["name"]:
            raise HandoffRefused("Master workplace and physical flow do not match")
        destination = people[new_id]
        profile = deepcopy(destination["hr_profile_json"] or {})
        profile.update(section=section, workplace=item["new_display_name"])
        destination.update(manager_employee_id=None, position=f"{section} master", hr_profile_json=profile)
        count = 0
        for before in plan["employees"]:
            if before["manager_employee_id"] != old_id or before["id"] in incoming:
                continue
            row = people[before["id"]]
            profile = deepcopy(before["hr_profile_json"] or {})
            if profile.get("workplace") == flow["name"]:
                profile["workplace"] = item["new_display_name"]
            position = before["position"]
            if position == f"{section} - {flow['name']}":
                position = f"{section} - {item['new_display_name']}"
            row.update(manager_employee_id=new_id, position=position, hr_profile_json=profile)
            count += 1
        flow["name"] = item["new_display_name"]
        counts[str(new_id)] = count
    return {"employees": [people[key] for key in sorted(people)],
            "flows": [flows[key] for key in sorted(flows)], "worker_counts": counts,
            "plan_sha256": fingerprint(plan)}


def apply_reviewed_plan(db: Session, plan: dict, *, reviewed_sha256: str,
                        backup_reference: str) -> dict:
    """Apply once in the caller's transaction; stale/mixed plans fail closed.

    PostgreSQL table locks prevent phantom roster additions by ordinary HR
    writers. Timeout makes this a bounded maintenance action, not an API call.
    Same-plan retries read the committed audit receipt and never replay writes.
    """
    digest = fingerprint(plan)
    if digest != reviewed_sha256 or plan.get("version") != 1:
        raise HandoffRefused("Plan digest/version does not match review")
    if not isinstance(backup_reference, str) or not backup_reference.strip():
        raise HandoffRefused("Verified backup reference is required")
    if db.new or db.dirty or db.deleted:
        raise HandoffRefused("Use a clean dedicated Session")
    if db.get_bind().dialect.name != "postgresql":
        raise HandoffRefused("Execution requires PostgreSQL locking; preview only on other databases")
    db.execute(text("SET LOCAL lock_timeout = '5s'"))
    db.execute(text("SET LOCAL statement_timeout = '15s'"))
    db.execute(text("LOCK TABLE employees, sewing_flows IN SHARE ROW EXCLUSIVE MODE"))
    receipt = db.scalars(select(AuditLog).where(
        AuditLog.action == "bst_master_handoff", AuditLog.entity_type == "BST roster",
    ).order_by(AuditLog.id.desc())).all()
    for row in receipt:
        if (row.new_value_json or {}).get("plan_sha256") == digest:
            spec = plan["specifications"]
            ids = {item[key] for item in spec for key in ("old_master_id", "new_master_id")}
            current_people = db.scalars(select(Employee).where(or_(Employee.id.in_(ids),
                Employee.manager_employee_id.in_(ids))).order_by(Employee.id)
                .execution_options(populate_existing=True)).all()
            current_flows = db.scalars(select(SewingFlow).where(SewingFlow.id.in_(
                [item["flow_id"] for item in spec])).order_by(SewingFlow.id)
                .execution_options(populate_existing=True)).all()
            expected = row.new_value_json
            if ([_employee(person) for person in current_people] != expected["employees"]
                    or [_flow(flow) for flow in current_flows] != expected["flows"]):
                raise HandoffRefused("Prior handoff receipt exists but current after-state has drifted")
            return {"plan_sha256": digest, "already_applied": True}
    current = capture_plan(db, plan["specifications"])
    if current != plan:
        raise HandoffRefused("Roster, identity or flow changed since review; capture a new plan")
    after = preview_plan(plan)
    employee_rows = {row.id: row for row in db.scalars(select(Employee)
        .where(Employee.id.in_([row["id"] for row in plan["employees"]]))
        .order_by(Employee.id).with_for_update()).all()}
    flow_rows = {row.id: row for row in db.scalars(select(SewingFlow)
        .where(SewingFlow.id.in_([row["id"] for row in plan["flows"]]))
        .order_by(SewingFlow.id).with_for_update()).all()}
    before_people = {row["id"]: row for row in plan["employees"]}
    for row in after["employees"]:
        if row != before_people[row["id"]]:
            assign_current_master(db, employee_rows[row["id"]], manager_id=row["manager_employee_id"],
                                  position=row["position"], profile=row["hr_profile_json"])
    for row in after["flows"]:
        rename_current_master_flow(db, flow_rows[row["id"]], name=row["name"])
    db.flush()
    for row in [*employee_rows.values(), *flow_rows.values()]:
        db.refresh(row)
    if ([_employee(employee_rows[key]) for key in sorted(employee_rows)] != after["employees"]
            or [_flow(flow_rows[key]) for key in sorted(flow_rows)] != after["flows"]):
        raise HandoffRefused("Readback does not match approved after-state")
    log_action(db, None, "bst_master_handoff", "BST roster", None,
               old_value=plan, new_value={**after, "backup_reference": backup_reference})
    return {"plan_sha256": digest, "already_applied": False, "worker_counts": after["worker_counts"]}
