"""DB03-MODEL: every write path that persists ``Model.details_json`` must bound
the serialized size, the nesting depth, and the JSON-compatibility of the
document, while leaving exact already-stored legacy values editable.
"""

import json
from copy import deepcopy
from uuid import uuid4

import pytest

from app.models import AuditLog, Item, Model, ModelBOM
from app.tests.conftest import TestSessionLocal

_MAX_DETAILS_BYTES = 64 * 1024
_MAX_DETAILS_DEPTH = 16

# 400 levels is 25x the ceiling and still parses: the stdlib JSON body decoder
# (not this validator) starts raising RecursionError somewhere past ~1000, so a
# depth this large proves the rejection comes from the walk and not the parser.
_DEEP_REQUEST_LEVELS = 400

# Cyrillic "ж" is 2 UTF-8 bytes, so this is comfortably past the byte ceiling
# while keeping the request body small.
_OVERSIZED_FILL = "ж" * (_MAX_DETAILS_BYTES // 2 + 1)


def _code(tag: str) -> str:
    return f"DB03-{tag}-{uuid4().hex[:8].upper()}"


def _create_model(client, headers, code: str, details: dict | None = None, name: str = "Bounded"):
    response = client.post(
        "/api/models",
        headers=headers,
        json={"code": code, "name": name, "details_json": details if details is not None else {}},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _details(mid: int) -> dict:
    with TestSessionLocal() as db:
        return deepcopy(db.get(Model, mid).details_json)


def _set_details(mid: int, details: object) -> None:
    with TestSessionLocal() as db:
        db.get(Model, mid).details_json = details
        db.commit()


def _counts() -> tuple[int, int]:
    with TestSessionLocal() as db:
        return db.query(Model.id).count(), db.query(AuditLog.id).count()


def _add_fabric_bom(mid: int, tag: str) -> None:
    with TestSessionLocal() as db:
        item = Item(sku=f"DB03-FAB-{tag}", name="DB03 fabric", category="fabric", unit="m")
        db.add(item)
        db.flush()
        db.add(ModelBOM(model_id=mid, item_id=item.id, material_role="main", quantity_per_piece=1, unit="m"))
        db.commit()


def _deep_list_text(levels: int) -> str:
    return "[" * levels + '"leaf"' + "]" * levels


def _body_with_details(payload: dict, details_text: str) -> bytes:
    """Build a request body whose ``details_json`` is given as raw JSON text.

    ``json.dumps`` is itself recursive, so a document of this depth cannot be
    round-tripped through ``client.post(json=...)``; assemble the bytes instead.
    """
    parts = [f"{json.dumps(key)}:{json.dumps(value)}" for key, value in payload.items()]
    parts.append(f'"details_json":{details_text}')
    return ("{" + ",".join(parts) + "}").encode("utf-8")


def _post_raw(client, url: str, headers: dict, body: bytes):
    return client.post(
        url,
        headers={**headers, "Content-Type": "application/json"},
        content=body,
    )


def _patch_raw(client, url: str, headers: dict, body: bytes):
    return client.patch(
        url,
        headers={**headers, "Content-Type": "application/json"},
        content=body,
    )


# --------------------------------------------------------------------------
# 1. Catalog writers: direct create and direct update
# --------------------------------------------------------------------------


def test_model_create_rejects_oversized_details_without_insert(client, auth_headers):
    code = _code("CREATE")
    details = {"general": {"model_no": code}, "extension": _OVERSIZED_FILL}

    response = client.post(
        "/api/models",
        headers=auth_headers,
        json={"code": code, "name": "Oversized", "details_json": details},
    )

    assert response.status_code == 422, response.text
    assert "UTF-8 bytes" in response.text
    with TestSessionLocal() as db:
        assert db.query(Model.id).filter(Model.code == code).first() is None


def test_model_patch_rejects_oversized_details_without_write(client, auth_headers):
    code = _code("PATCH")
    model_id = _create_model(client, auth_headers, code, {"general": {"model_no": code}})
    before_details = _details(model_id)
    before_counts = _counts()

    response = client.patch(
        f"/api/models/{model_id}",
        headers=auth_headers,
        json={
            "code": code,
            "name": "Oversized",
            "details_json": {**before_details, "extension": _OVERSIZED_FILL},
        },
    )

    assert response.status_code == 422, response.text
    assert "UTF-8 bytes" in response.text
    assert _details(model_id) == before_details
    assert _counts() == before_counts


def test_model_create_rejects_non_finite_details(client, auth_headers):
    for label, value in (("nan", float("nan")), ("infinity", float("inf")), ("negative infinity", float("-inf"))):
        code = _code("NONFINITE")
        response = client.post(
            "/api/models",
            headers=auth_headers,
            json={"code": code, "name": "Non finite", "details_json": {"general": {"model_no": code}, "value": value}},
        )

        assert response.status_code == 422, f"{label}: {response.status_code} {response.text}"
        assert "finite" in response.text
        with TestSessionLocal() as db:
            assert db.query(Model.id).filter(Model.code == code).first() is None


# --------------------------------------------------------------------------
# 2. Depth: the walk must be iterative, so a far-too-deep body is refused with
#    a domain 4xx instead of blowing the Python stack.
# --------------------------------------------------------------------------


def test_model_create_rejects_deeply_nested_details_without_recursion_error(client, auth_headers):
    code = _code("DEEP")
    before = _counts()

    response = _post_raw(
        client,
        "/api/models",
        auth_headers,
        _body_with_details(
            {"code": code, "name": "Deep"},
            '{"extension":' + _deep_list_text(_DEEP_REQUEST_LEVELS) + "}",
        ),
    )

    assert response.status_code == 422, response.text
    assert "nested container levels" in response.text
    with TestSessionLocal() as db:
        assert db.query(Model.id).filter(Model.code == code).first() is None
    assert _counts() == before


def test_direct_validator_rejects_depth_far_beyond_the_ceiling_iteratively():
    """The validator itself must not recurse, even far past what a body can carry."""
    from app.api.routes.catalog import _validate_model_details_json_bounds

    value = "leaf"
    for _ in range(_DEEP_REQUEST_LEVELS * 20):
        value = [value]

    with pytest.raises(Exception) as raised:
        _validate_model_details_json_bounds({"extension": value})

    assert "nested container levels" in str(raised.value)


# --------------------------------------------------------------------------
# 3. Clones and variants: these build a details document instead of receiving
#    one, so they must be bounded too.
# --------------------------------------------------------------------------


def test_model_clone_rejects_oversized_source_details_without_writes(client, auth_headers):
    code = _code("CLONE")
    model_id = _create_model(client, auth_headers, code, {"general": {"model_no": code}})
    _set_details(model_id, {"general": {"model_no": code}, "extension": _OVERSIZED_FILL})
    before = _counts()

    response = client.post(f"/api/models/{model_id}/clone", headers=auth_headers)

    assert response.status_code == 422, response.text
    assert "UTF-8 bytes" in response.text
    assert _counts() == before


def test_model_clone_rejects_deep_source_details_without_writes(client, auth_headers):
    code = _code("CLONE-DEEP")
    model_id = _create_model(client, auth_headers, code, {"general": {"model_no": code}})
    deep = {"general": {"model_no": code}, "extension": "leaf"}
    for _ in range(_MAX_DETAILS_DEPTH + 5):
        deep = {"extension": deep}
    _set_details(model_id, deep)
    before = _counts()

    response = client.post(f"/api/models/{model_id}/clone", headers=auth_headers)

    assert response.status_code == 422, response.text
    assert "nested container levels" in response.text
    assert _counts() == before


def test_model_variant_create_rejects_oversized_source_details_without_writes(client, auth_headers):
    code = _code("VARIANT")
    model_id = _create_model(client, auth_headers, code, {"general": {"model_no": code}})
    _add_fabric_bom(model_id, "VARIANT")
    _set_details(model_id, {"general": {"model_no": code}, "extension": _OVERSIZED_FILL})
    before = _counts()

    response = client.post(f"/api/models/{model_id}/variants", headers=auth_headers, json={"variant_no": "V2"})

    assert response.status_code == 422, response.text
    assert "UTF-8 bytes" in response.text
    assert _counts() == before


def test_variant_update_rejects_oversized_details_without_writes(client, auth_headers):
    code = _code("VAREDIT")
    model_id = _create_model(client, auth_headers, code, {"general": {"model_no": code}})
    _add_fabric_bom(model_id, "VAREDIT")
    created = client.post(f"/api/models/{model_id}/variants", headers=auth_headers, json={"variant_no": "V2"})
    assert created.status_code == 201, created.text
    variant_id = created.json()["id"]
    _set_details(variant_id, {"general": {"model_no": code, "variant_no": "V2"}, "extension": _OVERSIZED_FILL})
    before_details = _details(variant_id)
    before_counts = _counts()

    response = client.patch(
        f"/api/models/{model_id}/variants/{variant_id}",
        headers=auth_headers,
        json={"variant_no": "V3"},
    )

    assert response.status_code == 422, response.text
    assert "UTF-8 bytes" in response.text
    assert _details(variant_id) == before_details
    assert _counts() == before_counts


def test_model_no_rename_rejects_oversized_details_without_writes(client, auth_headers):
    code = _code("RENAME")
    model_id = _create_model(client, auth_headers, code, {"general": {"model_no": code}})
    _set_details(model_id, {"general": {"model_no": code}, "extension": _OVERSIZED_FILL})
    before_details = _details(model_id)
    before_counts = _counts()
    new_no = _code("RENEWTARGET")

    response = client.patch(
        f"/api/models/{model_id}",
        headers=auth_headers,
        json={
            "code": new_no,
            "name": "Renamed",
            "details_json": {**before_details, "general": {"model_no": new_no}},
        },
    )

    assert response.status_code == 422, response.text
    assert "UTF-8 bytes" in response.text
    assert _details(model_id) == before_details
    assert _counts() == before_counts


# --------------------------------------------------------------------------
# 4. Family saves: the family-wide paid-operations save rebuilds every member's
#    document, so the rebuilt result must be bounded as well.
# --------------------------------------------------------------------------


def test_family_paid_operations_save_rejects_oversized_result_without_writes(client, auth_headers):
    code = _code("FAMILY")
    model_id = _create_model(client, auth_headers, code, {"general": {"model_no": code}})
    _set_details(model_id, {"general": {"model_no": code}, "extension": _OVERSIZED_FILL})
    before_details = _details(model_id)
    before_counts = _counts()

    response = client.patch(
        f"/api/models/{model_id}/paid-operations",
        headers=auth_headers,
        json={"paid_operations": [{"id": "op-1", "name": "Sew", "rate": "100", "sewingFactory": "milana"}]},
    )

    assert response.status_code == 422, response.text
    assert "UTF-8 bytes" in response.text
    assert _details(model_id) == before_details
    assert _counts() == before_counts


# --------------------------------------------------------------------------
# 5. Established shape: an exact re-submit of an already-stored legacy document
#    must stay editable, and that exemption must not extend to a document that
#    merely looks equal under Python's bool/int aliasing.
# --------------------------------------------------------------------------


def test_model_patch_allows_exact_oversized_legacy_details(client, auth_headers):
    code = _code("LEGACY-BIG")
    model_id = _create_model(client, auth_headers, code, {"general": {"model_no": code}})
    legacy = {"general": {"model_no": code}, "extension": _OVERSIZED_FILL}
    _set_details(model_id, legacy)

    response = client.patch(
        f"/api/models/{model_id}",
        headers=auth_headers,
        json={"code": code, "name": "Legacy big", "details_json": legacy},
    )

    assert response.status_code == 200, response.text
    assert response.json()["details_json"] == legacy


def test_model_patch_allows_exact_deep_legacy_details(client, auth_headers):
    code = _code("LEGACY-DEEP")
    model_id = _create_model(client, auth_headers, code, {"general": {"model_no": code}})
    deep = "leaf"
    for _ in range(_MAX_DETAILS_DEPTH + 4):
        deep = [deep]
    legacy = {"general": {"model_no": code}, "extension": deep}
    _set_details(model_id, legacy)

    response = _patch_raw(
        client,
        f"/api/models/{model_id}",
        auth_headers,
        _body_with_details(
            {"code": code, "name": "Legacy deep"},
            '{"general":{"model_no":' + json.dumps(code) + '},"extension":' + _deep_list_text(_MAX_DETAILS_DEPTH + 4) + "}",
        ),
    )

    assert response.status_code == 200, response.text
    assert _details(model_id) == legacy


def test_model_patch_does_not_excuse_a_type_swapped_legacy_document(client, auth_headers):
    """``{"a": 1}`` and ``{"a": True}`` compare equal in Python but are not the
    same document, so the stored document must not be grandfathered through it."""
    code = _code("LEGACY-SWAP")
    model_id = _create_model(client, auth_headers, code, {"general": {"model_no": code}})
    stored = {"general": {"model_no": code}, "counter": 1, "extension": _OVERSIZED_FILL}
    _set_details(model_id, stored)
    before = _counts()

    response = client.patch(
        f"/api/models/{model_id}",
        headers=auth_headers,
        json={"code": code, "name": "Type swapped", "details_json": {**stored, "counter": True}},
    )

    assert response.status_code == 422, response.text
    assert "UTF-8 bytes" in response.text
    assert _details(model_id) == stored
    assert _counts() == before


def test_ordinary_details_within_the_ceilings_are_still_accepted(client, auth_headers):
    code = _code("ORDINARY")
    details = {
        "general": {"model_no": code},
        "paid_operations": [{"id": "op-1", "name": "Sew", "rate": "100", "sewingFactory": "milana"}],
        "costing": {"sam_minutes": 12.5, "layers": {"trim": {"trimming": True}}},
        "notes": "ж" * 1024,
    }
    model_id = _create_model(client, auth_headers, code, details)

    response = client.patch(
        f"/api/models/{model_id}",
        headers=auth_headers,
        json={"code": code, "name": "Ordinary", "details_json": details},
    )

    assert response.status_code == 200, response.text
    assert response.json()["details_json"] == details
