from app.api.routes.process_tracking import _actual_output_quantity


def test_actual_output_quantity_uses_highest_verified_stage_output():
    stages = [
        {"operation": "cutting", "completed": 612},
        {"operation": "sewing", "completed": 620},
        {"operation": "packaging", "completed": 620},
        {"operation": "storage_transfer", "completed": 0},
    ]

    assert _actual_output_quantity(stages) == 620


def test_actual_output_quantity_is_zero_before_production_starts():
    assert _actual_output_quantity([]) == 0
    assert _actual_output_quantity([{"operation": "cutting", "completed": None}]) == 0


def test_process_tracking_factory_filter_returns_only_selected_factory(client):
    from uuid import uuid4

    from app.core.security import create_access_token
    from app.models import Bundle, Model, ProductionOrder
    from app.tests.conftest import TestSessionLocal

    suffix = uuid4().hex[:8].upper()
    with TestSessionLocal() as db:
        model_id = db.query(Model.id).order_by(Model.id).scalar()
        assert model_id is not None
        orders = {}
        for factory_code in ("MIL", "ECO"):
            order = ProductionOrder(
                production_no=f"{factory_code}-TRACK-{suffix}",
                production_type="branded_stock",
                source_type="standard",
                model_id=model_id,
                status="new",
                planned_quantity=10,
            )
            db.add(order)
            db.flush()
            db.add(Bundle(
                bundle_no=f"{factory_code}-TRACK-BND-{suffix}",
                barcode=f"{factory_code}-TRACK-BAR-{suffix}",
                production_order_id=order.id,
                model_id=model_id,
                color="test",
                size="M",
                quantity=10,
                sewing_factory_code=factory_code,
                status="created",
            ))
            orders[factory_code] = order.production_no
        db.commit()

    eco_headers = {
        "Authorization": f"Bearer {create_access_token(1, extra={'factory_code': 'ECO'})}",
    }
    response = client.get(
        f"/api/process-tracking?factory=ECO&q=TRACK-{suffix}",
        headers=eco_headers,
    )

    assert response.status_code == 200, response.text
    production_numbers = {row["production_no"] for row in response.json()}
    assert orders["ECO"] in production_numbers
    assert orders["MIL"] not in production_numbers

    denied = client.get("/api/process-tracking?factory=MIL", headers=eco_headers)
    assert denied.status_code == 403
