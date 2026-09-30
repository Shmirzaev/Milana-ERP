from copy import deepcopy

import pytest

from app.models import Model, ModelColor, ModelImage, ModelSize, SystemSetting, User
from app.tests.conftest import TestSessionLocal
from scripts.reconcile_old_erp_catalog import apply_plan, build_plan, source_record


def source():
    return {"old_model_id": "999", "model_no": "XJ3200", "name": "Q100", "general": {
        "Код Модели": "XJ3200", "Имя": "Q100", "Продукт": "Source shirt"}, "grids": [
        {"headers": ["Размер Варианта Швейной Модели"], "rows": [["1", "S"], ["2", "M"]]},
        {"headers": ["Операции"], "rows": [["1", "Sew", "0.3", "150,50", "UZB", "Tikuv", "", "false"],
                                               ["2", "Pack", "1", "20", "UZB", "Упаковка", "", "true"]]},
        {"headers": ["Вид Расхода"], "rows": [["1", "Cotton", "0.5", "Main"]]},
    ]}


VARIANT = {"old_id": "888", "model_no": "XJ3200", "variant_no": "6427", "sewing_model_ref": "Q100",
           "color": "Blue", "design": "", "thermo": "", "embroidery": ""}
NUMBERING = {"variant_last_assigned": 6427, "models": {"XJ": {"number": 3200}}}


def snapshot(db):
    result = {}
    for table, columns in (
        (Model, ("id", "code", "name", "catalog_scope", "details_json")),
        (ModelSize, ("id", "model_id", "size", "measurement_json")),
        (ModelColor, ("id", "model_id", "color_name", "color_code")),
        (ModelImage, ("id", "model_id", "file_url", "image_type", "is_primary")),
    ):
        result[table.__tablename__] = [{c: getattr(row, c) for c in columns} for row in db.query(table).all()]
    return result


def test_reconciliation_dry_run_then_apply_and_replan(tmp_path):
    with TestSessionLocal() as db:
        actor = db.query(User).first()
        before = snapshot(db)
        settings_before = db.query(SystemSetting).count()
        plan = build_plan(before, [source()], [VARIANT], {}, NUMBERING)
        assert plan["summary"] == {"create": 1, "update": 0, "sizes": 2, "images": 0}
        apply_plan(db, plan, tmp_path, actor.id, dry_run=True)
        assert snapshot(db) == before
        assert db.query(SystemSetting).count() == settings_before
        assert not list(tmp_path.iterdir())
        applied = apply_plan(db, plan, tmp_path, actor.id)
        db.commit()
        model = db.get(Model, applied[0]["id"])
        assert model.status == "draft"
        assert model.name == "Source shirt"
        assert [o["rate"] for o in model.details_json["paid_operations"]] == ["150.50", "20"]
        assert [o["section"] for o in model.details_json["paid_operations"]] == ["sewing", "packaging"]
        assert model.details_json["old_erp_delta_migration"]["recipes"][0]["quantity"] == "0.5"
        assert db.query(SystemSetting).filter_by(key="model_variant_numbering").one().value_json["last_assigned"] == 6427
        assert build_plan(snapshot(db), [source()], [VARIANT], {}, NUMBERING)["entries"] == []


def test_reconciliation_preserves_configured_fields_and_rejects_drift(tmp_path):
    with TestSessionLocal() as db:
        original = {"general": {"model_no": "XJ3200", "variant_no": "V-6427", "qolip_no": "User mold"},
                    "paid_operations": [{"name": "Reviewed", "rate": "999"}], "user_setting": True}
        model = Model(code="XJ3200-6427", name="User name", details_json=deepcopy(original))
        db.add(model)
        db.commit()
        plan = build_plan(snapshot(db), [source()], [VARIANT], {}, NUMBERING)
        entry = plan["entries"][0]
        assert entry["name"] == "User name"
        assert entry["code"] == "XJ3200-6427"
        assert entry["details_json"]["paid_operations"] == original["paid_operations"]
        assert entry["details_json"]["general"]["qolip_no"] == "User mold"
        model.name = "Changed after review"
        db.commit()
        with pytest.raises(ValueError, match="Target changed"):
            apply_plan(db, plan, tmp_path, db.query(User).first().id)
        assert model.details_json == original


def test_duplicate_identity_is_never_merged():
    with TestSessionLocal() as db:
        db.add_all([Model(code="XJ3200-V-6427", name="First"), Model(code="XJ3200-6427", name="Second")])
        db.commit()
        plan = build_plan(snapshot(db), [source()], [VARIANT], {}, NUMBERING)
        assert not plan["entries"]
        assert plan["issues"][0]["reason"] == "existing_duplicates_preserved"


def test_incomplete_source_and_unknown_stage_are_rejected():
    record = source()
    record["grids"][1]["rows"][0][5] = "Unknown"
    with pytest.raises(ValueError, match="Unknown operation"):
        source_record(record)


def test_full_master_catalog_prevents_linking_to_only_captured_duplicate():
    second = {**source(), "old_model_id": "1000"}
    with TestSessionLocal() as db:
        plan = build_plan(snapshot(db), [source()], [VARIANT], {}, NUMBERING, master_catalog=[source(), second])
        assert not plan["entries"]
        assert plan["issues"][0]["reason"] == "source_master_unresolved"
    record = source()
    record["grids"].pop()
    with pytest.raises(ValueError, match="Incomplete detail"):
        source_record(record)
