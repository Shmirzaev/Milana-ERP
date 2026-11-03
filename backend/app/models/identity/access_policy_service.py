"""Per-factory policy evaluation without authenticated factory context."""
from app.core.permission_catalog import PERMISSION_KEYS


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
        grants = list(dict.fromkeys([*grants, *sorted(PERMISSION_KEYS - {"*", "admin.super"})]))
        grants.remove("*")
    return [permission for permission in grants if permission not in denied]
