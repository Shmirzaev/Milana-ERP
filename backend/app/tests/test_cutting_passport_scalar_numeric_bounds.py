from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app.api.routes.cutting_passports import _validate_passport_scalar_numeric_limits
from app.models import AuditLog, CuttingPassport
from app.schemas.cutting_passport import CuttingPassportIn
from app.tests.conftest import TestSessionLocal


_STORAGE_BOUNDS = {
    "rolls_count": (2_147_483_647, 2_147_483_648),
    "total_layers": (2_147_483_647, 2_147_483_648),
    "pieces": (2_147_483_647, 2_147_483_648),
    "layer_weight_kg": (9_999_999_999.9999, 10_000_000_000),
    "planned_kg": (9_999_999_999.9999, 10_000_000_000),
    "fabric_width_m": (9_999_999_999.9999, 10_000_000_000),
    "lay_length_m": (9_999_999_999.9999, 10_000_000_000),
    "scrap_kg": (9_999_999_999.9999, 10_000_000_000),
    "gramage": (99_999_999.999999, 100_000_000),
    "beka_per_piece_kg": (99_999_999.999999, 100_000_000),
    "other_beka_per_piece_kg": (99_999_999.999999, 100_000_000),
    "ribana_per_piece_kg": (99_999_999.999999, 100_000_000),
    "waste_pct": (100, 100.0001),
}


def _payload(**overrides) -> dict:
    return {
        "passport_no": "PASS-NUMERIC-BOUND",
        "date": datetime(2026, 9, 25, tzinfo=timezone.utc).isoformat(),
        **overrides,
    }


def _write_counts() -> tuple[int, int]:
    with TestSessionLocal() as db:
        return (
            db.query(CuttingPassport).count(),
            db.query(AuditLog).filter_by(entity_type="CuttingPassport").count(),
        )


@pytest.mark.parametrize(("field", "maximum", "overflow"), [
    (field, *bounds) for field, bounds in _STORAGE_BOUNDS.items()
])
def test_cutting_passport_scalar_limits_match_storage(field, maximum, overflow):
    accepted = CuttingPassportIn.model_validate(_payload(**{field: maximum}))
    _validate_passport_scalar_numeric_limits(accepted)

    rejected = CuttingPassportIn.model_validate(_payload(**{field: overflow}))
    with pytest.raises(HTTPException, match=field) as exc:
        _validate_passport_scalar_numeric_limits(rejected)
    assert exc.value.status_code == 422


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf")])
def test_cutting_passport_scalar_rejects_negative_and_nonfinite(value):
    payload = CuttingPassportIn.model_validate(_payload(planned_kg=value))
    with pytest.raises(HTTPException) as exc:
        _validate_passport_scalar_numeric_limits(payload)
    assert exc.value.status_code == 422


@pytest.mark.parametrize("field", ["rolls_count", "planned_kg", "gramage"])
def test_cutting_passport_create_rejects_scalar_overflow_without_writes(client, auth_headers, field):
    body = _payload(**{field: _STORAGE_BOUNDS[field][1]})
    before = _write_counts()

    assert client.post("/api/cutting-passports", json=body).status_code == 401
    rejected = client.post("/api/cutting-passports", headers=auth_headers, json=body)
    assert rejected.status_code == 422, rejected.text
    assert _write_counts() == before


def test_cutting_passport_scalar_limit_keeps_missing_order_precedence(client, auth_headers):
    response = client.post(
        "/api/cutting-passports",
        headers=auth_headers,
        json=_payload(production_order_id=2_147_483_647, planned_kg=10_000_000_000),
    )
    assert response.status_code == 404, response.text


def test_cutting_passport_update_rejects_scalar_overflow_without_writes(client, auth_headers):
    created = client.post("/api/cutting-passports", headers=auth_headers, json=_payload())
    assert created.status_code == 201, created.text
    before = _write_counts()

    rejected = client.patch(
        f"/api/cutting-passports/{created.json()['id']}",
        headers=auth_headers,
        json=_payload(pieces=2_147_483_648),
    )
    assert rejected.status_code == 422, rejected.text
    assert _write_counts() == before
