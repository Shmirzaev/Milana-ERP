"""Role operations; callers supply the authenticated HTTP context and Session."""
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.deps import SUPER_ADMIN_ROLE_NAME, is_super_admin, normalize_permissions, require_permissions
from app.libs.dto.catalog.catalog import RoleIn
from app.models.audit_service import log_action
from app.models.identity.access_service import _assert_can_grant_permissions
from app.schemas.identity.role_persistence import add_role

from app.schemas import Role, User


def list_roles(db: Session) -> list[Role]:
    """Read every role for an authenticated account; no transaction is committed."""
    return db.query(Role).all()


def create_role(db: Session, payload: RoleIn, current: User) -> Role:
    """Check grants, insert the role and its audit row, then commit once."""
    require_permissions("*")(current)
    permissions = normalize_permissions(payload.permissions)
    if payload.name.strip().lower() == SUPER_ADMIN_ROLE_NAME.lower() and not is_super_admin(current):
        raise HTTPException(403, "Only a super admin can create the super admin role")
    _assert_can_grant_permissions(current, permissions)
    if len(payload.name) > 64:
        raise HTTPException(422, "Role name must be at most 64 characters")
    r = add_role(db, name=payload.name, permissions=permissions)
    log_action(db, current, "create", "Role", r.id, new_value={"name": r.name})
    db.commit()
    db.refresh(r)
    return r
