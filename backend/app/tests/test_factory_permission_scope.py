from __future__ import annotations

from types import SimpleNamespace

from app.core.deps import factory_codes_with_permission
from app.services.factory_scope import available_factory_codes


def _user(
    *,
    factory_code="MIL",
    role_name="Planner",
    role_permissions=(),
    extra_permissions=(),
    access_policy=None,
):
    return SimpleNamespace(
        role=SimpleNamespace(name=role_name, permissions=list(role_permissions)),
        department=SimpleNamespace(code="PLN"),
        factory_code=factory_code,
        extra_permissions=list(extra_permissions),
        access_policy=access_policy or {},
        session_factory_code=factory_code,
    )


def test_factory_permission_scope_uses_primary_factory_global_permissions():
    user = _user(role_permissions=["forecasting.view"])

    assert factory_codes_with_permission(user, "forecasting.view") == ["MIL"]


def test_factory_permission_scope_finds_secondary_grant_and_filters_other_grants():
    user = _user(
        role_permissions=["planning.production"],
        extra_permissions=[
            "factory:ECO:forecasting.view",
            "factory:BST:usluga.view",
        ],
    )

    assert available_factory_codes(user) == ["MIL", "BST", "ECO"]
    assert factory_codes_with_permission(user, "forecasting.view") == ["ECO"]


def test_factory_permission_scope_honors_per_factory_denials():
    user = _user(
        role_permissions=["forecasting.view"],
        extra_permissions=["factory:ECO:forecasting.view"],
        access_policy={
            "MIL": {"deny": ["forecasting.view"]},
            "ECO": {"deny": ["forecasting.view"]},
        },
    )

    assert factory_codes_with_permission(user, "forecasting.view") == []


def test_super_admin_scope_includes_all_factories_but_respects_factory_denials():
    user = _user(
        role_name="Super Admin",
        role_permissions=["*", "admin.super"],
        access_policy={"ECO": {"deny": ["forecasting.view"]}},
    )

    assert factory_codes_with_permission(user, "forecasting.view") == ["MIL", "BST"]

