from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models import AuditLog, Item, Model, ModelBOM, Role, User


MAX_QUANTITY = Decimal("99999999.9999")
MAX_WASTE_PERCENT = Decimal("9999.99")


def _catalog_rows() -> tuple[int, int]:
    with SessionLocal() as db:
        return (
            db.query(ModelBOM).count(),
            db.query(AuditLog).filter(AuditLog.entity_type == "ModelBOM").count(),
        )


def _catalog_context() -> tuple[int, int]:
    marker = uuid4().hex
    with SessionLocal.begin() as db:
        model = Model(
            code=f"BOM-BOUND-{marker}",
            name=f"BOM bound model {marker}",
            status="draft",
            catalog_scope="standard",
        )
        item = Item(
            sku=f"BOM-BOUND-{marker}",
            name=f"BOM bound item {marker}",
            category="fabric",
            unit="kg",
            default_cost=1,
            reorder_level=0,
            composition_json=[],
        )
        db.add_all([model, item])
        db.flush()
        return model.id, item.id


def _payload(item_id: int, **overrides) -> dict:
    return {
        "item_id": item_id,
        "quantity_per_piece": "1.0000",
        "unit": "kg",
        "waste_percent": "0.00",
        **overrides,
    }


def _unprivileged_headers() -> dict[str, str]:
    marker = uuid4().hex
    with SessionLocal.begin() as db:
        role = Role(name=f"No model BOM access {marker}", permissions=[])
        db.add(role)
        db.flush()
        user = User(
            name="No model BOM access",
            email=f"no-model-bom-{marker}@example.invalid",
            password_hash="unused",
            role_id=role.id,
            factory_code="MIL",
        )
        db.add(user)
        db.flush()
        user_id = user.id
    token = create_access_token(user_id, {"factory_code": "MIL"})
    return {"Authorization": f"Bearer {token}"}


def test_model_bom_accepts_exact_numeric_boundaries(client, auth_headers):
    model_id, item_id = _catalog_context()

    response = client.post(
        f"/api/models/{model_id}/bom",
        headers=auth_headers,
        json=_payload(
            item_id,
            quantity_per_piece=str(MAX_QUANTITY),
            waste_percent=str(MAX_WASTE_PERCENT),
        ),
    )

    assert response.status_code == 201, response.text
    with SessionLocal() as db:
        row = db.get(ModelBOM, response.json()["id"])
        assert row.quantity_per_piece == MAX_QUANTITY
        assert row.waste_percent == MAX_WASTE_PERCENT


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("quantity_per_piece", "NaN"),
        ("quantity_per_piece", "Infinity"),
        ("quantity_per_piece", "-Infinity"),
        ("quantity_per_piece", "100000000"),
        ("quantity_per_piece", "-100000000"),
        ("waste_percent", "NaN"),
        ("waste_percent", "Infinity"),
        ("waste_percent", "-Infinity"),
        ("waste_percent", "10000"),
        ("waste_percent", "-10000"),
    ],
)
def test_model_bom_create_rejects_unstorable_numeric_without_writes(
    client, auth_headers, field, value,
):
    model_id, item_id = _catalog_context()
    before = _catalog_rows()

    response = client.post(
        f"/api/models/{model_id}/bom",
        headers=auth_headers,
        json=_payload(item_id, **{field: value}),
    )

    assert response.status_code == 422, response.text
    assert _catalog_rows() == before


def test_model_bom_patch_rejects_unstorable_numeric_without_mutation(
    client, auth_headers,
):
    model_id, item_id = _catalog_context()
    created = client.post(
        f"/api/models/{model_id}/bom",
        headers=auth_headers,
        json=_payload(item_id, quantity_per_piece="1.2500", waste_percent="2.50"),
    )
    assert created.status_code == 201, created.text
    row_id = created.json()["id"]
    before = _catalog_rows()

    response = client.patch(
        f"/api/models/{model_id}/bom/{row_id}",
        headers=auth_headers,
        json={"quantity_per_piece": "100000000", "waste_percent": "3.00"},
    )

    assert response.status_code == 422, response.text
    assert _catalog_rows() == before
    with SessionLocal() as db:
        row = db.get(ModelBOM, row_id)
        assert row.quantity_per_piece == Decimal("1.2500")
        assert row.waste_percent == Decimal("2.50")


def test_model_bom_numeric_validation_preserves_auth_and_not_found_precedence(
    client, auth_headers,
):
    _, item_id = _catalog_context()

    denied = client.post(
        "/api/models/2147483647/bom",
        headers=_unprivileged_headers(),
        json=_payload(item_id, quantity_per_piece="Infinity"),
    )
    assert denied.status_code == 403, denied.text

    missing = client.post(
        "/api/models/2147483647/bom",
        headers=auth_headers,
        json=_payload(item_id, quantity_per_piece="Infinity"),
    )
    assert missing.status_code == 404, missing.text
