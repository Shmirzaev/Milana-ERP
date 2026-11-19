"""Persistence for a service-approved Eco fabric dispatch."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.libs.enums.inventory import StockMovementType
from app.schemas.inventory.eco_transfer import EcoFabricDispatch, EcoFabricRoll
from app.schemas.inventory.inventory import StockBatch, StockMovement


def add_dispatch(db: Session, *, request_key: str, user_id: int, operator_name: str,
                 sent_at: datetime) -> EcoFabricDispatch:
    dispatch = EcoFabricDispatch(request_key=request_key, created_by=user_id, operator_name=operator_name,
                                 sent_at=sent_at, remaining_inventory=[])
    db.add(dispatch)
    return dispatch


def set_roll_weights(db: Session, batch: StockBatch, *, weights: list[float]) -> None:
    batch.roll_weights_kg = weights


def set_batch_quantity(db: Session, batch: StockBatch, *, quantity: Decimal) -> None:
    batch.quantity = quantity


def archive_sent_batch(db: Session, batch: StockBatch, *, sent_at: datetime, user_id: int) -> None:
    batch.archived_at = sent_at
    batch.archived_by = user_id


def add_sent_roll(db: Session, *, dispatch: EcoFabricDispatch, batch: StockBatch,
                  batch_id: int, roll_number: int, quantity: Decimal, user_id: int) -> None:
    db.add(EcoFabricRoll(dispatch_id=dispatch.id, batch_id=batch_id, roll_number=roll_number,
                         fabric_name=batch.item.name, batch_no=batch.batch_no, color=batch.color,
                         quantity=quantity, unit=batch.unit))
    db.add(StockMovement(movement_type=StockMovementType.ISSUE.value, item_id=batch.item_id, batch_id=batch_id,
                         from_warehouse_id=batch.warehouse_id, quantity=quantity, unit=batch.unit,
                         reference_type="EcoFabricDispatch", reference_id=dispatch.id, created_by=user_id))


def set_remaining_inventory(db: Session, dispatch: EcoFabricDispatch, *, snapshot: list) -> None:
    dispatch.remaining_inventory = snapshot
