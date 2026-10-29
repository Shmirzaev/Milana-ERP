"""Used enum contract and schema-owned write/transaction regressions."""
from typing import get_type_hints
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import event

from app.db.session import SessionLocal
from app.libs.dto.inventory.warehouse_input import WarehouseIn
from app.libs.dto.inventory.warehouse_output import WarehouseCreatedOut, WarehouseOut
from app.libs.enums.inventory import WarehouseType
from app.models.inventory import stock_service
from app.schemas import AuditLog, User, Warehouse
from app.schemas.inventory import warehouse_persistence


CREATE_VALUES = {
    "fabric_storage", "accessory_storage", "packaging", "cutting",
    "eco_cotton_cutting", "printing", "sewing", "besttex_packaging",
    "eco_cotton_packaging", "finished_goods", "waste",
}


def test_actual_creation_annotations_members_and_json():
    assert {member.value for member in WarehouseType} == CREATE_VALUES | {"raw_material", "warehouse"}
    assert WarehouseIn.model_fields["type"].annotation is WarehouseType
    assert WarehouseCreatedOut.model_fields["type"].annotation is WarehouseType
    assert get_type_hints(warehouse_persistence.insert_warehouse)["type"] is WarehouseType
    assert WarehouseOut.model_fields["type"].annotation is str
    assert WarehouseIn.model_fields["type"].is_required()
    for value in CREATE_VALUES:
        payload = WarehouseIn(name="Contract", type=value)
        assert payload.type is WarehouseType(value)
        assert payload.model_dump(mode="json")["type"] == value
        result = WarehouseCreatedOut(id=1, name="Contract", type=value)
        assert result.type is WarehouseType(value)
        assert result.model_dump(mode="json")["type"] == value


@pytest.mark.parametrize("value", ["raw_material", "warehouse", "unknown", "WASTE", " waste ", None])
def test_creation_input_and_output_refuse_legacy_unknown_and_unnormalized_values(value):
    with pytest.raises(ValidationError):
        WarehouseIn(name="Refused", type=value)
    with pytest.raises(ValidationError):
        WarehouseCreatedOut(id=1, name="Refused", type=value)


def test_actual_openapi_post_subset_and_legacy_get_are_distinct(client):
    document = client.get("/openapi.json").json()
    operation = document["paths"]["/api/inventory/warehouses"]
    schemas = document["components"]["schemas"]
    request = operation["post"]["requestBody"]["content"]["application/json"]["schema"]["$ref"].split("/")[-1]
    response = operation["post"]["responses"]["201"]["content"]["application/json"]["schema"]["$ref"].split("/")[-1]
    get_response = operation["get"]["responses"]["200"]["content"]["application/json"]["schema"]["items"]["$ref"].split("/")[-1]
    assert request == "WarehouseIn" and response == "WarehouseCreatedOut" and get_response == "WarehouseOut"
    for name in (request, response):
        assert schemas[name]["properties"]["type"]["type"] == "string"
        assert set(schemas[name]["properties"]["type"]["enum"]) == CREATE_VALUES
        assert "type" in schemas[name]["required"]
    assert schemas[get_response]["properties"]["type"]["type"] == "string"
    assert "enum" not in schemas[get_response]["properties"]["type"]


def test_service_uses_real_schema_insert_same_session_audit_and_one_outer_commit(monkeypatch):
    original_insert = warehouse_persistence.insert_warehouse
    original_audit = stock_service.log_action
    observed = []
    commits = []
    with SessionLocal() as db:
        actor = db.query(User).first()
        name = "Schema-owned " + uuid4().hex
        event.listen(db, "after_commit", lambda session: commits.append(session))

        def insert(session, **kwargs):
            assert session is db and kwargs["type"] is WarehouseType.WASTE
            row = original_insert(session, **kwargs)
            assert row.id is not None and row.type == "waste"
            assert commits == []
            observed.append(("insert", row.id))
            return row

        def audit(session, *args, **kwargs):
            assert session is db and observed and commits == []
            observed.append(("audit", args[3]))
            return original_audit(session, *args, **kwargs)

        monkeypatch.setattr(warehouse_persistence, "insert_warehouse", insert)
        monkeypatch.setattr(stock_service, "log_action", audit)
        row = stock_service.create_warehouse(db, WarehouseIn(name=name, type="waste"), actor)
        assert observed == [("insert", row.id), ("audit", row.id)]
        assert commits == [db]
        assert db.query(AuditLog).filter_by(entity_type="Warehouse", entity_id=row.id).count() == 1


def test_schema_insert_is_uncommitted_and_rollback_owned_by_caller():
    name = "Rollback schema " + uuid4().hex
    commits = []
    with SessionLocal() as db:
        event.listen(db, "after_commit", lambda session: commits.append(session))
        row = warehouse_persistence.insert_warehouse(db, name=name, type=WarehouseType.WASTE, department_id=None)
        assert row.id is not None and db.get(Warehouse, row.id) is row
        db.rollback()
    with SessionLocal() as db:
        assert db.query(Warehouse).filter_by(name=name).first() is None
    assert commits == []
