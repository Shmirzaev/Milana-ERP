"""Canonical movement and reservation vocabularies with schema-owned writes.

The vocabularies are checked against the column CHECK constraints they belong
to, so the enum and the stored column cannot drift apart.
"""
from datetime import datetime, timezone
from inspect import signature
from typing import Any, get_args, get_type_hints
from uuid import uuid4

import pytest

from app.db.session import SessionLocal
from app.libs.dto.inventory.material_reservation_input import MaterialReservationIn
from app.libs.dto.inventory.reservation_type_selection import DeferredReservationType
from app.libs.dto.inventory.material_reservation_output import (
    MaterialReservationOut,
    MaterialReservationPlanRow,
)
from app.libs.dto.inventory.stock_movement_input import StockMovementIn
from app.libs.dto.inventory.stock_movement_output import StockMovementOut
from app.libs.enums.inventory import (
    MaterialReservationSource,
    MaterialReservationStatus,
    MaterialReservationType,
    StockMovementType,
)
from app.schemas import Item, StockMovement, Warehouse
from app.schemas.inventory import material_reservation_persistence, stock_movement_persistence


def _check_values(table, column: str) -> tuple[str, ...]:
    """The values the column's own CHECK constraint allows."""
    for constraint in table.constraints:
        text = str(getattr(constraint, "sqltext", ""))
        if text.startswith(f"{column} IN ("):
            return tuple(part.strip().strip("'") for part in text.split("IN (")[1].split(")")[0].split(","))
    raise AssertionError(f"{table.name} has no CHECK constraint for {column}")


def test_movement_vocabulary_is_the_column_check_constraint():
    assert _check_values(StockMovement.__table__, "movement_type") == tuple(
        member.value for member in StockMovementType
    )


def test_reservation_vocabularies_are_the_column_check_constraints():
    table = material_reservation_persistence.MaterialReservation.__table__
    assert _check_values(table, "status") == tuple(member.value for member in MaterialReservationStatus)
    assert _check_values(table, "reservation_type") == tuple(member.value for member in MaterialReservationType)
    assert _check_values(table, "source") == tuple(member.value for member in MaterialReservationSource)


def test_used_contracts_carry_the_enum_classes():
    assert StockMovementIn.model_fields["movement_type"].annotation is StockMovementType
    assert StockMovementOut.model_fields["movement_type"].annotation is StockMovementType
    _assert_reservation_type_annotation(MaterialReservationIn.model_fields["reservation_type"].annotation)
    assert MaterialReservationOut.model_fields["status"].annotation is MaterialReservationStatus
    assert MaterialReservationOut.model_fields["reservation_type"].annotation is MaterialReservationType
    assert MaterialReservationOut.model_fields["source"].annotation is MaterialReservationSource


def _assert_reservation_type_annotation(annotation):
    assert annotation == MaterialReservationType | None
    assert set(get_args(annotation)) == {MaterialReservationType, type(None)}


@pytest.mark.parametrize("annotation", [str, Any, str | None, MaterialReservationType | str, MaterialReservationType | Any])
def test_reservation_type_annotation_guard_rejects_string_and_any(annotation, monkeypatch):
    monkeypatch.setattr(MaterialReservationIn.model_fields["reservation_type"], "annotation", annotation)
    with pytest.raises(AssertionError):
        test_used_contracts_carry_the_enum_classes()


@pytest.mark.parametrize("raw,expected", [
    (" material ", MaterialReservationType.MATERIAL),
    (" accessory ", MaterialReservationType.ACCESSORY),
    (" packaging ", MaterialReservationType.PACKAGING),
])
def test_reservation_input_preserves_raw_retry_value_and_yields_enum(raw, expected):
    payload = MaterialReservationIn(production_order_id=1, item_id=2, reserved_quantity=1, unit="kg", reservation_type=raw)
    assert payload.reservation_type is expected
    assert payload.reservation_type_selection() is expected
    assert payload.legacy_request_payload(mode="json")["reservation_type"] == raw


def test_reservation_input_default_fallback_and_invalid_are_distinct():
    from fastapi import HTTPException
    from pydantic import ValidationError
    from app.models.inventory_service import _reservation_type_member

    base = dict(production_order_id=1, item_id=2, reserved_quantity=1, unit="kg")
    default = MaterialReservationIn(**base)
    assert default.reservation_type is MaterialReservationType.MATERIAL
    assert default.legacy_request_payload(mode="json")["reservation_type"] == "material"
    fallback = MaterialReservationIn(**base, reservation_type="")
    invalid = MaterialReservationIn(**base, reservation_type="unknown")
    assert fallback.reservation_type is None and invalid.reservation_type is None
    assert fallback.reservation_type_selection() is DeferredReservationType.FALLBACK
    assert invalid.reservation_type_selection() is DeferredReservationType.INVALID
    assert fallback.legacy_request_payload(mode="json")["reservation_type"] == ""
    assert invalid.legacy_request_payload(mode="json")["reservation_type"] == "unknown"
    assert _reservation_type_member(fallback.reservation_type_selection(), "accessory") is MaterialReservationType.ACCESSORY
    with pytest.raises(HTTPException) as error:
        _reservation_type_member(invalid.reservation_type_selection(), "accessory")
    assert (error.value.status_code, error.value.detail) == (400, "Invalid reservation_type")
    with pytest.raises(ValidationError):
        MaterialReservationIn(**base, reservation_type=None)


def test_reservation_schema_insert_requires_canonical_type_annotation():
    from app.models.inventory_service import _ReservationCreateValues

    assert signature(material_reservation_persistence.insert_material_reservation).parameters["reservation_type"].annotation is MaterialReservationType
    assert get_type_hints(_ReservationCreateValues)["reservation_type"] is MaterialReservationType
    assert get_type_hints(_ReservationCreateValues)["status"] is MaterialReservationStatus
    assert get_type_hints(_ReservationCreateValues)["source"] is MaterialReservationSource


def test_plan_readiness_status_is_not_the_reservation_status():
    """The plan's own readiness status is a different concept."""
    assert MaterialReservationPlanRow.model_fields["status"].annotation is str
    assert MaterialReservationPlanRow.model_fields["reservation_type"].annotation is MaterialReservationType


def test_stock_movement_schema_insert_uses_the_supplied_session_and_stores_the_plain_value():
    name = f"Movement contract {uuid4().hex[:8]}"
    with SessionLocal() as db:
        item = Item(sku=f"MOVE-{uuid4().hex[:8]}", name="Movement item", category="fabric", unit="kg")
        db.add(item)
        db.flush()
        movement = stock_movement_persistence.insert_stock_movement(
            db,
            movement_type=StockMovementType.TRANSFER,
            item_id=item.id,
            batch_id=None,
            from_warehouse_id=None,
            to_warehouse_id=None,
            quantity=5,
            unit="kg",
            reference_type=None,
            reference_id=None,
            created_by=None,
        )
        assert movement.id is not None
        assert movement.movement_type == "transfer"
        assert type(movement.movement_type) is str
        assert db.get(StockMovement, movement.id) is movement
        db.rollback()
    with SessionLocal() as db:
        assert db.query(StockMovement).filter_by(item_id=item.id).first() is None


def test_material_reservation_schema_insert_stores_the_plain_canonical_values():
    marker = uuid4().hex[:8]
    with SessionLocal() as db:
        item = Item(sku=f"RES-{marker}", name="Reservation item", category="fabric", unit="kg")
        warehouse = Warehouse(name=f"Reservation warehouse {marker}", type="fabric_storage")
        db.add_all([item, warehouse])
        db.flush()
        reservation = material_reservation_persistence.insert_material_reservation(
            db,
            reservation_no=f"RES-{marker}",
            production_order_id=1,
            sales_order_id=None,
            item_id=item.id,
            stock_batch_id=None,
            warehouse_id=warehouse.id,
            reserved_quantity=3,
            consumed_quantity=0,
            released_quantity=0,
            unit="kg",
            status=MaterialReservationStatus.RESERVED,
            reservation_type=MaterialReservationType.MATERIAL,
            source=MaterialReservationSource.MANUAL,
            reserved_by=None,
            reserved_at=datetime.now(timezone.utc),
            notes=None,
        )
        db.flush()
        assert reservation.id is not None
        assert reservation.status == "reserved"
        assert reservation.reservation_type == "material"
        assert reservation.source == "manual"
        assert type(reservation.status) is str
        assert type(reservation.reservation_type) is str
        assert type(reservation.source) is str
        db.rollback()


@pytest.mark.parametrize("value", ["transfer", "issue", "consume", "adjustment", "return"])
def test_every_accepted_movement_kind_becomes_its_member(value):
    payload = StockMovementIn(
        movement_type=value, item_id=1, quantity=1, unit="kg",
    )
    assert payload.movement_type is StockMovementType(value)
    assert payload.model_dump(mode="json")["movement_type"] == value


def test_movement_request_refuses_a_value_outside_the_vocabulary():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        StockMovementIn(movement_type="teleport", item_id=1, quantity=1, unit="kg")
