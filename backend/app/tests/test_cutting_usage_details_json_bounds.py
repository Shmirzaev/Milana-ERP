from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app.api.routes import production


def test_oversized_cutting_usage_edit_rejects_before_any_write(monkeypatch):
    details = {
        "layer_material_kg": 1.0,
        "beika_kg": 0.0,
        "material_rolls_used": 0.0,
        "layup_operator_name": "Operator",
        "legacy_extension": "x" * production._MAX_CUTTING_USAGE_DETAILS_BYTES,
    }
    usage = SimpleNamespace(stock_batch_id=7, details=details, position=1)
    record = SimpleNamespace(
        id=55,
        work_order_id=9,
        layer_material_kg=1.0,
        beika_kg=0.0,
        material_rolls_used=0.0,
        layup_operator_name="Operator",
        notes=None,
        materials=[usage],
    )
    work_order = SimpleNamespace(id=9, operation="cutting")
    query = Mock()
    query.filter.return_value = query
    query.with_for_update.return_value = query
    query.first.return_value = record
    db = Mock()
    db.query.return_value = query
    db.get.return_value = work_order
    monkeypatch.setattr("app.services.factory_scope.require_work_order_factory_access", lambda *_args: None)
    monkeypatch.setattr(production, "log_action", Mock())

    with pytest.raises(HTTPException, match="16 KiB") as exc_info:
        production.update_cutting_record_details(
            55,
            production.CuttingRecordDetailsUpdateIn(layer_material_kg=2.0),
            db,
            SimpleNamespace(id=1),
        )

    assert exc_info.value.status_code == 422
    assert usage.details == details
    db.commit.assert_not_called()


def test_exact_unchanged_oversized_legacy_cutting_details_pass_through():
    legacy = {"old_extension": "x" * production._MAX_CUTTING_USAGE_DETAILS_BYTES}

    production._validate_cutting_usage_details_bounds(legacy, existing=legacy)


def test_changed_deep_cutting_details_reject_before_serialization():
    legacy = None
    changed = value = {}
    for _ in range(production._MAX_CUTTING_USAGE_DETAILS_DEPTH + 1):
        child = {}
        if legacy is None:
            legacy = child
        value["nested"] = child
        value = child

    with pytest.raises(HTTPException, match="nesting depth") as exc_info:
        production._validate_cutting_usage_details_bounds(changed, existing=legacy)

    assert exc_info.value.status_code == 422
