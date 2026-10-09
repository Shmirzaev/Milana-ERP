"""Explicit, transactional provisioning; never called by startup or migration."""
from sqlalchemy import func
from app.core.security import hash_password
from app.models import Department, Role, SewingAssignment, SewingFlow, User, WorkOrder
from app.services.audit import log_action

BAND_PERMISSIONS = ["sewing.workspace", "sewing.bundles", "sewing.records"]


def configure_eco_bands(db, actor, password=None, *, apply=False):
    flows = db.query(SewingFlow).filter(SewingFlow.factory_code == "ECO").order_by(SewingFlow.id).with_for_update().all()
    by_code = {flow.code: flow for flow in flows}
    wanted = [f"ECO-BAND-{n:02}" for n in range(1, 11)]
    if any(code not in by_code for code in wanted):
        raise ValueError("Expected Eco bands 1–10 must already exist")
    retiring = [f for f in flows if f.is_active and f.code not in wanted]
    retiring_ids = [f.id for f in retiring]
    if db.query(SewingAssignment.id).filter(SewingAssignment.sewing_flow_id.in_(retiring_ids), SewingAssignment.status.in_(("planned", "in_progress"))).first():
        raise ValueError("A retiring band still has assigned work; review reassignment first")
    if db.query(WorkOrder.id).filter(WorkOrder.sewing_flow_id.in_(retiring_ids), WorkOrder.status.notin_(("completed", "cancelled"))).first():
        raise ValueError("A retiring band still has a direct work order")
    department = db.query(Department).filter(Department.code == "ECO").one()
    role = db.query(Role).filter(Role.name == "Eco Band").first()
    if role and set(role.permissions) != set(BAND_PERMISSIONS):
        raise ValueError("Existing Eco Band role differs from the reviewed permissions")
    emails = [f"band{n}@milanapremium.uz" for n in range(1, 11)]
    existing = {u.email.lower(): u for u in db.query(User).filter(func.lower(User.email).in_(emails)).with_for_update(of=User).all()}
    for n, email in enumerate(emails, 1):
        user = existing.get(email)
        if user and (user.sewing_band_id != by_code[f"ECO-BAND-{n:02}"].id or user.factory_code != "ECO" or not role or user.role_id != role.id):
            raise ValueError(f"Existing account {email} has different access; it was not changed")
    result = {"retire": [f.code for f in retiring], "create": [e for e in emails if e not in existing], "keep": [e for e in emails if e in existing]}
    if not apply:
        return result
    if not password:
        raise ValueError("Password must be supplied securely at provisioning time")
    if not role:
        role = Role(name="Eco Band", permissions=BAND_PERMISSIONS)
        db.add(role); db.flush()
        log_action(db, actor, "create", "Role", role.id, new_value={"name": role.name, "permissions": BAND_PERMISSIONS})
    for flow in retiring:
        flow.is_active = False
        log_action(db, actor, "retire", "SewingFlow", flow.id, old_value={"is_active": True}, new_value={"is_active": False})
    for n, email in enumerate(emails, 1):
        flow = by_code[f"ECO-BAND-{n:02}"]
        if not flow.is_active:
            flow.is_active = True
            log_action(db, actor, "activate", "SewingFlow", flow.id, new_value={"is_active": True})
        if email in existing:
            continue  # Never reset existing passwords on a retry.
        user = User(name=f"Band {n}", email=email, password_hash=hash_password(password), role_id=role.id,
                    department_id=department.id, factory_code="ECO", sewing_band_id=flow.id, is_active=True,
                    extra_permissions=[])
        db.add(user); db.flush()
        log_action(db, actor, "create_band_account", "User", user.id,
                   new_value={"email": email, "factory_code": "ECO", "sewing_band_id": flow.id})
    return result
