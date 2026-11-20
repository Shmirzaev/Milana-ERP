from app.schemas import Model, ModelImage


def attach_test_qolip(db, model: Model) -> None:
    details = model.details_json or {}
    model.details_json = {**details, "general": {**details.get("general", {}), "qolip_no": "TEST-QOLIP"}}
    db.add(ModelImage(model=model, image_type="pattern", file_url="/test-fixtures/test-pattern.dxf"))
