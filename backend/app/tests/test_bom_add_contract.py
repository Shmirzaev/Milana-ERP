"""CAT-BOM-ADD: the used contracts of the BOM create operation.

Focused checks for the canonical material role, the schema-owned write and the
ID-only result. The frozen PostgreSQL characterization suite stays the separate
behaviour baseline; these checks run on the local SQLite test database.
"""

from typing import Optional

import pytest
from pydantic import ValidationError

from app.libs.dto.catalog.model_bom_input import ModelBOMIn
from app.libs.enums.catalog import BomMaterialRole, CatalogScope
from app.libs.types.catalog import NormalizedBomCreate
from app.models.catalog import models_service
from app.schemas import Item, Model, ModelBOM, User
from app.tests.conftest import TestSessionLocal


def _actor():
    with TestSessionLocal() as db:
        user = db.query(User).filter(User.email == "admin@example.com").first()
        db.expunge_all()
        return user


def _model(catalog_scope: str):
    with TestSessionLocal() as db:
        model = Model(
            code=f"BOM-{catalog_scope}",
            name="BOM contract",
            catalog_scope=catalog_scope,
            factory_code="ECO" if catalog_scope == "usluga" else "MIL",
        )
        db.add(model)
        db.commit()
        db.refresh(model)
        return model.id


def _accessory_item():
    with TestSessionLocal() as db:
        item = db.query(Item).filter(Item.category == "accessory").first()
        return item.id if item else None


def _manual(**extra):
    return ModelBOMIn(
        material_name=" Cotton ", material_role=" MAIN ", quantity_per_piece=1, unit="kg", **extra
    )


def test_the_canonical_role_is_one_enum_with_two_members():
    assert [role.value for role in BomMaterialRole] == ["main", "secondary"]
    assert BomMaterialRole.MAIN.value == "main"
    assert BomMaterialRole.SECONDARY.value == "secondary"


def test_the_create_dto_carries_the_nullable_canonical_member():
    field = ModelBOMIn.model_fields["material_role"]
    assert field.annotation == Optional[BomMaterialRole]
    assert field.default is None


def test_the_runtime_role_is_a_member_for_omitted_and_supplied_values():
    assert ModelBOMIn(quantity_per_piece=1, unit="kg").material_role is None
    assert ModelBOMIn(
        material_name="Cotton", material_role="main", quantity_per_piece=1, unit="kg"
    ).material_role is BomMaterialRole.MAIN
    assert ModelBOMIn(
        material_name="Cotton", material_role=" MAIN ", quantity_per_piece=1, unit="kg"
    ).material_role is BomMaterialRole.MAIN
    assert ModelBOMIn(
        material_name="Cotton", material_role=" Secondary ", quantity_per_piece=1, unit="kg"
    ).material_role is BomMaterialRole.SECONDARY


def test_an_inventory_link_discards_the_supplied_role():
    assert ModelBOMIn(
        material_name="  ", material_role="unrecognized", quantity_per_piece=1, unit="kg"
    ).material_role is None
    assert ModelBOMIn(
        material_role=" MAIN ", quantity_per_piece=1, unit="kg"
    ).material_role is None


def test_the_original_request_validation_runs_before_the_discard():
    with pytest.raises(ValidationError) as error:
        ModelBOMIn(material_name="  ", material_role="x" * 17, quantity_per_piece=1, unit="kg")
    assert error.value.errors()[0]["type"] == "string_too_long"
    with pytest.raises(ValidationError) as error:
        ModelBOMIn(material_name="  ", material_role=123, quantity_per_piece=1, unit="kg")
    assert error.value.errors()[0]["type"] == "string_type"


def test_the_service_hands_the_write_to_the_schema_owned_insert(monkeypatch):
    seen = []
    original = models_service.insert_model_bom

    def spy(db, *, model_id, create):
        seen.append((model_id, create))
        return original(db, model_id=model_id, create=create)

    monkeypatch.setattr(models_service, "insert_model_bom", spy)
    mid = _model("usluga")
    with TestSessionLocal() as db:
        result = models_service.add_bom(_actor(), db, mid, _manual(), CatalogScope.USLUGA)
    assert len(seen) == 1
    assert seen[0][0] == mid
    assert isinstance(seen[0][1], NormalizedBomCreate)
    assert seen[0][1].material_role is BomMaterialRole.MAIN
    assert set(result) == {"id"}


def test_the_stored_role_is_the_plain_string():
    mid = _model("usluga")
    with TestSessionLocal() as db:
        result = models_service.add_bom(_actor(), db, mid, _manual(), CatalogScope.USLUGA)
        row = db.get(ModelBOM, result["id"])
        assert row.material_role == "main"
        assert type(row.material_role) is str
        assert row.material_name == "Cotton"
        assert row.item_id is None
        assert row.stock_batch_id is None


def test_an_inventory_line_stores_no_role():
    mid = _model("standard")
    item_id = _accessory_item()
    with TestSessionLocal() as db:
        result = models_service.add_bom(
            _actor(),
            db,
            mid,
            ModelBOMIn(
                item_id=item_id,
                material_name="  ",
                material_role="unrecognized",
                quantity_per_piece=1,
                unit="pcs",
            ),
            CatalogScope.STANDARD,
        )
        row = db.get(ModelBOM, result["id"])
        assert row.material_role is None
        assert row.material_name is None
        assert row.item_id == item_id


def test_the_create_route_returns_the_id_only_result(client, auth_headers):
    mid = _model("standard")
    item_id = _accessory_item()
    response = client.post(
        f"/api/models/{mid}/bom",
        headers=auth_headers,
        json={"item_id": item_id, "quantity_per_piece": 1, "unit": "pcs"},
    )
    assert response.status_code == 201, response.text
    assert set(response.json()) == {"id"}
    assert isinstance(response.json()["id"], int)


def test_the_openapi_exposes_the_canonical_role_and_the_id_only_result(client):
    schema = client.get("/openapi.json").json()
    role = schema["components"]["schemas"]["ModelBOMIn"]["properties"]["material_role"]
    assert "default" not in role
    assert role["anyOf"][0]["enum"] == ["main", "secondary"]
    assert role["anyOf"][1] == {"type": "null"}
    result = schema["components"]["schemas"]["ModelBOMCreateOut"]
    assert result["properties"]["id"]["type"] == "integer"
    assert result["required"] == ["id"]
