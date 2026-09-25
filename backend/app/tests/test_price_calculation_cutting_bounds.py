from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.db.session import SessionLocal
from app.models import AuditLog, Model, PriceCalculationRequest
from app.schemas.price_calculation import PriceCalculationCuttingIn


def _payload(**overrides) -> dict:
    return {
        "kroy_no": "MANUAL-BOUND",
        "fabric_width_m": 1.72,
        "lay_length_m": 3.1,
        "size_count": 3,
        "gramage": 0.185,
        "binding_kg_per_piece": 0.007,
        **overrides,
    }


def _create_request(client, auth_headers) -> int:
    with SessionLocal() as db:
        model_id = int(
            db.query(Model.id)
            .filter(Model.catalog_scope == "standard")
            .order_by(Model.id)
            .scalar()
        )
    response = client.post(
        "/api/price-calculation/requests",
        headers=auth_headers,
        json={"model_id": model_id},
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def _state(request_id: int) -> tuple[dict, int]:
    with SessionLocal() as db:
        request = db.get(PriceCalculationRequest, request_id)
        assert request is not None
        values = {
            "kroy_no": request.kroy_no,
            "cutting_passport_id": request.cutting_passport_id,
            "fabric_width_m": request.fabric_width_m,
            "lay_length_m": request.lay_length_m,
            "size_count": request.size_count,
            "gramage": request.gramage,
            "binding_kg_per_piece": request.binding_kg_per_piece,
        }
        audit_count = db.query(AuditLog).count()
        return deepcopy(values), audit_count


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("fabric_width_m", "NaN"),
        ("fabric_width_m", "Infinity"),
        ("fabric_width_m", "10000000000"),
        ("lay_length_m", "Infinity"),
        ("lay_length_m", "10000000000"),
        ("size_count", 2_147_483_648),
        ("gramage", "Infinity"),
        ("gramage", "100000000"),
        ("binding_kg_per_piece", "NaN"),
        ("binding_kg_per_piece", "Infinity"),
        ("binding_kg_per_piece", "100000000"),
        ("fabric_width_m", "1.00001"),
        ("lay_length_m", "1.00001"),
        ("gramage", "1.0000001"),
        ("binding_kg_per_piece", "0.0000001"),
    ],
)
def test_cutting_price_fields_reject_non_finite_and_storage_overflow(field, value):
    with pytest.raises(ValidationError):
        PriceCalculationCuttingIn(**_payload(**{field: value}))


def test_cutting_price_fields_preserve_existing_values_and_storage_boundaries():
    parsed = PriceCalculationCuttingIn(**_payload(
        fabric_width_m="9999999999.9999",
        lay_length_m="9999999999.9999",
        size_count=2_147_483_647,
        gramage="99999999.999999",
        binding_kg_per_piece="99999999.999999",
    ))

    assert parsed.fabric_width_m == pytest.approx(9_999_999_999.9999)
    assert parsed.lay_length_m == pytest.approx(9_999_999_999.9999)
    assert parsed.size_count == 2_147_483_647
    assert parsed.gramage == pytest.approx(99_999_999.999999)
    assert parsed.binding_kg_per_piece == pytest.approx(99_999_999.999999)
    assert PriceCalculationCuttingIn(**_payload()).model_dump() == _payload()
    assert PriceCalculationCuttingIn(**_payload(
        fabric_width_m="1.23000", gramage="0.1850000",
    )).fabric_width_m == pytest.approx(1.23)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("fabric_width_m", "Infinity"),
        ("lay_length_m", "10000000000"),
        ("size_count", 2_147_483_648),
        ("gramage", "NaN"),
        ("binding_kg_per_piece", "100000000"),
        ("fabric_width_m", "1.00001"),
        ("gramage", "1.0000001"),
    ],
)
def test_invalid_cutting_price_update_has_no_request_or_audit_side_effects(
    client,
    auth_headers,
    field,
    value,
):
    request_id = _create_request(client, auth_headers)
    before = _state(request_id)

    response = client.patch(
        f"/api/price-calculation/requests/{request_id}/cutting",
        headers=auth_headers,
        json=_payload(**{field: value}),
    )

    assert response.status_code == 422, response.text
    assert _state(request_id) == before


def test_valid_cutting_price_update_remains_compatible(client, auth_headers):
    request_id = _create_request(client, auth_headers)

    response = client.patch(
        f"/api/price-calculation/requests/{request_id}/cutting",
        headers=auth_headers,
        json=_payload(),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kroy_no"] == "MANUAL-BOUND"
    assert body["fabric_width_m"] == pytest.approx(1.72)
    assert body["lay_length_m"] == pytest.approx(3.1)
    assert body["size_count"] == 3
    assert body["gramage"] == pytest.approx(0.185)
    assert body["binding_kg_per_piece"] == pytest.approx(0.007)


def test_invalid_cutting_price_input_preserves_authentication_precedence(client):
    before = _state(1) if _request_exists(1) else None

    response = client.patch(
        "/api/price-calculation/requests/1/cutting",
        json=_payload(fabric_width_m="Infinity"),
    )

    assert response.status_code == 401, response.text
    if before is not None:
        assert _state(1) == before


def _request_exists(request_id: int) -> bool:
    with SessionLocal() as db:
        return db.get(PriceCalculationRequest, request_id) is not None
