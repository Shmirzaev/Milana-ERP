"""Material reservations: reserve, consume and release stock for production orders.

Every write here owns its transaction. Availability and reservation arithmetic stays
in `app.models.inventory_service`, which is the single source for stock truth.
"""

from fastapi import HTTPException

from app.libs.dto.inventory.material_reservation_input import (
    MaterialReservationAutoIn, MaterialReservationConsumeIn, MaterialReservationIn,
)
from app.libs.dto.inventory.material_reservation_output import MaterialReservationOut
from app.libs.enums.inventory import MaterialReservationSource
from app.models import inventory_access_service as inventory_access
from app.models.audit_service import log_action
from app.models.idempotency_service import replay_idempotent_response, store_idempotent_response
from app.models.inventory_service import (
    auto_reserve_materials_for_production_order,
    consume_material_reservation as consume_reservation_row,
    create_material_reservations,
    reservation_plan_for_production_order,
)
from app.models.inventory.reservation_release_service import release_material_reservation as release_reservation_row
from app.schemas import Item, MaterialReservation, User


def reservation_payload(reservation: MaterialReservation) -> dict:
    item = reservation.item
    batch = reservation.stock_batch
    warehouse = reservation.warehouse
    return {
        **MaterialReservationOut.model_validate(reservation).model_dump(),
        "item_sku": item.sku if item else None,
        "item_name": item.name if item else None,
        "batch_no": batch.batch_no if batch else None,
        "warehouse_name": warehouse.name if warehouse else None,
    }


def material_reservation_plan(db, user: User, production_order_id: int) -> dict:
    """The material reservation plan for one production order."""
    return reservation_plan_for_production_order(
        db, production_order_id,
        categories=inventory_access.MATERIAL_CATEGORIES if inventory_access.materials_only(user) else None,
    )


def list_material_reservations(
    db,
    user: User,
    production_order_id: int | None = None,
    sales_order_id: int | None = None,
    item_id: int | None = None,
    status: str | None = None,
) -> list[dict]:
    qry = db.query(MaterialReservation)
    if inventory_access.materials_only(user):
        qry = qry.join(Item, Item.id == MaterialReservation.item_id).filter(Item.category.in_(inventory_access.MATERIAL_CATEGORIES))
    if production_order_id is not None:
        qry = qry.filter(MaterialReservation.production_order_id == production_order_id)
    if sales_order_id is not None:
        qry = qry.filter(MaterialReservation.sales_order_id == sales_order_id)
    if item_id is not None:
        qry = qry.filter(MaterialReservation.item_id == item_id)
    if status:
        qry = qry.filter(MaterialReservation.status == status)
    rows = qry.order_by(MaterialReservation.created_at.desc(), MaterialReservation.id.desc()).all()
    return [reservation_payload(row) for row in rows]


def create_material_reservation(
    db,
    payload: MaterialReservationIn,
    current: User,
    idempotency_key: str | None = None,
) -> dict:
    inventory_access.require_item(db, current, payload.item_id)
    inventory_access.require_batch(db, current, payload.stock_batch_id)
    fingerprint_payload = payload.legacy_request_payload(mode="json")
    replay = replay_idempotent_response(db, scope="inventory.reservations.create", key=idempotency_key, payload=fingerprint_payload)
    if replay:
        return replay

    try:
        line = payload.legacy_request_payload()
        created = create_material_reservations(
            db,
            production_order_id=payload.production_order_id,
            lines=[line],
            user_id=current.id,
            source=MaterialReservationSource.MANUAL,
        )
    except HTTPException as exc:
        if exc.status_code in (400, 409):
            log_action(
                db,
                current,
                "failed_create_material_reservation",
                "MaterialReservation",
                None,
                new_value={"payload": payload.legacy_request_payload(), "detail": exc.detail},
            )
            db.commit()
        raise
    reservation = created[0]
    log_action(
        db,
        current,
        "create_material_reservation",
        "MaterialReservation",
        reservation.id,
        new_value={
            "reservation_no": reservation.reservation_no,
            "production_order_id": reservation.production_order_id,
            "item_id": reservation.item_id,
            "stock_batch_id": reservation.stock_batch_id,
            "reserved_quantity": float(reservation.reserved_quantity or 0),
        },
    )
    response = reservation_payload(reservation)
    store_idempotent_response(
        db,
        scope="inventory.reservations.create",
        key=idempotency_key,
        payload=fingerprint_payload,
        response=response,
        user=current,
        status_code=201,
    )
    db.commit()
    db.refresh(reservation)
    return response


def auto_create_material_reservations(db, payload: MaterialReservationAutoIn, current: User) -> dict:
    if payload.reserve_accessories or payload.reserve_packaging:
        inventory_access.require_accessories(current)
    result = auto_reserve_materials_for_production_order(
        db,
        production_order_id=payload.production_order_id,
        mode=payload.mode,
        reserve_accessories=payload.reserve_accessories,
        reserve_materials=payload.reserve_materials,
        reserve_packaging=payload.reserve_packaging,
        user_id=current.id,
    )
    if inventory_access.materials_only(current):
        result["plan"] = reservation_plan_for_production_order(db, payload.production_order_id, categories=inventory_access.MATERIAL_CATEGORIES)
    reservations = result["reservations"]
    log_action(
        db,
        current,
        "auto_reserve_materials",
        "ProductionOrder",
        payload.production_order_id,
        new_value={
            "mode": payload.mode,
            "created_count": len(reservations),
            "reservation_ids": [int(row.id) for row in reservations],
        },
    )
    db.commit()
    return {
        "production_order_id": payload.production_order_id,
        "created_count": len(reservations),
        "reservations": [reservation_payload(row) for row in reservations],
        "plan": result["plan"],
    }


def release_material_reservation(db, reservation_id: int, current: User) -> dict:
    inventory_access.require_reservation(db, current, reservation_id)
    reservation = release_reservation_row(db, reservation_id)
    log_action(
        db,
        current,
        "release_material_reservation",
        "MaterialReservation",
        reservation.id,
        new_value={
            "released_quantity": float(reservation.released_quantity or 0),
            "status": reservation.status,
        },
    )
    db.commit()
    db.refresh(reservation)
    return reservation_payload(reservation)


def consume_material_reservation(
    db,
    reservation_id: int,
    payload: MaterialReservationConsumeIn,
    current: User,
) -> dict:
    inventory_access.require_reservation(db, current, reservation_id)
    reservation = consume_reservation_row(
        db,
        reservation_id,
        quantity=payload.quantity,
        user_id=current.id,
    )
    log_action(
        db,
        current,
        "consume_material_reservation",
        "MaterialReservation",
        reservation.id,
        new_value={
            "quantity": payload.quantity,
            "consumed_quantity": float(reservation.consumed_quantity or 0),
            "status": reservation.status,
        },
    )
    db.commit()
    db.refresh(reservation)
    return reservation_payload(reservation)
