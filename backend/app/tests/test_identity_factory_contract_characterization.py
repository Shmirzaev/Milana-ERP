"""Factory identity contracts before canonical output/internal typing."""

import pytest
from fastapi import HTTPException

from app.libs.dto.catalog.catalog import UserOut
from app.models.factory_scope_service import normalize_factory_code
from app.schemas import User
from app.tests.test_idn01_factory_switch_characterization import (
    bearer, h, switch_database,  # noqa: F401 - pytest fixtures are used by name
)


@pytest.mark.parametrize("raw,expected", [
    ("MIL", "MIL"), (" bst ", "BST"), ("eco", "ECO"),
])
def test_normalized_factory_is_still_a_string_value(raw, expected, h):
    assert normalize_factory_code(raw) == expected


def test_unknown_factory_keeps_existing_400_detail(h):
    with pytest.raises(HTTPException) as error:
        normalize_factory_code("other")
    assert (error.value.status_code, error.value.detail) == (
        400, "Factory must be MIL, BST, or ECO",
    )


def test_me_selected_factory_and_admin_user_output_keep_json_values(h):
    factory, user_id, client = h
    me = client.get("/api/auth/me", headers=bearer(user_id, "ECO"))
    assert me.status_code == 200, me.text
    assert {key: me.json()[key] for key in (
        "factory_code", "assigned_factory_code", "available_factories",
    )} == {
        "factory_code": "ECO",
        "assigned_factory_code": "MIL",
        "available_factories": ["MIL", "ECO"],
    }
    with factory() as db:
        assigned = UserOut.model_validate(db.get(User, user_id)).model_dump(mode="json")
    assert assigned["factory_code"] == "MIL"
