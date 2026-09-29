from copy import deepcopy

import pytest

from app.api.routes.catalog import _model_code_parts, _model_group_key
from app.models import AuditLog, Model, ModelSize
from app.tests.conftest import TestSessionLocal
from app.tests.test_paid_operation_factory_scope import _operation
from scripts.reconcile_model_paid_operations import DEFAULTS, apply_plan, digest, make_plan, summary


def _row(mid, code, operations=(), scope="standard", family="model:pj1236", variant="1"):
    details = {"paid_operations": list(operations)}
    return {"id": mid, "code": code, "scope": scope, "family_key": family,
            "variant_no": variant, "legacy": False, "operations": list(operations),
            "details_hash": digest(details)}


def _defaults(factory="milana"):
    return [{"id": f"default-{i}-{factory}", "code": code, "name": name, "section": section,
             "selected": True, "rate": "", "sewingFactory": factory, "quantityMode": "batch",
             "customQuantity": 0, "copies": 1, "splitMode": "none", "splitQuantities": []}
            for i, (code, name, section) in enumerate(DEFAULTS)]


def test_plan_fills_only_missing_and_untouched_defaults_ignoring_storage_ids():
    first = _operation("real", "milana")
    duplicate = {**first, "id": "different-storage-id", "legacySourceId": "historical"}
    rows = [_row(1, "PJ1236", variant=""), _row(2, "PJ1236-1", [first]),
            _row(3, "PJ1236-2", [duplicate]), _row(4, "PJ1236-3", _defaults())]
    plan = make_plan(rows)
    assert summary(plan)["model_rows"] == 2
    assert summary(plan)["parent_models"] == 1
    fill = plan["groups"][0]["fills"][0]
    assert {r["id"] for r in fill["targets"]} == {1, 4}
    assert fill["operations"] == [first]
    assert make_plan([_row(1, "EMPTY"), _row(2, "DEFAULT", _defaults())])["groups"] == []


def test_conflicting_rates_require_choice_and_choice_preserves_populated_siblings():
    first = _operation("real", "milana")
    second = {**first, "rate": "999"}
    rows = [_row(1, "BASE", variant=""), _row(2, "VAR-A", [first]), _row(3, "VAR-B", [second])]
    assert make_plan(rows)["groups"] == []
    assert len(make_plan(rows)["conflicts"]) == 1
    plan = make_plan(rows, {"standard|model:pj1236|milana": "VAR-A"})
    fill = plan["groups"][0]["fills"][0]
    assert [r["id"] for r in fill["targets"]] == [1]
    assert fill["operations"] == [first]
    assert fill["explicit_choice"]


def test_modified_default_is_configured_and_not_replaced():
    defaults = _defaults()
    defaults[0]["rate"] = "5"
    rows = [_row(1, "BASE", variant=""), _row(2, "CUSTOM-DEFAULT", defaults),
            _row(3, "REAL", [_operation("real", "milana")])]
    assert make_plan(rows)["groups"] == []


def test_plan_keeps_catalog_legacy_and_factory_boundaries():
    rows = [_row(1, "BASE", variant=""), _row(2, "SERVICE", [_operation("real", "milana")], scope="usluga"),
            {**_row(3, "LEGACY", [_operation("real", "milana")]), "legacy": True},
            _row(4, "OTHER", [_operation("real", "milana")], family="model:pj12360")]
    assert make_plan(rows)["groups"] == []
    rows.append(_row(5, "UNKNOWN", [{"id": "unscoped", "rate": "100"}]))
    assert make_plan(rows)["groups"] == []
    assert make_plan(rows)["skipped"][0]["reason"] == "unrecognized_factory"


def _snapshot(db):
    return [{"id": r.id, "code": r.code, "scope": r.catalog_scope, "family_key": _model_group_key(r),
             "variant_no": _model_code_parts(r)[1], "legacy": False,
             "operations": deepcopy((r.details_json or {}).get("paid_operations", [])),
             "details_hash": digest(r.details_json or {})}
            for r in db.query(Model).filter(Model.code.like("RECONTEST%")).all()]


def _fixture(db):
    rows = [Model(code="RECONTEST", name="Preserved base", selling_price=55,
                  details_json={"general": {"model_no": "RECONTEST"}, "note": "base note"}),
            Model(code="RECONTEST-1", name="Preserved variant",
                  details_json={"general": {"model_no": "RECONTEST", "variant_no": "1"},
                                "paid_operations": [_operation("real", "milana")]}),
            Model(code="RECONTEST-2", name="Preserved other factory",
                  details_json={"general": {"model_no": "RECONTEST", "variant_no": "2"},
                                "paid_operations": [*_defaults(), _operation("eco", "eco_cotton")]})]
    db.add_all(rows)
    db.flush()
    db.add(ModelSize(model_id=rows[0].id, size="48", measurement_json={"unchanged": True}))
    db.commit()
    return rows


def test_apply_preserves_populated_lists_other_fields_and_is_repeatable(client):
    with TestSessionLocal() as db:
        rows = _fixture(db)
        before = deepcopy(rows[1].details_json)
        plan = make_plan(_snapshot(db))
        result = apply_plan(db, plan, plan["sha256"])
        db.commit()
        assert result["model_rows"] == 3  # Milana and the existing ECO template are shared independently.
        assert rows[0].details_json["note"] == "base note"
        assert rows[0].name == "Preserved base" and float(rows[0].selling_price) == 55
        assert db.query(ModelSize).filter(ModelSize.model_id == rows[0].id).one().measurement_json == {"unchanged": True}
        assert next(r for r in rows[1].details_json["paid_operations"] if r["sewingFactory"] == "milana") == before["paid_operations"][0]
        assert next(r for r in rows[2].details_json["paid_operations"] if r["sewingFactory"] == "eco_cotton")["id"] == "eco"
        assert db.query(AuditLog).filter(AuditLog.action == "reconcile_paid_operations").count() == 4
        assert make_plan(_snapshot(db))["groups"] == []


def test_stale_plan_or_modified_plan_cannot_write(client):
    with TestSessionLocal() as db:
        rows = _fixture(db)
        plan = make_plan(_snapshot(db))
        rows[1].details_json = {**rows[1].details_json, "concurrent_change": True}
        db.commit()
        with pytest.raises(ValueError, match="changed since review"):
            apply_plan(db, plan, plan["sha256"])
        db.rollback()
        assert "paid_operations" not in db.get(Model, rows[0].id).details_json
        changed = deepcopy(plan)
        changed["groups"][0]["fills"][0]["operations"][0]["rate"] = "9999"
        with pytest.raises(ValueError, match="hash"):
            apply_plan(db, changed, plan["sha256"])
