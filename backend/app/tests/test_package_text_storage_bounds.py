from app.db.session import SessionLocal
from app.models import (
    AuditLog,
    Package,
    PackageItem,
    PackageScanLog,
    PackagingRecord,
    WorkOrder,
)


def _create_order_with_packaging_evidence(client, auth_headers) -> int:
    response = client.post(
        "/api/planning/create-branded-production",
        json={
            "production_type": "branded_stock",
            "model_id": 1,
            "planned_quantity": 1,
            "items": [{
                "model_id": 1,
                "color": "white",
                "size": "M",
                "planned_quantity": 1,
            }],
        },
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    order_id = int(response.json()["id"])

    with SessionLocal() as db:
        work_order = db.query(WorkOrder).filter_by(
            production_order_id=order_id,
            operation="packaging",
            production_batch_id=None,
        ).one()
        db.add(PackagingRecord(
            work_order_id=work_order.id,
            production_batch_id=None,
            input_qty=1,
            packed_qty=1,
            damaged_qty=0,
        ))
        db.commit()
    return order_id


def _payload(order_id: int, color: str, item_color: str, size: str) -> dict:
    return {
        "production_order_id": order_id,
        "model_id": 1,
        "color": color,
        "capacity": 1,
        "items": [{
            "model_id": 1,
            "color": item_color,
            "size": size,
            "quantity": 1,
        }],
    }


def _write_counts() -> tuple[int, int, int, int]:
    with SessionLocal() as db:
        return (
            db.query(Package).count(),
            db.query(PackageItem).count(),
            db.query(PackageScanLog).count(),
            db.query(AuditLog).filter_by(entity_type="Package").count(),
        )


def test_package_and_item_text_storage_boundaries_are_accepted(client, auth_headers):
    order_id = _create_order_with_packaging_evidence(client, auth_headers)
    response = client.post(
        "/api/packages",
        headers=auth_headers,
        json=_payload(order_id, "P" * 64, "C" * 64, "S" * 32),
    )

    assert response.status_code == 201, response.text


def test_package_text_overflow_is_rejected_without_writes_and_preserves_precedence(
    client,
    auth_headers,
):
    order_id = _create_order_with_packaging_evidence(client, auth_headers)
    before = _write_counts()

    for payload in (
        _payload(order_id, "P" * 65, "Black", "M"),
        _payload(order_id, "Black", "C" * 65, "M"),
        _payload(order_id, "Black", "Black", "S" * 33),
    ):
        response = client.post("/api/packages", headers=auth_headers, json=payload)
        assert response.status_code == 422, response.text
        assert _write_counts() == before

    unauthenticated = client.post(
        "/api/packages",
        json=_payload(order_id, "P" * 65, "Black", "M"),
    )
    assert unauthenticated.status_code == 401

    missing_order = client.post(
        "/api/packages",
        headers=auth_headers,
        json=_payload(2_147_483_647, "P" * 65, "Black", "M"),
    )
    assert missing_order.status_code == 404
    assert _write_counts() == before
