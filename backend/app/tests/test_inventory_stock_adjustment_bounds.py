"""DB01-ADJUSTMENT: forced stock corrections must not leave reservations unbacked.

``force=true`` is a deliberate admin override for legacy selection rules
(multi-batch item corrections, linked-record overrides). It must never relax the
reservation floor: correcting stock below the sum of active reservations leaves
those claims without physical stock behind them.
"""

from uuid import uuid4

from app.db.session import SessionLocal
from app.models import (
    AuditLog,
    MaterialReservation,
    Model,
    ProductionOrder,
    StockBatch,
    StockMovement,
)
from app.services.inventory import current_stock_for_item

ITEM_FLOOR_MESSAGE = "Stock quantity cannot be lower than reserved quantity"
BATCH_FLOOR_MESSAGE = "Quantity cannot be lower than reserved stock"
MULTI_BATCH_MESSAGE = "Batch-tracked stock has multiple active batches"


def _create_item(
    client,
    auth_headers,
    *,
    category: str = "accessory",
    unit: str = "pcs",
    track_batch: bool = False,
) -> int:
    suffix = uuid4().hex[:10].upper()
    response = client.post(
        "/api/inventory/items",
        headers=auth_headers,
        json={
            "sku": f"DB01-{suffix}",
            "name": f"DB01 adjustment {suffix}",
            "category": category,
            "unit": unit,
            "default_cost": 1,
            "reorder_level": 0,
            "track_batch": track_batch,
            "is_active": True,
        },
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def _fabric_warehouse_id(client, auth_headers) -> int:
    response = client.get("/api/inventory/warehouses", headers=auth_headers)
    assert response.status_code == 200, response.text
    for warehouse in response.json():
        if warehouse.get("type") == "fabric_storage":
            return int(warehouse["id"])
    raise AssertionError("seeded data has no fabric storage warehouse")


def _receive(client, auth_headers, *, item_id: int, quantity: float, warehouse_id: int) -> int:
    response = client.post(
        "/api/inventory/receive",
        headers=auth_headers,
        json={
            "item_id": item_id,
            "batch_no": f"DB01-{uuid4().hex}",
            "quantity": quantity,
            "unit": "kg",
            "cost_per_unit": 1,
            "warehouse_id": warehouse_id,
            "qc_status": "passed",
        },
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def _reserve(
    *,
    item_id: int,
    quantity: float,
    unit: str,
    stock_batch_id: int | None = None,
    warehouse_id: int | None = None,
    reservation_type: str = "material",
) -> int:
    suffix = uuid4().hex[:12]
    with SessionLocal() as db:
        model = Model(
            code=f"DB01-MODEL-{suffix}",
            name=f"DB01 adjustment model {suffix}",
            status="approved",
        )
        db.add(model)
        db.flush()
        order = ProductionOrder(
            production_no=f"DB01-PO-{suffix}",
            production_type="branded_stock",
            model_id=model.id,
            planned_quantity=1,
        )
        db.add(order)
        db.flush()
        reservation = MaterialReservation(
            reservation_no=f"DB01-MR-{suffix}",
            production_order_id=order.id,
            item_id=item_id,
            stock_batch_id=stock_batch_id,
            warehouse_id=warehouse_id,
            reserved_quantity=quantity,
            consumed_quantity=0,
            released_quantity=0,
            unit=unit,
            status="reserved",
            reservation_type=reservation_type,
            source="manual",
        )
        db.add(reservation)
        db.commit()
        return int(reservation.id)


def _item_with_stock_and_reservation(client, auth_headers, *, stock: float, reserved: float):
    """Non batch-tracked item holding `stock` units with `reserved` units claimed."""
    item_id = _create_item(client, auth_headers, category="accessory", unit="pcs", track_batch=False)
    adjusted = client.patch(
        f"/api/inventory/stock/{item_id}",
        headers=auth_headers,
        json={"quantity": stock, "unit": "pcs"},
    )
    assert adjusted.status_code == 200, adjusted.text
    # ck_material_reservations_reserved_positive forbids a zero-quantity claim.
    reservation_id = None
    if reserved > 0:
        reservation_id = _reserve(
            item_id=item_id,
            quantity=reserved,
            unit="pcs",
            reservation_type="accessory",
        )
    return item_id, reservation_id


def _batch_with_stock_and_reservation(client, auth_headers, *, stock: float, reserved: float):
    """Batch-tracked item holding `stock` kg in one batch with `reserved` kg claimed."""
    warehouse_id = _fabric_warehouse_id(client, auth_headers)
    item_id = _create_item(client, auth_headers, category="fabric", unit="kg", track_batch=True)
    batch_id = _receive(
        client,
        auth_headers,
        item_id=item_id,
        quantity=stock,
        warehouse_id=warehouse_id,
    )
    reservation_id = _reserve(
        item_id=item_id,
        quantity=reserved,
        unit="kg",
        stock_batch_id=batch_id,
        warehouse_id=warehouse_id,
    )
    return item_id, batch_id, reservation_id


def _item_ledger(item_id: int) -> tuple[float, int, int]:
    """On-hand stock, movement count and adjustment audit count for an item.

    A non batch-tracked item carries its stock in StockMovement, not StockBatch,
    so the shared service function is the only correct way to read it back.
    """
    with SessionLocal() as db:
        total = current_stock_for_item(db, item_id)
        movements = db.query(StockMovement).filter(StockMovement.item_id == item_id).count()
        audit = db.query(AuditLog).filter(
            AuditLog.entity_type == "Item",
            AuditLog.entity_id == item_id,
        ).count()
    return total, movements, audit


# ===== Item endpoint: PATCH /stock/{item_id} =====


def test_unforced_item_correction_below_reservation_floor_is_rejected(client, auth_headers):
    item_id, _ = _item_with_stock_and_reservation(client, auth_headers, stock=10, reserved=7)

    response = client.patch(
        f"/api/inventory/stock/{item_id}",
        headers=auth_headers,
        json={"quantity": 6, "unit": "pcs"},
    )

    assert response.status_code == 409, response.text
    assert ITEM_FLOOR_MESSAGE in response.json()["detail"]


def test_forced_item_correction_below_reservation_floor_is_rejected(client, auth_headers):
    item_id, _ = _item_with_stock_and_reservation(client, auth_headers, stock=10, reserved=7)

    response = client.patch(
        f"/api/inventory/stock/{item_id}?force=true",
        headers=auth_headers,
        json={"quantity": 6, "unit": "pcs"},
    )

    assert response.status_code == 409, response.text
    assert ITEM_FLOOR_MESSAGE in response.json()["detail"]


def test_forced_item_correction_to_reservation_floor_succeeds(client, auth_headers):
    item_id, _ = _item_with_stock_and_reservation(client, auth_headers, stock=10, reserved=7)

    response = client.patch(
        f"/api/inventory/stock/{item_id}?force=true",
        headers=auth_headers,
        json={"quantity": 7, "unit": "pcs"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["quantity"] == 7


# ===== Batch endpoint: PATCH /batches/{batch_id} =====


def test_unforced_batch_correction_below_reservation_floor_is_rejected(client, auth_headers):
    _, batch_id, _ = _batch_with_stock_and_reservation(client, auth_headers, stock=10, reserved=7)

    response = client.patch(
        f"/api/inventory/batches/{batch_id}",
        headers=auth_headers,
        json={"quantity": 6},
    )

    assert response.status_code == 409, response.text
    assert BATCH_FLOOR_MESSAGE in response.json()["detail"]


def test_forced_batch_correction_below_reservation_floor_is_rejected(client, auth_headers):
    _, batch_id, _ = _batch_with_stock_and_reservation(client, auth_headers, stock=10, reserved=7)

    response = client.patch(
        f"/api/inventory/batches/{batch_id}?force=true",
        headers=auth_headers,
        json={"quantity": 6},
    )

    assert response.status_code == 409, response.text
    assert BATCH_FLOOR_MESSAGE in response.json()["detail"]


def test_forced_batch_correction_to_reservation_floor_succeeds(client, auth_headers):
    _, batch_id, _ = _batch_with_stock_and_reservation(client, auth_headers, stock=10, reserved=7)

    response = client.patch(
        f"/api/inventory/batches/{batch_id}?force=true",
        headers=auth_headers,
        json={"quantity": 7},
    )

    assert response.status_code == 200, response.text
    assert float(response.json()["quantity"]) == 7
    assert float(response.json()["reserved_quantity"]) == 7
    assert float(response.json()["available_quantity"]) == 0


# ===== Rollback: a rejected correction writes nothing =====


def test_rejected_forced_correction_leaves_claims_movements_and_audit_unchanged(client, auth_headers):
    item_id, reservation_id = _item_with_stock_and_reservation(client, auth_headers, stock=10, reserved=7)
    stock_before, movements_before, audit_before = _item_ledger(item_id)
    assert stock_before == 10

    response = client.patch(
        f"/api/inventory/stock/{item_id}?force=true",
        headers=auth_headers,
        json={"quantity": 6, "unit": "pcs"},
    )

    assert response.status_code == 409, response.text
    assert _item_ledger(item_id) == (stock_before, movements_before, audit_before)
    with SessionLocal() as db:
        reservation = db.get(MaterialReservation, reservation_id)
        assert reservation is not None
        assert reservation.status == "reserved"
        assert float(reservation.reserved_quantity) == 7
        assert float(reservation.consumed_quantity or 0) == 0
        assert float(reservation.released_quantity or 0) == 0


def test_rejected_forced_batch_correction_leaves_quantity_and_audit_unchanged(client, auth_headers):
    item_id, batch_id, reservation_id = _batch_with_stock_and_reservation(
        client, auth_headers, stock=10, reserved=7,
    )
    with SessionLocal() as db:
        movements_before = db.query(StockMovement).filter(StockMovement.batch_id == batch_id).count()
        audit_before = db.query(AuditLog).filter(
            AuditLog.entity_type == "StockBatch",
            AuditLog.entity_id == batch_id,
        ).count()

    response = client.patch(
        f"/api/inventory/batches/{batch_id}?force=true",
        headers=auth_headers,
        json={"quantity": 6},
    )

    assert response.status_code == 409, response.text
    with SessionLocal() as db:
        assert float(db.get(StockBatch, batch_id).quantity) == 10
        assert db.query(StockMovement).filter(StockMovement.batch_id == batch_id).count() == movements_before
        assert db.query(AuditLog).filter(
            AuditLog.entity_type == "StockBatch",
            AuditLog.entity_id == batch_id,
        ).count() == audit_before
        reservation = db.get(MaterialReservation, reservation_id)
        assert reservation.status == "reserved"
        assert float(reservation.reserved_quantity) == 7
        assert item_id == reservation.item_id


# ===== Ordering: the floor is re-read from fresh state on every request =====


def test_reservation_floor_is_reread_on_fresh_state_between_requests(client, auth_headers):
    item_id, _ = _item_with_stock_and_reservation(client, auth_headers, stock=10, reserved=7)

    first = client.patch(
        f"/api/inventory/stock/{item_id}?force=true",
        headers=auth_headers,
        json={"quantity": 6, "unit": "pcs"},
    )
    assert first.status_code == 409, first.text
    assert "(7 pcs)" in first.json()["detail"]

    # A later reservation raises the floor; the next correction must observe it.
    _reserve(item_id=item_id, quantity=1, unit="pcs", reservation_type="accessory")

    second = client.patch(
        f"/api/inventory/stock/{item_id}?force=true",
        headers=auth_headers,
        json={"quantity": 6, "unit": "pcs"},
    )
    assert second.status_code == 409, second.text
    assert "(8 pcs)" in second.json()["detail"]

    at_floor = client.patch(
        f"/api/inventory/stock/{item_id}?force=true",
        headers=auth_headers,
        json={"quantity": 8, "unit": "pcs"},
    )
    assert at_floor.status_code == 200, at_floor.text

    # Releasing the claims drops the floor, so a full write-off is permitted again.
    with SessionLocal() as db:
        for reservation in db.query(MaterialReservation).filter(
            MaterialReservation.item_id == item_id,
            MaterialReservation.status.in_(("reserved", "partially_consumed")),
        ):
            reservation.released_quantity = float(reservation.reserved_quantity)
            reservation.status = "released"
        db.commit()

    released = client.patch(
        f"/api/inventory/stock/{item_id}?force=true",
        headers=auth_headers,
        json={"quantity": 0, "unit": "pcs"},
    )
    assert released.status_code == 200, released.text
    assert released.json()["quantity"] == 0


# ===== Unreserved and metadata-only work must keep working =====


def test_forced_correction_below_zero_reservation_still_succeeds(client, auth_headers):
    item_id, _ = _item_with_stock_and_reservation(client, auth_headers, stock=10, reserved=0)

    response = client.patch(
        f"/api/inventory/stock/{item_id}?force=true",
        headers=auth_headers,
        json={"quantity": 1, "unit": "pcs"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["quantity"] == 1


def test_metadata_only_batch_edits_still_work_while_reserved(client, auth_headers):
    _, batch_id, _ = _batch_with_stock_and_reservation(client, auth_headers, stock=10, reserved=7)
    batch_no = f"DB01-EDIT-{uuid4().hex[:8].upper()}"

    for payload in (
        {"batch_no": batch_no},
        {"qc_status": "hold"},
        {"image_url": "https://example.com/db01-batch.jpg"},
    ):
        response = client.patch(
            f"/api/inventory/batches/{batch_id}?force=true",
            headers=auth_headers,
            json=payload,
        )
        assert response.status_code == 200, response.text

    with SessionLocal() as db:
        batch = db.get(StockBatch, batch_id)
        assert batch.batch_no == batch_no
        assert batch.qc_status == "hold"
        assert batch.image_url == "https://example.com/db01-batch.jpg"
        assert float(batch.quantity) == 10
        # Metadata edits must not disturb the claims on the batch.
        reservation = db.query(MaterialReservation).filter(
            MaterialReservation.stock_batch_id == batch_id,
        ).one()
        assert reservation.status == "reserved"
        assert float(reservation.reserved_quantity) == 7


# ===== force still permits the legacy overrides it exists for =====


def test_force_still_permits_legacy_multi_batch_selection(client, auth_headers):
    warehouse_id = _fabric_warehouse_id(client, auth_headers)
    item_id = _create_item(client, auth_headers, category="fabric", unit="kg", track_batch=True)
    _receive(client, auth_headers, item_id=item_id, quantity=5, warehouse_id=warehouse_id)
    _receive(client, auth_headers, item_id=item_id, quantity=5, warehouse_id=warehouse_id)

    blocked = client.patch(
        f"/api/inventory/stock/{item_id}",
        headers=auth_headers,
        json={"quantity": 8, "unit": "kg"},
    )
    assert blocked.status_code == 409, blocked.text
    assert MULTI_BATCH_MESSAGE in blocked.json()["detail"]

    forced = client.patch(
        f"/api/inventory/stock/{item_id}?force=true",
        headers=auth_headers,
        json={"quantity": 8, "unit": "kg"},
    )
    assert forced.status_code == 200, forced.text
    assert forced.json()["quantity"] == 8


def test_force_still_permits_linked_record_material_override(client, auth_headers):
    warehouse_id = _fabric_warehouse_id(client, auth_headers)
    item_id = _create_item(client, auth_headers, category="fabric", unit="kg", track_batch=True)
    other_item_id = _create_item(client, auth_headers, category="fabric", unit="kg", track_batch=True)
    batch_id = _receive(
        client, auth_headers, item_id=item_id, quantity=10, warehouse_id=warehouse_id,
    )
    _reserve(
        item_id=item_id,
        quantity=3,
        unit="kg",
        stock_batch_id=batch_id,
        warehouse_id=warehouse_id,
    )

    blocked = client.patch(
        f"/api/inventory/batches/{batch_id}",
        headers=auth_headers,
        json={"item_id": other_item_id},
    )
    assert blocked.status_code == 409, blocked.text

    forced = client.patch(
        f"/api/inventory/batches/{batch_id}?force=true",
        headers=auth_headers,
        json={"item_id": other_item_id},
    )
    assert forced.status_code == 200, forced.text
    assert forced.json()["item_id"] == other_item_id
    assert float(forced.json()["reserved_quantity"]) == 3
