"""Per-factory overrides. Empty policies preserve historical account behavior."""
from app.core.permission_catalog import PERMISSION_KEYS

_WILDCARD_EXPANSION = tuple(sorted(PERMISSION_KEYS - {"*", "admin.super"}))


def policy_for(user, factory: str) -> dict:
    return (getattr(user, "access_policy", None) or {}).get(factory, {})


def denied_for(user, factory: str) -> set[str]:
    return set(policy_for(user, factory).get("deny", []))


def apply_policy(user, factory: str, permissions) -> list[str]:
    policy = policy_for(user, factory)
    grants = list(dict.fromkeys([*permissions, *policy.get("allow", [])]))
    denied = set(policy.get("deny", []))
    if not denied:
        return grants
    if "*" in grants:
        # A wildcard must not bypass an explicit denial. Preserve all named
        # capabilities, including legacy/custom role keys, then subtract denies.
        grants = list(dict.fromkeys([*grants, *_WILDCARD_EXPANSION]))
        grants.remove("*")
    return [permission for permission in grants if permission not in denied]


def permission_denied(user, permission: str) -> bool:
    from app.services.factory_scope import selected_factory_code
    return permission in denied_for(user, selected_factory_code(user))


def access_configured(user) -> bool:
    from app.services.factory_scope import selected_factory_code
    return selected_factory_code(user) in (getattr(user, "access_policy", None) or {})
