from app.schemas import Model, ModelImage


def attach_test_qolip(db, model: Model) -> None:
    details = model.details_json or {}
    general = details.get("general") or {}
    if not any(general.get(key) for key in ("qolip_no", "qolipNo", "mold_no", "moldNo", "pattern_no", "patternNo")):
        model.details_json = {**details, "general": {**general, "qolip_no": "TEST-QOLIP"}}
    db.add(ModelImage(model=model, image_type="pattern", file_url="/test-fixtures/test-pattern.dxf"))


def attach_test_qolip_for_model(model_id: int) -> None:
    from app.db.session import SessionLocal

    with SessionLocal.begin() as db:
        attach_test_qolip(db, db.get(Model, model_id))
