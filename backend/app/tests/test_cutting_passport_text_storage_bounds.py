from datetime import datetime, timezone

import pytest

from app.models import AuditLog, CuttingPassport
from app.tests.conftest import TestSessionLocal


_TEXT_LIMITS = {
    "passport_no": 32,
    "model_code": 128,
    "variant": 64,
    "mold_no": 64,
    "image_ref": 512,
    "operator_name_manual": 128,
    "fabric_type": 128,
    "order_no": 128,
    "lot_no": 64,
    "size_range": 32,
}


def _payload(**overrides):
    return {
        "passport_no": "PASS-TEXT-BOUNDARY",
        "date": datetime(2026, 9, 23, tzinfo=timezone.utc).isoformat(),
        **overrides,
    }


def _write_counts() -> tuple[int, int]:
    with TestSessionLocal() as db:
        return db.query(CuttingPassport).count(), db.query(AuditLog).filter_by(entity_type="CuttingPassport").count()


def test_cutting_passport_accepts_existing_varchar_boundaries(client, auth_headers):
    response = client.post(
        "/api/cutting-passports",
        headers=auth_headers,
        json=_payload(**{field: "x" * limit for field, limit in _TEXT_LIMITS.items()}),
    )
    assert response.status_code == 201, response.text
    for field, limit in _TEXT_LIMITS.items():
        assert len(response.json()[field]) == limit


@pytest.mark.parametrize(("field", "limit"), list(_TEXT_LIMITS.items()))
def test_cutting_passport_create_rejects_oversized_text_without_writes(
    client, auth_headers, field, limit
):
    before = _write_counts()
    response = client.post(
        "/api/cutting-passports",
        headers=auth_headers,
        json=_payload(**{field: "x" * (limit + 1)}),
    )
    assert response.status_code == 422, response.text
    assert _write_counts() == before


def test_cutting_passport_text_limit_preserves_auth_and_missing_reference_precedence(client, auth_headers):
    unauthenticated = client.post(
        "/api/cutting-passports",
        json=_payload(passport_no="x" * 33),
    )
    assert unauthenticated.status_code == 401, unauthenticated.text

    with_missing_order = client.post(
        "/api/cutting-passports",
        headers=auth_headers,
        json=_payload(passport_no="x" * 33, production_order_id=2_147_483_647),
    )
    assert with_missing_order.status_code == 404, with_missing_order.text
