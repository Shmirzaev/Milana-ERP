"""Keep editable model payroll JSON in its established list-of-objects shape."""

from copy import deepcopy
from uuid import uuid4

import pytest

from app.db.session import SessionLocal
from app.models import AuditLog, Model

_MAX_DETAILS_BYTES = 64 * 1024
_MAX_DETAILS_DEPTH = 16


def _model() -> tuple[int, dict]:
    suffix = uuid4().hex[:8].upper()
    details = {
        "general": {"model_no": f"DB03-{suffix}"},
        "costing": {"target_margin_pct": 20},
        "paid_operations": [{
            "id": f"sew-{suffix}",
            "selected": True,
            "section": "sewing",
            "code": f"SEW-{suffix}",
            "name": "Sewing",
            "rate": "100",
            "legacy_extension": {"source": "existing-client"},
        }],
    }
    with SessionLocal() as db:
        model = Model(
            code=f"DB03-{suffix}",
            name=f"DB03 model {suffix}",
            status="draft",
            details_json=deepcopy(details),
        )
        db.add(model)
        db.commit()
        return int(model.id), details


def _update_payload(model_id: int, details: dict) -> dict:
    with SessionLocal() as db:
        model = db.get(Model, model_id)
        return {
            "code": model.code,
            "name": model.name,
            "status": model.status,
            "details_json": details,
        }


def _snapshot(model_id: int) -> tuple[dict, int]:
    with SessionLocal() as db:
        return deepcopy(db.get(Model, model_id).details_json), db.query(AuditLog).count()


def _nested_detail(depth: int) -> dict:
    value: object = "leaf"
    for _ in range(depth):
        value = [value]
    return {"extension": value}


@pytest.mark.parametrize(("paid_operations", "detail"), [
    ({"id": "not-a-list"}, "details_json.paid_operations must be a list"),
    ([{"id": "valid"}, "not-an-object"], "details_json.paid_operations[1] must be an object"),
])
def test_model_update_rejects_malformed_paid_operation_json_without_writes(
    client, auth_headers, paid_operations, detail,
):
    model_id, original = _model()
    before = _snapshot(model_id)
    malformed = {**deepcopy(original), "paid_operations": paid_operations}

    response = client.patch(
        f"/api/models/{model_id}",
        headers=auth_headers,
        json=_update_payload(model_id, malformed),
    )

    assert response.status_code == 422, response.text
    assert response.json() == {"detail": detail}
    assert _snapshot(model_id) == before


@pytest.mark.parametrize("key", ["paid_operations", "paidOperations"])
def test_model_update_preserves_supported_operation_aliases_and_extensible_rows(client, auth_headers, key):
    model_id, original = _model()
    operation = deepcopy(original["paid_operations"][0])
    details = {
        "general": deepcopy(original["general"]),
        "costing": deepcopy(original["costing"]),
        "future_section": {"kept": True},
        key: [operation],
    }

    response = client.patch(
        f"/api/models/{model_id}",
        headers=auth_headers,
        json=_update_payload(model_id, details),
    )

    assert response.status_code == 200, response.text
    assert response.json()["details_json"] == details
    with SessionLocal() as db:
        assert db.get(Model, model_id).details_json == details


def test_model_details_structure_validation_preserves_authentication(client):
    model_id, original = _model()
    before = _snapshot(model_id)
    malformed = {**deepcopy(original), "paid_operations": "not-a-list"}

    response = client.patch(f"/api/models/{model_id}", json=_update_payload(model_id, malformed))

    assert response.status_code == 401
    assert _snapshot(model_id) == before


def test_model_details_structure_validation_preserves_missing_model_precedence(client, auth_headers):
    response = client.patch(
        "/api/models/2147483647",
        headers=auth_headers,
        json={
            "code": "MISSING",
            "name": "Missing",
            "status": "draft",
            "details_json": {"paid_operations": "not-a-list"},
        },
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Model not found"}


@pytest.mark.parametrize(
    ("details", "message"),
    [
        ({"extension": "ж" * (_MAX_DETAILS_BYTES // 2 + 1)}, "UTF-8 bytes"),
        (
            _nested_detail(_MAX_DETAILS_DEPTH + 1),
            "nested container levels",
        ),
    ],
)
def test_model_create_rejects_oversized_or_deep_details_without_insert(
    client, auth_headers, details, message,
):
    code = f"DB03-BOUNDS-{uuid4().hex[:8].upper()}"

    response = client.post(
        "/api/models",
        headers=auth_headers,
        json={"code": code, "name": "Bounded detail", "details_json": details},
    )

    assert response.status_code == 422, response.text
    assert message in response.text
    with SessionLocal() as db:
        assert db.query(Model.id).filter(Model.code == code).first() is None


def test_model_patch_rejects_oversized_extension_before_model_or_audit_write(client, auth_headers):
    model_id, original = _model()
    before = _snapshot(model_id)
    changed = {**original, "future_extension": "ж" * (_MAX_DETAILS_BYTES // 2 + 1)}

    response = client.patch(
        f"/api/models/{model_id}",
        headers=auth_headers,
        json=_update_payload(model_id, changed),
    )

    assert response.status_code == 422, response.text
    assert "UTF-8 bytes" in response.text
    assert _snapshot(model_id) == before


def test_model_patch_allows_exact_oversized_legacy_details(client, auth_headers):
    model_id, _original = _model()
    legacy = {"future_extension": "ж" * (_MAX_DETAILS_BYTES // 2 + 1)}
    with SessionLocal() as db:
        db.get(Model, model_id).details_json = legacy
        db.commit()
    before = _snapshot(model_id)

    response = client.patch(
        f"/api/models/{model_id}",
        headers=auth_headers,
        json=_update_payload(model_id, legacy),
    )

    assert response.status_code == 200, response.text
    assert response.json()["details_json"] == legacy
    assert _snapshot(model_id)[0] == before[0]


def test_model_patch_allows_exact_deep_legacy_extension(client, auth_headers):
    model_id, _original = _model()
    legacy = _nested_detail(_MAX_DETAILS_DEPTH + 2)
    with SessionLocal() as db:
        db.get(Model, model_id).details_json = legacy
        db.commit()

    response = client.patch(
        f"/api/models/{model_id}",
        headers=auth_headers,
        json=_update_payload(model_id, legacy),
    )

    assert response.status_code == 200, response.text
    assert response.json()["details_json"] == legacy


def test_model_paid_operations_patch_rejects_changed_oversized_document_without_write(client, auth_headers):
    model_id, original = _model()
    legacy = {**original, "future_extension": "ж" * (_MAX_DETAILS_BYTES // 2 + 1)}
    with SessionLocal() as db:
        db.get(Model, model_id).details_json = legacy
        db.commit()
    before = _snapshot(model_id)

    response = client.patch(
        f"/api/models/{model_id}/paid-operations",
        headers=auth_headers,
        json={"paid_operations": [{"id": "new-op", "name": "New operation"}]},
    )

    assert response.status_code == 422, response.text
    assert "UTF-8 bytes" in response.text
    assert _snapshot(model_id) == before


def test_model_clone_rejects_oversized_transformed_details_without_writes(client, auth_headers):
    suffix = uuid4().hex[:8].upper()
    code = f"DB03-CLONE-{suffix}"
    created = client.post(
        "/api/models",
        headers=auth_headers,
        json={"code": code, "name": "Clone source", "details_json": {"general": {"model_no": code}}},
    )
    assert created.status_code == 201, created.text
    model_id = created.json()["id"]
    legacy = {"general": {"model_no": code}, "extension": "ж" * (_MAX_DETAILS_BYTES // 2 + 1)}
    with SessionLocal() as db:
        db.get(Model, model_id).details_json = legacy
        db.commit()
        before = (db.query(Model.id).count(), db.query(AuditLog.id).count())

    response = client.post(f"/api/models/{model_id}/clone", headers=auth_headers)

    assert response.status_code == 422, response.text
    assert "UTF-8 bytes" in response.text
    with SessionLocal() as db:
        assert (db.query(Model.id).count(), db.query(AuditLog.id).count()) == before


def test_model_variant_create_rejects_oversized_transformed_details_without_writes(client, auth_headers):
    from app.models import Item, ModelBOM
    from app.tests.conftest import TestSessionLocal

    suffix = uuid4().hex[:8].upper()
    code = f"DB03-VARIANT-{suffix}"
    created = client.post(
        "/api/models",
        headers=auth_headers,
        json={"code": code, "name": "Variant source", "details_json": {"general": {"model_no": code}}},
    )
    assert created.status_code == 201, created.text
    model_id = created.json()["id"]
    legacy = {"general": {"model_no": code}, "extension": "ж" * (_MAX_DETAILS_BYTES // 2 + 1)}
    with TestSessionLocal() as db:
        item = Item(sku=f"DB03-VARIANT-FAB-{suffix}", name="Variant fabric", category="fabric", unit="m")
        db.add(item)
        db.flush()
        db.add(ModelBOM(model_id=model_id, item_id=item.id, material_role="main", quantity_per_piece=1, unit="m"))
        db.get(Model, model_id).details_json = legacy
        db.commit()
        before = (db.query(Model.id).count(), db.query(AuditLog.id).count())

    response = client.post(
        f"/api/models/{model_id}/variants",
        headers=auth_headers,
        json={"variant_no": "V2"},
    )

    assert response.status_code == 422, response.text
    assert "UTF-8 bytes" in response.text
    with SessionLocal() as db:
        assert (db.query(Model.id).count(), db.query(AuditLog.id).count()) == before


def test_variant_edit_rejects_oversized_transformed_details_without_writes(client, auth_headers):
    from app.models import Item, ModelBOM
    from app.tests.conftest import TestSessionLocal

    suffix = uuid4().hex[:8].upper()
    code = f"DB03-VARIANT-EDIT-{suffix}"
    created = client.post(
        "/api/models",
        headers=auth_headers,
        json={"code": code, "name": "Variant source", "details_json": {"general": {"model_no": code}}},
    )
    assert created.status_code == 201, created.text
    model_id = created.json()["id"]
    with TestSessionLocal() as db:
        item = Item(sku=f"DB03-VARIANT-EDIT-FAB-{suffix}", name="Variant fabric", category="fabric", unit="m")
        db.add(item)
        db.flush()
        db.add(ModelBOM(model_id=model_id, item_id=item.id, material_role="main", quantity_per_piece=1, unit="m"))
        db.commit()
    variant = client.post(
        f"/api/models/{model_id}/variants",
        headers=auth_headers,
        json={"variant_no": "V2"},
    )
    assert variant.status_code == 201, variant.text
    variant_id = variant.json()["id"]
    legacy = {"general": {"model_no": code, "variant_no": "V2"}, "extension": "ж" * (_MAX_DETAILS_BYTES // 2 + 1)}
    with TestSessionLocal() as db:
        db.get(Model, variant_id).details_json = legacy
        db.commit()
        before = (db.query(Model.id).count(), db.query(Model.code).filter(Model.id == variant_id).scalar(), db.query(AuditLog.id).count())

    response = client.patch(
        f"/api/models/{model_id}/variants/{variant_id}",
        headers=auth_headers,
        json={"variant_no": "V3"},
    )

    assert response.status_code == 422, response.text
    assert "UTF-8 bytes" in response.text
    with TestSessionLocal() as db:
        assert (db.query(Model.id).count(), db.query(Model.code).filter(Model.id == variant_id).scalar(), db.query(AuditLog.id).count()) == before
