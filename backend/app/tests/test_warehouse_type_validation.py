"""Warehouse creation accepts only stock-policy warehouse type codes."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.db.session import SessionLocal
from app.models import AuditLog, Warehouse
from app.schemas.inventory import WarehouseIn


WAREHOUSE_TYPES = (
    "fabric_storage",
    "accessory_storage",
    "packaging",
    "cutting",
    "eco_cotton_cutting",
    "printing",
    "sewing",
    "besttex_packaging",
    "eco_cotton_packaging",
    "finished_goods",
    "waste",
)


@pytest.mark.parametrize("warehouse_type", WAREHOUSE_TYPES)
def test_warehouse_schema_accepts_seeded_stock_policy_codes(warehouse_type):
    assert WarehouseIn(name="Warehouse", type=warehouse_type).type == warehouse_type


def test_warehouse_create_rejects_unknown_type_without_row_or_audit(client, auth_headers):
    name = f"Unknown warehouse {uuid4().hex}"
    with SessionLocal() as db:
        before = (db.query(Warehouse).count(), db.query(AuditLog).count())

    response = client.post(
        "/api/inventory/warehouses",
        json={"name": name, "type": "fabric-stroage"},
        headers=auth_headers,
    )

    assert response.status_code == 422, response.text
    with SessionLocal() as db:
        assert (db.query(Warehouse).count(), db.query(AuditLog).count()) == before
        assert db.query(Warehouse.id).filter_by(name=name).first() is None


def test_warehouse_create_accepts_canonical_type(client, auth_headers):
    name = f"Additional fabric warehouse {uuid4().hex}"

    response = client.post(
        "/api/inventory/warehouses",
        json={"name": name, "type": "fabric_storage"},
        headers=auth_headers,
    )

    assert response.status_code == 201, response.text
    assert response.json()["type"] == "fabric_storage"
    with SessionLocal() as db:
        assert db.get(Warehouse, response.json()["id"]).name == name


def test_warehouse_create_keeps_authentication_precedence(client):
    response = client.post(
        "/api/inventory/warehouses",
        json={"name": "Unauthorized", "type": "fabric-stroage"},
    )
    assert response.status_code == 401, response.text


def test_warehouse_schema_rejects_unknown_type():
    with pytest.raises(ValidationError):
        WarehouseIn(name="Unknown", type="fabric-stroage")
