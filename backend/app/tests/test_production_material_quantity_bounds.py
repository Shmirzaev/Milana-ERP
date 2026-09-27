from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.db.session import SessionLocal
from app.models import AuditLog, MaterialReservation, ProductionOrder, ProductionOrderMaterial
from app.schemas.production import ProductionOrderIn, ProductionOrderMaterialIn


MAX_MATERIAL_QUANTITY = Decimal("9999999999.9999")


def _order_payload(quantity: str) -> dict:
    return {
        "production_type": "branded_stock",
        "model_id": 1,
        "materials": [
            {
                "stock_batch_id": 1,
                "estimated_quantity": quantity,
                "unit": "kg",
            },
        ],
    }


def _write_counts() -> tuple[int, int, int, int]:
    with SessionLocal() as db:
        return (
            db.query(ProductionOrder).count(),
            db.query(ProductionOrderMaterial).count(),
            db.query(MaterialReservation).count(),
            db.query(AuditLog).count(),
        )


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "10000000000"])
def test_production_material_quantity_rejects_non_finite_and_storage_overflow(value):
    with pytest.raises(ValidationError):
        ProductionOrderMaterialIn(
            stock_batch_id=1,
            estimated_quantity=value,
            unit="kg",
        )


def test_production_material_quantity_preserves_extra_precision_and_exact_maximum():
    precise = ProductionOrderMaterialIn(
        stock_batch_id=1,
        estimated_quantity="2.34567",
        unit="kg",
    )
    assert precise.estimated_quantity == pytest.approx(2.34567)

    maximum = ProductionOrderMaterialIn(
        stock_batch_id=1,
        estimated_quantity=str(MAX_MATERIAL_QUANTITY),
        unit="kg",
    )
    assert maximum.estimated_quantity == pytest.approx(float(MAX_MATERIAL_QUANTITY))
    nested = ProductionOrderIn(**_order_payload(str(MAX_MATERIAL_QUANTITY)))
    assert nested.materials[0].estimated_quantity == pytest.approx(
        float(MAX_MATERIAL_QUANTITY),
    )


def test_production_material_stock_batch_id_rejects_integer_storage_overflow():
    with pytest.raises(ValidationError):
        ProductionOrderMaterialIn(
            stock_batch_id=2_147_483_648,
            estimated_quantity=1,
            unit="kg",
        )

    payload = _order_payload("1")
    payload["materials"][0]["stock_batch_id"] = 2_147_483_648
    with pytest.raises(ValidationError):
        ProductionOrderIn(**payload)


def test_invalid_production_material_quantity_has_no_write_side_effects(
    client,
    auth_headers,
):
    before = _write_counts()

    response = client.post(
        "/api/production-orders",
        headers=auth_headers,
        json=_order_payload("10000000000"),
    )

    assert response.status_code == 422, response.text
    assert _write_counts() == before


def test_invalid_production_material_quantity_preserves_authentication_precedence(client):
    before = _write_counts()

    response = client.post(
        "/api/production-orders",
        json=_order_payload("Infinity"),
    )

    assert response.status_code == 401, response.text
    assert _write_counts() == before


def test_invalid_production_material_id_preserves_authentication_precedence(client):
    before = _write_counts()
    payload = _order_payload("1")
    payload["materials"][0]["stock_batch_id"] = 2_147_483_648

    response = client.post("/api/production-orders", json=payload)

    assert response.status_code == 401, response.text
    assert _write_counts() == before
