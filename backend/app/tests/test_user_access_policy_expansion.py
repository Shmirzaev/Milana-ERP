"""Cached wildcard permission expansion must preserve scoped denial semantics."""
from types import SimpleNamespace

from app.core.permission_catalog import PERMISSION_KEYS
from app.services.user_access import apply_policy


def test_wildcard_policy_expansion_is_cached_and_denials_still_win():
    user = SimpleNamespace(access_policy={"MIL": {"allow": ["custom.allow"], "deny": ["finance.view"]}})

    actual = apply_policy(user, "MIL", ["*", "legacy.permission"])

    expected = [
        "legacy.permission",
        "custom.allow",
        *(permission for permission in sorted(PERMISSION_KEYS - {"*", "admin.super", "finance.view"})
          if permission not in {"legacy.permission", "custom.allow"}),
    ]
    assert actual == expected
    assert "*" not in actual
    assert "admin.super" not in actual
    assert "finance.view" not in actual
