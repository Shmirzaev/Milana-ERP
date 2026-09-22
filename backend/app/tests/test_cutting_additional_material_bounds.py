from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.db.session import SessionLocal
from app.models import AuditLog, CuttingPassport, MaterialReservation, ProductionOrderMaterial
from app.schemas.cutting_passport import CuttingPassportIn, PassportAdditionalMaterial


MAX_MATERIAL_QUANTITY = Decimal("9999999999.9999")


def _payload(quantity: str) -> dict:
    return {
        "passport_no": f"MAT-BOUND-{uuid4().hex[:10].upper()}",
        "date": datetime.now(timezone.utc).isoformat(),
        "additional_materials": [
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
            db.query(CuttingPassport).count(),
            db.query(ProductionOrderMaterial).count(),
            db.query(MaterialReservation).count(),
            db.query(AuditLog).count(),
        )


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "10000000000"])
def test_additional_material_quantity_rejects_non_finite_and_storage_overflow(value):
    with pytest.raises(ValidationError):
        PassportAdditionalMaterial(
            stock_batch_id=1,
            estimated_quantity=value,
            unit="kg",
        )


def test_additional_material_quantity_preserves_extra_precision_and_exact_maximum():
    precise = PassportAdditionalMaterial(
        stock_batch_id=1,
        estimated_quantity="2.34567",
        unit="kg",
    )
    assert precise.estimated_quantity == pytest.approx(2.34567)

    maximum = PassportAdditionalMaterial(
        stock_batch_id=1,
        estimated_quantity=str(MAX_MATERIAL_QUANTITY),
        unit="kg",
    )
    assert maximum.estimated_quantity == pytest.approx(float(MAX_MATERIAL_QUANTITY))
    parsed = CuttingPassportIn(**_payload(str(MAX_MATERIAL_QUANTITY)))
    assert parsed.additional_materials[0].estimated_quantity == pytest.approx(
        float(MAX_MATERIAL_QUANTITY),
    )


def test_invalid_additional_material_quantity_has_no_write_side_effects(
    client,
    auth_headers,
):
    before = _write_counts()

    response = client.post(
        "/api/cutting-passports",
        headers=auth_headers,
        json=_payload("10000000000"),
    )

    assert response.status_code == 422, response.text
    assert _write_counts() == before


def test_invalid_additional_material_quantity_preserves_authentication_precedence(client):
    before = _write_counts()

    response = client.post(
        "/api/cutting-passports",
        json=_payload("10000000000"),
    )

    assert response.status_code == 401, response.text
    assert _write_counts() == before
