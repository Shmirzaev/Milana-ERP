"""Shared Identity grant and policy checks for account operations."""
from types import SimpleNamespace

from fastapi import HTTPException

from app.core.deps import (
    SUPER_ADMIN_PERMISSION, SUPER_ADMIN_ROLE_NAME, DbSession, is_super_admin,
    normalize_permissions, user_permissions, require_permissions,
)
from app.models.factory_scope_service import FACTORY_CODES, normalize_factory_code, selected_factory_code
from app.core.permission_catalog import PERMISSION_CATALOG
from app.core.permission_catalog import PERMISSION_KEYS
from app.libs.dto.catalog.catalog import UserIn
from app.models.factory_scope_service import available_factory_codes
from app.schemas import Department, Role, User


def _access_subject(db, values):
    role = db.get(Role, values.get("role_id")) if values.get("role_id") else None
    department = db.get(Department, values.get("department_id")) if values.get("department_id") else None
    if values.get("role_id") and role is None:
        raise HTTPException(404, "Role not found")
    if values.get("department_id") and department is None:
        raise HTTPException(404, "Department not found")
    return SimpleNamespace(
        role=role, department=department, name=values.get("name", ""), email=values.get("email", ""),
        factory_code=values.get("factory_code") or "MIL",
        extra_permissions=values.get("extra_permissions") or [], access_policy=values.get("access_policy") or {},
    )


def _user_access_values(user):
    return {key: getattr(user, key, None) for key in (
        "role_id", "department_id", "name", "email", "factory_code", "extra_permissions", "access_policy",
    )}


def _assert_policy_change(db, actor, values, old=None):
    proposed = _access_subject(db, values)
    for factory, policy in proposed.access_policy.items():
        if factory != proposed.factory_code and SUPER_ADMIN_PERMISSION in set(policy.get("allow", [])) | set(policy.get("deny", [])):
            raise HTTPException(400, "Super Admin access is configured in the primary factory only")
    if is_super_admin(actor):
        return proposed
    own = set(user_permissions(actor))
    previous = _access_subject(db, old) if old else None
    old_policy = (old or {}).get("access_policy") or {}
    for factory in FACTORY_CODES:
        policy = proposed.access_policy.get(factory, {})
        if policy == old_policy.get(factory, {}) and (factory not in proposed.access_policy) == (factory not in old_policy):
            continue
        if factory != selected_factory_code(actor):
            raise HTTPException(403, "Only Super Admin can configure another factory")
        proposed.session_factory_code = factory
        before = set()
        if previous:
            previous.session_factory_code = factory
            before = set(user_permissions(previous))
        after = set(user_permissions(proposed))
        if ({"*", SUPER_ADMIN_PERMISSION} & (set(policy.get("allow", [])) | (after - before))):
            raise HTTPException(403, "Only Super Admin can grant administrator access")
        # Removing a deny is also a grant; restoring a restrictive scope is not
        # allowed to become an indirect privilege-escalation route.
        if "*" not in own and ((after - before) - own):
            raise HTTPException(403, "You cannot grant permissions you don't hold")
        if "inventory.materials_only" in own and "inventory.materials_only" not in after:
            raise HTTPException(403, "You cannot remove your own inventory scope from another account")
    proposed.session_factory_code = proposed.factory_code
    return proposed


def _role_is_super_admin(role: Role | None) -> bool:
    if not role:
        return False
    role_name = (role.name or "").strip().lower()
    return role_name == SUPER_ADMIN_ROLE_NAME.lower() or SUPER_ADMIN_PERMISSION in (role.permissions or [])


def _permissions_grant_admin_control(permissions: list[str] | set[str]) -> bool:
    return "*" in permissions or SUPER_ADMIN_PERMISSION in permissions


def _role_grants_admin_control(role: Role) -> bool:
    return _role_is_super_admin(role) or _permissions_grant_admin_control(set(role.permissions or []))


def _future_is_super_admin(db: DbSession, role_id: int | None, extra_permissions: list[str] | None) -> bool:
    if role_id is not None:
        role = db.get(Role, role_id)
        if not role:
            raise HTTPException(404, "Role not found")
        if _role_is_super_admin(role):
            return True
    return SUPER_ADMIN_PERMISSION in normalize_permissions(extra_permissions)


def _assert_can_grant_role(db: DbSession, actor: User, role_id: int | None) -> None:
    """Prevent privilege escalation: a user-manager may only assign a role whose
    permissions are a subset of their own. Administrator roles require the
    explicit Super Admin tier, even if the actor already holds '*'."""
    if role_id is None:
        return
    role = db.get(Role, role_id)
    if not role:
        raise HTTPException(404, "Role not found")
    if _role_grants_admin_control(role):
        if not is_super_admin(actor):
            raise HTTPException(403, "Only a super admin can assign administrator roles")
        return
    _assert_can_grant_permissions(actor, role.permissions)


def _assert_can_grant_permissions(
    actor: User, permissions: list[str] | None, *, previous: list[str] | None = None,
) -> None:
    if is_super_admin(actor):
        return
    target_perms = set(normalize_permissions(permissions))
    previous_perms = set(normalize_permissions(previous))
    added = target_perms - previous_perms
    removed = previous_perms - target_perms
    actor_perms = set(user_permissions(actor))
    actor_factory = selected_factory_code(actor)
    missing = set()
    # Like access_policy, unchanged legacy grants must survive profile edits.
    # Check removals too: another factory's access is not ours to configure.
    for token in added | removed:
        permission = token
        if token.startswith("factory:"):
            parts = token.split(":", 2)
            if len(parts) != 3 or not parts[2].strip():
                raise HTTPException(400, "Invalid factory permission")
            factory = normalize_factory_code(parts[1])
            if factory != actor_factory:
                raise HTTPException(403, "Only Super Admin can configure another factory")
            permission = parts[2].strip()
        if token not in added:
            continue
        if permission in {"*", SUPER_ADMIN_PERMISSION}:
            raise HTTPException(403, "Only a super admin can grant administrator access")
        if "*" not in actor_perms and permission not in actor_perms:
            missing.add(permission)
    if missing:
        raise HTTPException(403, f"You cannot grant permissions you don't hold: {sorted(missing)}")


def _effective_permissions_for(db: DbSession, role_id: int | None, extra_permissions: list[str] | None) -> list[str]:
    permissions: list[str] = []
    if role_id is not None:
        role = db.get(Role, role_id)
        if not role:
            raise HTTPException(404, "Role not found")
        permissions.extend(role.permissions or [])
    permissions.extend(extra_permissions or [])
    return normalize_permissions(permissions)


def _require_active_admin_actor(actor: User) -> None:
    if actor is None or not actor.is_active:
        raise HTTPException(status_code=401, detail="Inactive or unknown user")
    require_permissions("admin.users", "*")(actor)


def get_access_catalog(actor: User) -> list[dict]:
    _require_active_admin_actor(actor)
    own = set(user_permissions(actor))
    return [{**row, "grantable": is_super_admin(actor) if row["key"] in {"*", SUPER_ADMIN_PERMISSION}
             else "*" in own or row["key"] in own} for row in PERMISSION_CATALOG]


def preview_user_access(db: DbSession, payload: UserIn, actor: User) -> dict:
    _require_active_admin_actor(actor)
    values = payload.model_dump(exclude={"password"})
    subject = _access_subject(db, values)
    available = available_factory_codes(subject)
    result = {}
    for factory in FACTORY_CODES:
        subject.session_factory_code = factory
        effective = user_permissions(subject)
        expanded = sorted((set(effective) - {"*"}) | (PERMISSION_KEYS - {"*", SUPER_ADMIN_PERMISSION} if "*" in effective else set()))
        result[factory] = {"permissions": effective, "effective": sorted(set(expanded) | ({"*"} if "*" in effective else set())), "available": factory in available}
    return result
