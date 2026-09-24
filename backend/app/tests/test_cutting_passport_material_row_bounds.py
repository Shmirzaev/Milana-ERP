from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.routes.cutting_passports import _validate_passport_material_limits
from app.models import (
    AuditLog,
    CuttingPassport,
    Department,
    MaterialReservation,
    Model,
    ProductionOrder,
    ProductionOrderMaterial,
    WorkOrder,
)
from app.schemas.cutting_passport import CuttingPassportIn
from app.tests.conftest import TestSessionLocal


MAX_MATERIAL_ROWS = 1000


def _material_rows(count: int) -> list[dict[str, int]]:
    return [
        {
            "stock_batch_id": index + 1,
            "pieces": 1,
            "beka_per_piece_kg": 0,
            "other_beka_per_piece_kg": 0,
            "ribana_per_piece_kg": 0,
            "scrap_kg": 0,
            "layer_weight_kg": 0,
            "total_layers": 0,
            "fabric_width_m": 0,
            "lay_length_m": 0,
            "gramage": 0,
            "planned_kg": 0,
        }
        for index in range(count)
    ]


def _additional_material_rows(count: int) -> list[dict[str, object]]:
    return [
        {"stock_batch_id": index + 1, "estimated_quantity": 1, "unit": "kg"}
        for index in range(count)
    ]


def _payload(**overrides) -> dict:
    return {
        "passport_no": f"MAT-ROWS-{uuid4().hex[:10].upper()}",
        "date": datetime.now(timezone.utc).isoformat(),
        **overrides,
    }


def _linked_order() -> int:
    suffix = uuid4().hex[:10].upper()
    with TestSessionLocal() as db:
        order = ProductionOrder(
            production_no=f"MAT-BOUND-{suffix}",
            production_type="branded_stock",
            model_id=db.query(Model.id).order_by(Model.id).scalar(),
            status="new",
            planned_quantity=1,
        )
        db.add(order)
        db.flush()
        db.add(WorkOrder(
            production_order_id=order.id,
            department_id=db.query(Department.id).filter_by(code="CUT").scalar(),
            operation="cutting",
            status="in_progress",
        ))
        db.commit()
        return order.id


def _write_counts() -> tuple[int, int, int, int]:
    with TestSessionLocal() as db:
        return (
            db.query(CuttingPassport).count(),
            db.query(ProductionOrderMaterial).count(),
            db.query(MaterialReservation).count(),
            db.query(AuditLog).count(),
        )


def test_cutting_passport_material_row_limit_accepts_boundary_before_domain_validation(
    client,
    auth_headers,
):
    order_id = _linked_order()
    before = _write_counts()

    materials = client.post(
        "/api/cutting-passports",
        headers=auth_headers,
        json=_payload(
            production_order_id=order_id,
            materials=_material_rows(MAX_MATERIAL_ROWS),
        ),
    )
    additions = client.post(
        "/api/cutting-passports",
        headers=auth_headers,
        json=_payload(
            production_order_id=order_id,
            additional_materials=_additional_material_rows(MAX_MATERIAL_ROWS),
        ),
    )

    # Both arrays pass the 1,000-row guard and then fail existing order-plan
    # consistency checks before any material, reservation, passport, or audit write.
    assert materials.status_code == 400, materials.text
    assert additions.status_code == 400, additions.text
    assert _write_counts() == before


def test_cutting_passport_rejects_oversized_material_arrays_without_writes(client, auth_headers):
    order_id = _linked_order()
    before = _write_counts()

    materials = client.post(
        "/api/cutting-passports",
        headers=auth_headers,
        json=_payload(
            production_order_id=order_id,
            materials=_material_rows(MAX_MATERIAL_ROWS + 1),
        ),
    )
    additions = client.post(
        "/api/cutting-passports",
        headers=auth_headers,
        json=_payload(
            production_order_id=order_id,
            additional_materials=_additional_material_rows(MAX_MATERIAL_ROWS + 1),
        ),
    )

    assert materials.status_code == 422, materials.text
    assert additions.status_code == 422, additions.text
    assert _write_counts() == before


@pytest.mark.parametrize("field,maximum", [("fabric_type", 128), ("lot_no", 64)])
def test_cutting_passport_material_text_matches_scalar_storage_width(field, maximum):
    row = _material_rows(1)[0]
    row[field] = "x" * maximum
    accepted = CuttingPassportIn.model_validate(_payload(materials=[row]))
    assert _validate_passport_material_limits(accepted) is False

    row[field] += "x"
    rejected = CuttingPassportIn.model_validate(_payload(materials=[row]))
    with pytest.raises(HTTPException, match=f"materials.{field} must be at most {maximum}"):
        _validate_passport_material_limits(rejected)


@pytest.mark.parametrize("field,maximum", [("fabric_type", 128), ("lot_no", 64)])
def test_cutting_passport_rejects_overlong_material_text_without_writes(client, auth_headers, field, maximum):
    order_id = _linked_order()
    row = _material_rows(1)[0]
    row[field] = "x" * (maximum + 1)
    before = _write_counts()

    response = client.post(
        "/api/cutting-passports", headers=auth_headers,
        json=_payload(production_order_id=order_id, materials=[row]),
    )

    assert response.status_code == 422, response.text
    assert _write_counts() == before


def test_unchanged_oversized_legacy_materials_round_trip_on_patch(client, auth_headers):
    passport_no = f"LEGACY-MAT-{uuid4().hex[:10].upper()}"
    legacy_materials = _material_rows(MAX_MATERIAL_ROWS + 1)
    legacy_materials[0]["fabric_type"] = "x" * 129
    legacy_materials[0]["lot_no"] = "y" * 65
    with TestSessionLocal() as db:
        passport = CuttingPassport(
            passport_no=passport_no,
            date=datetime.now(timezone.utc),
            materials=legacy_materials,
        )
        db.add(passport)
        db.commit()
        passport_id = passport.id

    # Sending the exact legacy list is accepted, and omitting the list on a
    # metadata-only PATCH also leaves the stored JSON byte-for-value intact.
    exact = client.patch(
        f"/api/cutting-passports/{passport_id}",
        headers=auth_headers,
        json=_payload(passport_no=passport_no, materials=legacy_materials),
    )
    assert exact.status_code == 200, exact.text
    assert [row["stock_batch_id"] for row in exact.json()["materials"]] == [
        row["stock_batch_id"] for row in legacy_materials
    ]

    omitted = client.patch(
        f"/api/cutting-passports/{passport_id}",
        headers=auth_headers,
        json=_payload(passport_no=passport_no, notes="Unrelated metadata edit"),
    )
    assert omitted.status_code == 200, omitted.text
    assert [row["stock_batch_id"] for row in omitted.json()["materials"]] == [
        row["stock_batch_id"] for row in legacy_materials
    ]
    with TestSessionLocal() as db:
        saved = db.get(CuttingPassport, passport_id)
        assert saved.materials == legacy_materials
        assert saved.notes == "Unrelated metadata edit"


def test_changed_oversized_legacy_materials_are_rejected_without_writes(client, auth_headers):
    order_id = _linked_order()
    passport_no = f"LEGACY-CHANGE-{uuid4().hex[:10].upper()}"
    legacy_materials = _material_rows(MAX_MATERIAL_ROWS + 1)
    with TestSessionLocal() as db:
        passport = CuttingPassport(
            passport_no=passport_no,
            date=datetime.now(timezone.utc),
            production_order_id=order_id,
            materials=legacy_materials,
        )
        db.add(passport)
        db.commit()
        passport_id = passport.id

    changed_materials = [*legacy_materials]
    changed_materials[-1] = {"stock_batch_id": MAX_MATERIAL_ROWS + 2}
    before = _write_counts()

    response = client.patch(
        f"/api/cutting-passports/{passport_id}",
        headers=auth_headers,
        json=_payload(
            passport_no=passport_no,
            production_order_id=order_id,
            materials=changed_materials,
        ),
    )

    assert response.status_code == 422, response.text
    assert _write_counts() == before
    with TestSessionLocal() as db:
        assert db.get(CuttingPassport, passport_id).materials == legacy_materials
