import math

import pytest
from pydantic import ValidationError

from app.db.session import SessionLocal
from app.models import (
    AuditLog,
    FinishedGoodsStock,
    IdempotencyRecord,
    Package,
    PackageItem,
)
from app.schemas.tracking import PackageBulkIn, PackageEditPayload, PackageIn


MAX_PACKAGE_WEIGHT = 9_999_999_999.9999


def _payload(**overrides):
    payload = {
        "production_order_id": 1,
        "model_id": 1,
        "color": "navy",
        "items": [{
            "model_id": 1,
            "color": "navy",
            "size": "M",
            "quantity": 1,
        }],
    }
    payload.update(overrides)
    return payload


def _write_counts():
    with SessionLocal() as db:
        return (
            db.query(Package).count(),
            db.query(PackageItem).count(),
            db.query(FinishedGoodsStock).count(),
            db.query(AuditLog).count(),
            db.query(IdempotencyRecord).count(),
        )


def test_package_weight_preserves_optional_float_and_exact_storage_boundary():
    single = PackageIn.model_validate(_payload(weight_kg=str(MAX_PACKAGE_WEIGHT)))
    bulk = PackageBulkIn.model_validate(_payload(
        count=3,
        weight_kg="12.34567",
        weight_kg_values=[None, "0", str(MAX_PACKAGE_WEIGHT)],
    ))
    edit = PackageEditPayload.model_validate({"weight_kg": "12.34567"})

    assert isinstance(single.weight_kg, float)
    assert single.weight_kg == MAX_PACKAGE_WEIGHT
    assert bulk.weight_kg == 12.34567
    assert bulk.weight_kg_values == [None, 0, MAX_PACKAGE_WEIGHT]
    assert edit.weight_kg == 12.34567
    assert PackageIn.model_validate(_payload()).weight_kg is None
    # Keep the established service-level 400 response for negative finite values.
    assert PackageIn.model_validate(_payload(weight_kg=-1)).weight_kg == -1


@pytest.mark.parametrize("weight", ["NaN", "Infinity", "-Infinity", "10000000000"])
@pytest.mark.parametrize(
    "builder",
    [
        lambda value: PackageIn.model_validate(_payload(weight_kg=value)),
        lambda value: PackageBulkIn.model_validate(_payload(count=1, weight_kg_values=[value])),
        lambda value: PackageEditPayload.model_validate({"weight_kg": value}),
    ],
)
def test_package_weight_rejects_nonfinite_or_unrepresentable_values(builder, weight):
    with pytest.raises(ValidationError):
        builder(weight)


@pytest.mark.parametrize(
    ("path", "extra"),
    [
        ("/api/packages", {"weight_kg": "Infinity"}),
        ("/api/packages/bulk", {"count": 1, "weight_kg_values": ["10000000000"]}),
    ],
)
def test_package_weight_api_rejects_before_side_effects_and_preserves_auth(
    client,
    auth_headers,
    path,
    extra,
):
    payload = _payload(**extra)
    before = _write_counts()

    rejected = client.post(path, headers=auth_headers, json=payload)
    unauthenticated = client.post(path, json=payload)

    assert rejected.status_code == 422, rejected.text
    assert unauthenticated.status_code == 401, unauthenticated.text
    assert _write_counts() == before


def test_package_weight_json_contract_rejects_native_nonfinite_numbers():
    for value in (math.nan, math.inf, -math.inf):
        with pytest.raises(ValidationError):
            PackageIn.model_validate(_payload(weight_kg=value))
