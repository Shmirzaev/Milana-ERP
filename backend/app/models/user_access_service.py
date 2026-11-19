"""Per-factory overrides. Empty policies preserve historical account behavior."""
from app.models.identity.access_policy_service import (
    apply_policy as apply_policy,
    denied_for as denied_for,
    policy_for as policy_for,
)


def permission_denied(user, permission: str) -> bool:
    from app.models.factory_scope_service import selected_factory_code
    return permission in denied_for(user, selected_factory_code(user))


def access_configured(user) -> bool:
    from app.models.factory_scope_service import selected_factory_code
    return selected_factory_code(user) in (getattr(user, "access_policy", None) or {})
