"""Validate stock receipt QC commands before any inventory write."""

from uuid import uuid4

import pytest

from app.db.session import SessionLocal
from app.models import AuditLog, IdempotencyRecord, Item, StockBatch, StockMovement, Warehouse


VALID_QC_STATUSES = ("pending", "passed", "failed", "rejected", "hold")


def _fabric_receipt_payload(qc_status: str, *, item_id: int | None = None, warehouse_id: int | None = None) -> dict:
    with SessionLocal() as db:
        if item_id is None:
            item_id = db.query(Item.id).filter(
                Item.category == "fabric", Item.is_active.is_(True),
            ).order_by(Item.id).first()[0]
        item_unit = db.query(Item.unit).filter(Item.id == item_id).scalar() or "kg"
        if warehouse_id is None:
            warehouse_id = db.query(Warehouse.id).filter(
                Warehouse.type == "fabric_storage",
            ).order_by(Warehouse.id).first()[0]
    return {
        "item_id": item_id,
        "batch_no": f"DB02-QC-{uuid4().hex}",
        "quantity": 1,
        "unit": item_unit,
        "cost_per_unit": 1,
        "warehouse_id": warehouse_id,
        "qc_status": qc_status,
    }


def _write_counts() -> tuple[int, int, int, int]:
    with SessionLocal() as db:
        return (
            db.query(StockBatch).count(),
            db.query(StockMovement).count(),
            db.query(AuditLog).count(),
            db.query(IdempotencyRecord).count(),
        )


@pytest.mark.parametrize("qc_status", VALID_QC_STATUSES)
def test_receive_stock_preserves_every_supported_qc_status(client, auth_headers, qc_status):
    response = client.post(
        "/api/inventory/receive",
        headers=auth_headers,
        json=_fabric_receipt_payload(qc_status),
    )

    assert response.status_code == 201, response.text
    assert response.json()["qc_status"] == qc_status
    with SessionLocal() as db:
        assert db.get(StockBatch, response.json()["id"]).qc_status == qc_status


def test_receive_stock_rejects_unknown_qc_status_without_writes(client, auth_headers):
    before = _write_counts()

    response = client.post(
        "/api/inventory/receive",
        headers=auth_headers,
        json=_fabric_receipt_payload("released"),
    )

    assert response.status_code == 400, response.text
    assert response.json() == {"detail": "Invalid QC status"}
    assert _write_counts() == before


def test_receive_stock_qc_validation_preserves_authentication(client):
    before = _write_counts()

    response = client.post("/api/inventory/receive", json=_fabric_receipt_payload("released"))

    assert response.status_code == 401
    assert _write_counts() == before


def test_receive_stock_qc_validation_preserves_missing_warehouse_precedence(client, auth_headers):
    before = _write_counts()

    response = client.post(
        "/api/inventory/receive",
        headers=auth_headers,
        json=_fabric_receipt_payload("released", warehouse_id=2_147_483_647),
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Warehouse not found"}
    assert _write_counts() == before
