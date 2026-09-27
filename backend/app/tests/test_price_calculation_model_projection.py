from uuid import uuid4

from sqlalchemy import event

from app.api.routes.price_calculation import _request_or_404, serialize_price_request
from app.models import Model, PriceCalculationRequest, User
from app.tests.conftest import TestSessionLocal, test_engine


def test_price_request_read_projects_model_fields_used_by_serializer():
    marker = uuid4().hex[:10]
    with TestSessionLocal() as db:
        admin = db.query(User).filter_by(email="admin@example.com").one()
        model = Model(
            code=f"PRICE-{marker}-V1",
            name="Projected price model",
            category="T-shirt",
            product_type="shirt",
            details_json={"general": {"model_no": "PRICE", "variant_no": "V1"}},
            description="unused model details",
        )
        db.add(model)
        db.flush()
        request = PriceCalculationRequest(model_id=model.id, created_by_id=admin.id)
        db.add(request)
        db.commit()
        request_id = request.id

    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(test_engine, "before_cursor_execute", capture)
    try:
        with TestSessionLocal() as db:
            result = serialize_price_request(_request_or_404(db, request_id))
    finally:
        event.remove(test_engine, "before_cursor_execute", capture)

    assert result["model_no"] == "PRICE"
    assert result["variant_no"] == "V1"
    assert result["model_name"] == "Projected price model"
    assert result["model_category"] == "T-shirt"
    request_reads = [statement for statement in statements if " from price_calculation_requests " in statement]
    assert len(request_reads) == 1, statements
    selected_columns = request_reads[0].split(" from ", 1)[0]
    assert "models_1.code" in selected_columns
    assert "models_1.details_json" in selected_columns
    assert "models_1.selling_price" in selected_columns
    assert "models_1.description" not in selected_columns
    assert "models_1.status" not in selected_columns
    assert "models_1.brand_id" not in selected_columns
    assert not any(statement.startswith("select models.") for statement in statements), statements
